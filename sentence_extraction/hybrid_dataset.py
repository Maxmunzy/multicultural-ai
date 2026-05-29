"""Hybrid 모델 학습 Dataset — layoutxlm_bio_train.jsonl + PDF page image.

각 record를 한 batch sample로 변환:
  - LayoutXLM input: words + bboxes + page image → processor (subword tokenize)
  - KoCharELECTRA input: char_text → tokenizer (char tokenize)
  - char_to_word, char_labels는 KoCharELECTRA token level로 align
  - LayoutXLM word_ids (subword → word) 저장

학습 시 forward에서 두 인코더 결과를 char level로 align해서 fusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset


@dataclass
class HybridSample:
    """학습 sample (collate_fn에서 batch로 합칠 dict).

    Fields:
      layoutxlm_inputs: processor output (input_ids, bbox, image, attention_mask) [1, T]
      word_ids: list[int|None] of length T (subword → word index)
      char_input_ids: KoCharELECTRA token ids [Ck]
      char_attention_mask: [Ck]
      char_to_word_tok: [Ck] — 각 KoCharELECTRA token이 어느 word index
      labels: [Ck] — token별 0/1/2 또는 -100 (special/pad)
    """
    layoutxlm_inputs: dict[str, torch.Tensor]
    word_ids: list[int | None]
    char_input_ids: torch.Tensor
    char_attention_mask: torch.Tensor
    char_to_word_tok: torch.Tensor
    labels: torch.Tensor


class HybridDataset(Dataset):
    """layoutxlm_bio_train.jsonl 기반 dataset."""

    def __init__(
        self,
        records: list[dict[str, Any]],
        pdf_dir: Path,
        layoutxlm_processor,
        char_tokenizer,
        max_layoutxlm_len: int = 512,
        max_char_len: int = 512,
        image_dpi: int = 150,
        is_train: bool = True,
    ):
        self.records = records
        self.pdf_dir = pdf_dir
        self.layoutxlm_processor = layoutxlm_processor
        self.char_tokenizer = char_tokenizer
        self.max_lxlm = max_layoutxlm_len
        self.max_char = max_char_len
        self.image_dpi = image_dpi
        # train: 매 __getitem__ 호출마다 random window crop (page 중간 시작 학습 신호)
        # val:   항상 page 첫 510자 (평가 일관성)
        self.is_train = is_train

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        rec = self.records[idx]
        pdf_path = self.pdf_dir / rec["pdf"]
        page_idx = rec["page"]

        # 1. PDF page image — corrupt PDF (structure tree 깨진 경우 등)는 blank fallback
        import sys
        import fitz
        from PIL import Image
        try:
            doc = fitz.open(pdf_path)
            page = doc[page_idx]
            pix = page.get_pixmap(dpi=self.image_dpi)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            doc.close()
        except Exception as e:
            print(f"  [warning] fitz failed on {rec['pdf']} page {page_idx}: {e}", file=sys.stderr)
            image = Image.new("RGB", (224, 224), (255, 255, 255))

        # 2. LayoutXLM processor (subword tokenize)
        words = rec["words"]
        bboxes = rec["bboxes"]
        lxlm_encoded = self.layoutxlm_processor(
            image, words, boxes=bboxes,
            return_tensors="pt", truncation=True,
            padding="max_length", max_length=self.max_lxlm,
        )
        # word_ids: subword → word
        word_ids = lxlm_encoded.word_ids()
        # squeeze batch dim
        layoutxlm_inputs = {k: v.squeeze(0) for k, v in lxlm_encoded.items() if hasattr(v, "squeeze")}

        # 3. KoCharELECTRA tokenize (char text)
        char_text = rec["char_text"]
        char_labels = rec["char_labels"]
        char_to_word = rec["char_to_word"]

        # truncate char-level data — train은 random window, val은 첫 510자 고정
        max_keep = self.max_char - 2  # CLS + SEP
        if len(char_text) > max_keep:
            if self.is_train:
                import random
                start = random.randint(0, len(char_text) - max_keep)
            else:
                start = 0
            char_text = char_text[start : start + max_keep]
            char_labels = char_labels[start : start + max_keep]
            char_to_word = char_to_word[start : start + max_keep]

        char_enc = self.char_tokenizer(
            char_text,
            return_offsets_mapping=True,
            add_special_tokens=False,
            truncation=True,
            max_length=self.max_char - 2,
        )
        char_tokens = char_enc["input_ids"]
        offsets = char_enc["offset_mapping"]

        # token별 라벨 + char_to_word 매핑 — token의 첫 char 기준
        token_labels: list[int] = []
        token_to_word: list[int] = []
        for start, end in offsets:
            if start < len(char_labels):
                token_labels.append(char_labels[start])
                token_to_word.append(char_to_word[start])
            else:
                token_labels.append(-100)
                token_to_word.append(-1)

        # CLS + tokens + SEP, special token은 ignore
        cls_id = self.char_tokenizer.cls_token_id
        sep_id = self.char_tokenizer.sep_token_id
        pad_id = self.char_tokenizer.pad_token_id

        input_ids = [cls_id] + char_tokens + [sep_id]
        labels = [-100] + token_labels + [-100]
        c2w = [-1] + token_to_word + [-1]
        attn = [1] * len(input_ids)

        # Pad to max_char
        pad_len = self.max_char - len(input_ids)
        input_ids += [pad_id] * pad_len
        attn += [0] * pad_len
        labels += [-100] * pad_len
        c2w += [-1] * pad_len

        return {
            "layoutxlm_inputs": layoutxlm_inputs,
            "word_ids": word_ids,
            "char_input_ids": torch.tensor(input_ids, dtype=torch.long),
            "char_attention_mask": torch.tensor(attn, dtype=torch.long),
            "char_to_word_tok": torch.tensor(c2w, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def hybrid_collate_fn(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """batch 묶기. word_ids는 list 그대로 (가변 길이)."""
    # LayoutXLM inputs은 이미 max_length로 pad됐으므로 stack
    layoutxlm_inputs: dict[str, torch.Tensor] = {}
    keys = samples[0]["layoutxlm_inputs"].keys()
    for k in keys:
        layoutxlm_inputs[k] = torch.stack([s["layoutxlm_inputs"][k] for s in samples])

    word_ids_list = [s["word_ids"] for s in samples]

    return {
        "layoutxlm_inputs": layoutxlm_inputs,
        "word_ids_list": word_ids_list,
        "char_input_ids": torch.stack([s["char_input_ids"] for s in samples]),
        "char_attention_mask": torch.stack([s["char_attention_mask"] for s in samples]),
        "char_to_word": torch.stack([s["char_to_word_tok"] for s in samples]),
        "labels": torch.stack([s["labels"] for s in samples]),
    }
