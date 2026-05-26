"""LayoutXLM sentence extraction — 통합 모델 추론.

본문/표 구분 없이 단일 LayoutXLM 모델로 token별 group_id 예측 → 같은 group 묶음 = sentence.

추론 흐름:
  PDF → page별:
    - pdfplumber로 word + bbox
    - pymupdf로 page image 렌더링
    - LayoutXLM forward → token별 group_id
    - 같은 group 묶음 sentence (등장 순서 보존)
  → sentence_list

옵션: attr별 후처리 분리 (Claude 통합 형식이 길게 나오면 ", " 등으로 split)
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


class LayoutXLMInferer:
    """LayoutXLM 기반 sentence extractor."""

    def __init__(self, checkpoint_path: str | Path, device: str | None = None):
        import torch
        from transformers import LayoutXLMProcessor, LayoutLMv2ForTokenClassification

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ckpt = torch.load(str(checkpoint_path), map_location=self.device, weights_only=False)
        model_id = ckpt.get("model_id", "microsoft/layoutxlm-base")
        self.num_labels = ckpt.get("num_labels", 130)
        self.max_sent_id = ckpt.get("max_sent_id", self.num_labels - 1)

        self.processor = LayoutXLMProcessor.from_pretrained(model_id, apply_ocr=False)
        self.model = LayoutLMv2ForTokenClassification.from_pretrained(
            model_id, num_labels=self.num_labels,
        ).to(self.device)
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()
        print(f"LayoutXLM loaded: {model_id}, num_labels={self.num_labels}, device={self.device}", file=sys.stderr)

    def _extract_page_input(self, pdf_path: Path, page_idx: int) -> tuple[list[str], list[list[int]], Any] | None:
        """Page에서 word + bbox + image 추출."""
        import pdfplumber
        import fitz
        from PIL import Image

        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return None
            page = pdf.pages[page_idx]
            W, H = page.width, page.height
            if W <= 0 or H <= 0:
                return None
            words: list[str] = []
            boxes: list[list[int]] = []
            for w in page.extract_words(
                use_text_flow=True, keep_blank_chars=False,
                x_tolerance=3, y_tolerance=3,
            ):
                words.append(w["text"])
                x0, y0, x1, y1 = w["x0"], w["top"], w["x1"], w["bottom"]
                boxes.append([
                    max(0, min(1000, int(x0 / W * 1000))),
                    max(0, min(1000, int(y0 / H * 1000))),
                    max(0, min(1000, int(x1 / W * 1000))),
                    max(0, min(1000, int(y1 / H * 1000))),
                ])

        # page image 렌더링
        doc = fitz.open(pdf_path)
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()

        return words, boxes, image

    def extract_sentences(self, pdf_path: Path) -> list[str]:
        """PDF에서 sentence_list 추출 — 본문/표 모두 LayoutXLM이 처리."""
        import fitz

        # 전체 page 수
        doc = fitz.open(pdf_path)
        n_pages = len(doc)
        doc.close()

        all_sentences: list[str] = []
        for page_idx in range(n_pages):
            page_data = self._extract_page_input(pdf_path, page_idx)
            if page_data is None:
                continue
            words, boxes, image = page_data
            if not words:
                continue

            encoded = self.processor(
                image, words, boxes=boxes,
                return_tensors="pt", truncation=True,
                padding="max_length", max_length=512,
            )
            encoded_dev = {k: v.to(self.device) for k, v in encoded.items()}

            with self.torch.no_grad():
                outputs = self.model(**encoded_dev)
            predictions = outputs.logits.argmax(-1)[0].cpu().tolist()

            # token → word level (majority vote)
            word_ids = encoded.word_ids()
            word_preds: dict[int, list[int]] = defaultdict(list)
            for ti, wi in enumerate(word_ids):
                if wi is None:
                    continue
                word_preds[wi].append(predictions[ti])

            word_label: list[int] = []
            for wi in range(len(words)):
                if wi in word_preds and word_preds[wi]:
                    counts: dict[int, int] = {}
                    for p in word_preds[wi]:
                        counts[p] = counts.get(p, 0) + 1
                    word_label.append(max(counts, key=counts.get))
                else:
                    word_label.append(-1)

            # 같은 group_id 묶음 → sentence (첫 등장 순서 보존, unlabeled/padding 제외)
            groups: dict[int, list[str]] = defaultdict(list)
            first_app: dict[int, int] = {}
            for idx, (w, lab) in enumerate(zip(words, word_label)):
                if lab < 0 or lab >= self.max_sent_id:  # unlabeled or padding label
                    continue
                groups[lab].append(w)
                first_app.setdefault(lab, idx)
            sorted_groups = sorted(groups.keys(), key=lambda g: first_app[g])

            for g in sorted_groups:
                sent = " ".join(groups[g]).strip()
                if sent:
                    all_sentences.append(sent)

        return all_sentences


def split_attr_sentences(sentence: str) -> list[str]:
    """Claude 통합 형식 sentence → attr별 분리.

    형식 예: "엔티티 - attr1: v1, attr2: v2, attr3: v3"
      → ["엔티티 - attr1: v1", "엔티티 - attr2: v2", "엔티티 - attr3: v3"]

    분리 규칙:
      - " - " 가 있으면 entity prefix 추출
      - ", " 로 split 후 ":" 포함된 토막만 attr로 인정
      - entity prefix를 각 attr 토막에 붙임

    분리할 수 없으면 원본 그대로.
    """
    if " - " not in sentence:
        return [sentence]
    # 마지막 " - " 기준으로 split — entity 안에 " - "가 2번 이상 있을 때 대응
    # (예: "가만히 들어주었어 - 비밀친구 모루토끼 인형 만들기 - 날짜: ..., 대상: ...")
    head, rest = sentence.rsplit(" - ", 1)
    parts = [p.strip() for p in rest.split(", ")]
    if len(parts) < 2:
        return [sentence]
    attr_parts: list[str] = []
    non_attr_buffer: list[str] = []
    for p in parts:
        if ":" in p:
            if non_attr_buffer:
                # 이전 attr에 붙여놓을 부분 (e.g. "내용: a, b, c" 같은 경우)
                if attr_parts:
                    attr_parts[-1] = attr_parts[-1] + ", " + ", ".join(non_attr_buffer)
                non_attr_buffer = []
            attr_parts.append(p)
        else:
            non_attr_buffer.append(p)
    if non_attr_buffer and attr_parts:
        attr_parts[-1] = attr_parts[-1] + ", " + ", ".join(non_attr_buffer)
    if not attr_parts:
        return [sentence]
    return [f"{head} - {ap}" for ap in attr_parts]


def post_process(sentences: list[str], split_attr: bool = True) -> list[str]:
    """sentence_list 후처리.

    - split_attr=True: Claude 통합 형식 (entity - attr1: v1, attr2: v2)을 attr별로 분리
    - 너무 짧은 단편(2자 미만) 제거
    """
    out: list[str] = []
    for s in sentences:
        s = s.strip()
        if len(s) < 2:
            continue
        if split_attr:
            out.extend(split_attr_sentences(s))
        else:
            out.append(s)
    return out


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
    ap.add_argument("--no-split-attr", action="store_true", help="attr별 분리 후처리 끄기")
    args = ap.parse_args()

    inf = LayoutXLMInferer(args.checkpoint)
    raw_sents = inf.extract_sentences(args.file)
    sents = post_process(raw_sents, split_attr=not args.no_split_attr)

    print(f"=== {args.file.name} ===")
    print(f"Raw sentences: {len(raw_sents)}")
    print(f"After post-process: {len(sents)}\n")
    for i, s in enumerate(sents):
        print(f"  [{i:02d}] {s}")
