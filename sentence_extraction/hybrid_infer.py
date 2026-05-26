"""Hybrid Sentence Extractor 추론 — PDF → sentence_list.

학습된 hybrid_best.pt로 PDF page를 처리해서 char별 BIO 예측 → B 위치마다 sentence 분리.

흐름 (학습과 동일):
  PDF page → word + bbox + image
  → LayoutXLMProcessor + KoCharELECTRA tokenizer
  → HybridSentenceExtractor.forward
  → char별 BIO logits
  → B 위치마다 sentence 시작 (변형 0: 원문 char substring)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import torch


class HybridInferer:
    """Hybrid 모델 추론 wrapper."""

    def __init__(self, checkpoint_path: str | Path, device: str | None = None):
        from transformers import LayoutXLMProcessor, AutoTokenizer
        from hybrid_model import HybridSentenceExtractor, HybridConfig

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ckpt = torch.load(str(checkpoint_path), map_location=self.device, weights_only=False)
        # config 복원
        config_dict = ckpt.get("config", {})
        # tuple 복원 (json save 시 list로 됐을 수도)
        if "class_weights" in config_dict and isinstance(config_dict["class_weights"], list):
            config_dict["class_weights"] = tuple(config_dict["class_weights"])
        config = HybridConfig(**config_dict)

        self.model = HybridSentenceExtractor(config).to(self.device)
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()

        self.processor = LayoutXLMProcessor.from_pretrained(config.layoutxlm_id, apply_ocr=False)
        self.tokenizer = AutoTokenizer.from_pretrained(config.kochar_id)
        self.config = config
        print(f"Hybrid loaded: device={self.device}, trainable_only={sum(p.numel() for p in self.model.parameters() if p.requires_grad)/1e6:.1f}M", file=sys.stderr)

    def _extract_page(self, pdf_path: Path, page_idx: int) -> tuple[list[str], list[list[int]], Any] | None:
        """Page → word + bbox + image.

        한글자 word 단편 합치기 (자간 큰 헤더 처리) — 학습 데이터와 동일 로직.
        """
        import pdfplumber
        import fitz
        from PIL import Image
        from parser_ensemble import dedup_overlapping_words, merge_singleton_words

        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return None
            page = pdf.pages[page_idx]
            W, H = page.width, page.height
            if W <= 0 or H <= 0:
                return None
            raw_words = page.extract_words(
                use_text_flow=True, keep_blank_chars=False,
                x_tolerance=3, y_tolerance=3,
            )
            raw_words = dedup_overlapping_words(raw_words)
            raw_words = merge_singleton_words(raw_words)
            words: list[str] = []
            bboxes: list[list[int]] = []
            for w in raw_words:
                words.append(w["text"])
                x0, y0, x1, y1 = w["x0"], w["top"], w["x1"], w["bottom"]
                bboxes.append([
                    max(0, min(1000, int(x0 / W * 1000))),
                    max(0, min(1000, int(y0 / H * 1000))),
                    max(0, min(1000, int(x1 / W * 1000))),
                    max(0, min(1000, int(y1 / H * 1000))),
                ])
        doc = fitz.open(pdf_path)
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return words, bboxes, image

    def _build_char_text(self, words: list[str]) -> tuple[str, list[int]]:
        """words → char_text + char_to_word (학습 데이터와 동일 규칙)."""
        char_text_parts: list[str] = []
        char_to_word: list[int] = []
        for wi, word in enumerate(words):
            if not word:
                continue
            if char_text_parts:
                char_text_parts.append(" ")
                char_to_word.append(wi - 1 if wi > 0 else 0)
            for c in word:
                char_text_parts.append(c)
                char_to_word.append(wi)
        return "".join(char_text_parts), char_to_word

    def _forward_chunk(
        self, chunk_text: str, chunk_c2w: list[int],
        chunk_words: list[str], chunk_bboxes: list[list[int]], image,
        max_lxlm: int, max_char: int,
    ) -> list[tuple[int, int]]:
        """한 chunk 처리. Returns (B 위치 char index, next char index) 페어 list — 매 B마다 sentence span 만들기 위함."""
        # LayoutXLM
        lxlm_encoded = self.processor(
            image, chunk_words, boxes=chunk_bboxes,
            return_tensors="pt", truncation=True,
            padding="max_length", max_length=max_lxlm,
        )
        word_ids = lxlm_encoded.word_ids()
        layoutxlm_inputs = {k: v.to(self.device) for k, v in lxlm_encoded.items() if hasattr(v, "squeeze")}

        # KoCharELECTRA
        char_enc = self.tokenizer(
            chunk_text, return_offsets_mapping=True, add_special_tokens=False,
            truncation=True, max_length=max_char - 2,
        )
        char_tokens = char_enc["input_ids"]
        offsets = char_enc["offset_mapping"]
        token_to_word = [chunk_c2w[s] if s < len(chunk_c2w) else -1 for s, _ in offsets]

        cls_id = self.tokenizer.cls_token_id
        sep_id = self.tokenizer.sep_token_id
        pad_id = self.tokenizer.pad_token_id
        input_ids = [cls_id] + char_tokens + [sep_id]
        c2w = [-1] + token_to_word + [-1]
        attn = [1] * len(input_ids)
        pad_len = max_char - len(input_ids)
        input_ids += [pad_id] * pad_len
        attn += [0] * pad_len
        c2w += [-1] * pad_len
        n_real = max_char - pad_len

        char_input_ids = torch.tensor([input_ids], dtype=torch.long).to(self.device)
        char_attention_mask = torch.tensor([attn], dtype=torch.long).to(self.device)
        char_to_word_t = torch.tensor([c2w], dtype=torch.long).to(self.device)

        with torch.no_grad():
            outputs = self.model(
                layoutxlm_inputs=layoutxlm_inputs,
                word_ids_list=[word_ids],
                char_input_ids=char_input_ids,
                char_attention_mask=char_attention_mask,
                char_to_word=char_to_word_t,
                labels=None,
            )
        if self.model.crf is not None and "predictions" in outputs:
            # CRF Viterbi decode — list of int, length = mask sum (n_real)
            preds = outputs["predictions"][0]
        else:
            preds = outputs["logits"].argmax(-1)[0].cpu().tolist()

        # B 위치 char index 찾기 — chunk_text 기준
        b_positions: list[int] = []  # B-SENT 시작 char index
        for tok_i, (s, e) in enumerate(offsets):
            real_idx = tok_i + 1
            if real_idx >= n_real - 1:
                break
            if real_idx >= len(preds):
                break
            if preds[real_idx] == 1:  # B-SENT
                b_positions.append(s)
        return b_positions

    def extract_page_sentences(
        self, pdf_path: Path, page_idx: int,
        max_lxlm: int = 512, max_char: int = 512,
        char_stride: int = 400,
    ) -> list[str]:
        """단일 page에서 sentence_list 추출 — sliding window로 긴 page 처리."""
        page_data = self._extract_page(pdf_path, page_idx)
        if page_data is None:
            return []
        words, bboxes, image = page_data
        if not words:
            return []

        # 전체 char_text + char_to_word 만들기 (truncation 없이)
        char_text, char_to_word = self._build_char_text(words)
        if not char_text:
            return []

        chunk_size = max_char - 2  # CLS + SEP 제외
        all_b_positions: set[int] = set()  # 전체 char 기준 B-SENT 위치

        # Sliding window
        start = 0
        while start < len(char_text):
            end = min(start + chunk_size, len(char_text))
            chunk_text = char_text[start:end]
            chunk_c2w_abs = char_to_word[start:end]  # 절대 word index

            # 이 chunk에서 사용하는 word range
            valid_w = [w for w in chunk_c2w_abs if w >= 0]
            if not valid_w:
                start += char_stride
                continue
            min_w, max_w = min(valid_w), max(valid_w)
            chunk_words = words[min_w : max_w + 1]
            chunk_bboxes = bboxes[min_w : max_w + 1]
            chunk_c2w_local = [(w - min_w) if w >= 0 else -1 for w in chunk_c2w_abs]

            try:
                b_rel = self._forward_chunk(
                    chunk_text, chunk_c2w_local, chunk_words, chunk_bboxes, image,
                    max_lxlm, max_char,
                )
            except Exception as e:
                print(f"  chunk forward FAIL [{start}:{end}]: {e}", file=sys.stderr)
                start += char_stride
                continue

            # 절대 char 위치로 변환
            for b in b_rel:
                all_b_positions.add(start + b)

            if end >= len(char_text):
                break
            start += char_stride

        # B 위치 sort → sentence span 만들기
        sorted_b = sorted(all_b_positions)
        sentences: list[str] = []
        if sorted_b:
            # 첫 B 이전은 sentence 아님 (또는 O 영역)
            for i, b_pos in enumerate(sorted_b):
                end_pos = sorted_b[i + 1] if i + 1 < len(sorted_b) else len(char_text)
                sent = char_text[b_pos:end_pos].strip()
                if sent:
                    sentences.append(sent)
        return sentences

    def extract_sentences(self, pdf_path: Path) -> list[str]:
        """전체 PDF → sentence_list (page별 처리 후 합침)."""
        import fitz
        doc = fitz.open(pdf_path)
        n_pages = len(doc)
        doc.close()
        all_sents: list[str] = []
        for page_idx in range(n_pages):
            all_sents.extend(self.extract_page_sentences(pdf_path, page_idx))
        return all_sents


if __name__ == "__main__":
    import argparse
    import io

    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--file", required=True, type=Path)
    args = ap.parse_args()

    inf = HybridInferer(args.checkpoint)
    sents = inf.extract_sentences(args.file)
    print(f"=== {args.file.name} ===")
    print(f"Sentences: {len(sents)}\n")
    for i, s in enumerate(sents):
        print(f"  [{i:02d}] {s}")
