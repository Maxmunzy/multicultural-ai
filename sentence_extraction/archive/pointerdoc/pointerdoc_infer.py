"""PointerDoc 추론 — PDF → sentence_list (변형 0 구조적 보장).

학습된 PointerDoc checkpoint로 PDF에서 sentence_list 추출.
텍스트는 pdfplumber rows에서 직접 가져오므로 환각 0.

사용:
    python sentence_extraction/pointerdoc_infer.py \\
        --checkpoint sentence_extraction/data/pointerdoc_best.pt \\
        --pdf backend/data/sample.pdf
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Any

import fitz  # pymupdf
import pdfplumber
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoTokenizer

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from pointerdoc_model import PointerDoc, PointerDocConfig


class PointerDocInferer:
    """PointerDoc 모델 로더 + PDF → sentence_list 추론."""

    def __init__(self, checkpoint_path: str | Path, device: str | None = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ckpt = torch.load(str(checkpoint_path), map_location=self.device, weights_only=False)
        self.cfg = PointerDocConfig(**ckpt["cfg"])
        self.model = PointerDoc(self.cfg).to(self.device)
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()
        self.processor = AutoImageProcessor.from_pretrained(self.cfg.vision_model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(self.cfg.text_model_id)
        print(f"PointerDoc loaded: device={self.device}, max_rows={self.cfg.max_rows}", file=sys.stderr)

    @staticmethod
    def _extract_rows(pdf_path: Path, page_idx: int) -> list[dict[str, Any]]:
        """pymupdf get_text('dict') line 단위 row 추출.

        v3/v4 학습 데이터와 동일 방식 (pdfplumber X). PDF block 구조 그대로 사용.
        """
        rows: list[dict[str, Any]] = []
        doc = fitz.open(pdf_path)
        if page_idx >= len(doc):
            doc.close()
            return []
        page = doc[page_idx]
        page_w = float(page.rect.width)
        page_h = float(page.rect.height)
        data = page.get_text("dict")
        for b in data.get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            for line in b.get("lines", []):
                text = " ".join(span["text"] for span in line.get("spans", [])).strip()
                if not text:
                    continue
                bbox = line.get("bbox", [0, 0, 0, 0])
                rows.append({
                    "text": text,
                    "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                    "page_width": page_w,
                    "page_height": page_h,
                })
        doc.close()
        return rows

    @staticmethod
    def _render_page(pdf_path: Path, page_idx: int, max_side: int = 518) -> Image.Image:
        """PDF 페이지 → PIL RGB Image (longer side = max_side)."""
        doc = fitz.open(pdf_path)
        page = doc[page_idx]
        longer = max(float(page.rect.width), float(page.rect.height))
        zoom = max_side / longer if longer > 0 else 1.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return img

    @staticmethod
    def _normalize_bbox(bbox: list[float], pw: float, ph: float) -> list[float]:
        x0, y0, x1, y1 = bbox
        return [
            max(0.0, min(1.0, x0 / pw)),
            max(0.0, min(1.0, y0 / ph)),
            max(0.0, min(1.0, x1 / pw)),
            max(0.0, min(1.0, y1 / ph)),
        ]

    @torch.no_grad()
    def extract_page(
        self,
        pdf_path: Path,
        page_idx: int = 0,
        active_threshold: float = 0.5,
        row_threshold: float = 0.5,
    ) -> list[str]:
        """한 페이지에서 sentence_list 추출."""
        rows = self._extract_rows(pdf_path, page_idx)
        if not rows:
            return []
        n = len(rows)
        if n > self.cfg.max_rows:
            return []  # 너무 많은 행 — skip

        # Image
        img = self._render_page(pdf_path, page_idx)
        pixel = self.processor(images=img, return_tensors="pt")["pixel_values"].to(self.device)

        # bboxes (padded to max_rows)
        bboxes = torch.zeros(1, self.cfg.max_rows, 4, device=self.device)
        for i, r in enumerate(rows):
            bboxes[0, i] = torch.tensor(
                self._normalize_bbox(r["bbox"], r["page_width"], r["page_height"]),
                device=self.device,
            )

        # row mask
        mask = torch.zeros(1, self.cfg.max_rows, dtype=torch.bool, device=self.device)
        mask[0, :n] = True

        # text tokens
        texts = [r["text"] for r in rows]
        max_t = self.cfg.text_max_length
        tok = self.tokenizer(
            texts, padding="max_length", truncation=True, max_length=max_t, return_tensors="pt"
        )
        text_ids = torch.zeros(1, self.cfg.max_rows, max_t, dtype=torch.long, device=self.device)
        text_mask = torch.zeros(1, self.cfg.max_rows, max_t, dtype=torch.long, device=self.device)
        text_ids[0, :n] = tok["input_ids"].to(self.device)
        text_mask[0, :n] = tok["attention_mask"].to(self.device)

        # Predict
        preds = self.model.predict(
            pixel, bboxes, mask,
            text_ids=text_ids, text_mask=text_mask,
            active_threshold=active_threshold,
            row_threshold=row_threshold,
        )

        # row_ids → sentence text (pdfplumber row text 그대로 concat = 변형 0 보장)
        sentences: list[str] = []
        for row_ids in preds[0]:
            txt = " ".join(rows[i]["text"] for i in sorted(row_ids) if 0 <= i < n)
            if txt.strip():
                sentences.append(txt)
        return sentences

    @torch.no_grad()
    def extract_pdf(
        self,
        pdf_path: Path,
        active_threshold: float = 0.5,
        row_threshold: float = 0.5,
    ) -> list[str]:
        """전체 페이지 sentence_list 합침."""
        doc = fitz.open(pdf_path)
        n_pages = len(doc)
        doc.close()
        all_sents: list[str] = []
        for p in range(n_pages):
            sents = self.extract_page(
                pdf_path, page_idx=p,
                active_threshold=active_threshold,
                row_threshold=row_threshold,
            )
            all_sents.extend(sents)
        return all_sents


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=None, help="없으면 전체 페이지")
    ap.add_argument("--active-threshold", type=float, default=0.5)
    ap.add_argument("--row-threshold", type=float, default=0.5)
    args = ap.parse_args()

    inf = PointerDocInferer(args.checkpoint)
    if args.page_idx is not None:
        sents = inf.extract_page(
            args.pdf, page_idx=args.page_idx,
            active_threshold=args.active_threshold,
            row_threshold=args.row_threshold,
        )
    else:
        sents = inf.extract_pdf(
            args.pdf,
            active_threshold=args.active_threshold,
            row_threshold=args.row_threshold,
        )

    print(f"PDF: {args.pdf.name}")
    print(f"Sentences ({len(sents)}):")
    for i, s in enumerate(sents):
        print(f"  [{i:02d}] {s}")


if __name__ == "__main__":
    main()
