"""End-to-end pipeline — Format routing + Parser + KoCharELECTRA BIO + sentence list.

흐름:
  PDF/HWP/HWPX → format별 parser → cleaned text
                      → KoCharELECTRA BIO → sentence_list (변형 0)

사용:
    python sentence_extraction/extract_sentences.py \\
        --checkpoint sentence_extraction/data/kocharelectra_bio_best.pt \\
        --file <path.pdf | .hwp | .hwpx>
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


def extract_text_pdf(pdf_path: Path) -> str:
    """pymupdf get_text('dict') — block 단위 자연스러운 join."""
    import fitz
    doc = fitz.open(pdf_path)
    text_blocks: list[str] = []
    for page in doc:
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            lines: list[str] = []
            for line in b.get("lines", []):
                t = " ".join(s["text"] for s in line.get("spans", [])).strip()
                if t:
                    lines.append(t)
            if lines:
                text_blocks.append(" ".join(lines))
    doc.close()
    return "\n".join(text_blocks)


def extract_text_hwpx(hwpx_path: Path) -> str:
    """HWPX = zip + XML — Section0.xml의 paragraph text 추출."""
    import xml.etree.ElementTree as ET
    texts: list[str] = []
    with zipfile.ZipFile(hwpx_path) as z:
        section_names = [n for n in z.namelist() if "section" in n.lower() and n.endswith(".xml")]
        for sec_name in section_names:
            sec_xml = z.read(sec_name).decode("utf-8")
            root = ET.fromstring(sec_xml)
            for elem in root.iter():
                t = (elem.text or "").strip()
                if t:
                    texts.append(t)
    return "\n".join(texts)


def extract_text_hwp(hwp_path: Path) -> str:
    """pyhwp의 hwp5txt CLI 호출 (Python에서 module로 호출도 가능)."""
    import subprocess
    r = subprocess.run(
        ["hwp5txt", str(hwp_path)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if r.returncode != 0:
        print(f"hwp5txt failed: {r.stderr[:200]}", file=sys.stderr)
        return ""
    return r.stdout


def extract_text(file_path: Path) -> tuple[str, str]:
    """Format detection → text 추출. Returns (text, format_name)."""
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_pdf(file_path), "pdf"
    if suffix == ".hwpx":
        return extract_text_hwpx(file_path), "hwpx"
    if suffix == ".hwp":
        return extract_text_hwp(file_path), "hwp"
    raise ValueError(f"Unsupported format: {suffix}")


def extract_text_ensemble(file_path: Path) -> tuple[str, str, dict[str, float]]:
    """Parser ensemble + selection — 진짜 architecture."""
    from parser_ensemble import extract_text as _ext
    return _ext(file_path)


class BIOInferer:
    """KoCharELECTRA BIO 모델 로드 + sentence_list 추출."""

    def __init__(self, checkpoint_path: str | Path, device: str | None = None):
        import torch
        from transformers import AutoTokenizer, ElectraModel
        import torch.nn as nn

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ckpt = torch.load(str(checkpoint_path), map_location=self.device, weights_only=False)
        model_id = ckpt.get("model_id", "monologg/kocharelectra-small-discriminator")
        self.max_len = ckpt.get("max_len", 512)

        class BIOTagger(nn.Module):
            def __init__(self, mid, num_labels=3):
                super().__init__()
                self.electra = ElectraModel.from_pretrained(mid)
                hidden = self.electra.config.hidden_size
                self.dropout = nn.Dropout(0.1)
                self.classifier = nn.Linear(hidden, num_labels)
            def forward(self, input_ids, attention_mask):
                out = self.electra(input_ids=input_ids, attention_mask=attention_mask)
                return self.classifier(self.dropout(out.last_hidden_state))

        self.model = BIOTagger(model_id).to(self.device)
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.torch = torch
        print(f"BIO model loaded: {model_id}, device={self.device}", file=sys.stderr)

    def extract_sentences(self, text: str) -> list[str]:
        """sliding window로 긴 text 처리. B-SENT 위치마다 sentence 시작."""
        if not text.strip():
            return []
        enc = self.tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
        tokens = enc["input_ids"]
        offsets = enc["offset_mapping"]

        # Sliding window predict
        STRIDE = self.max_len - 128
        all_preds: list[int] = [0] * len(tokens)
        all_counts: list[int] = [0] * len(tokens)  # 평균 voting

        for start in range(0, len(tokens), STRIDE):
            chunk_tokens = tokens[start:start + self.max_len - 2]
            if not chunk_tokens:
                break
            input_ids = [self.tokenizer.cls_token_id] + chunk_tokens + [self.tokenizer.sep_token_id]
            input_ids_t = self.torch.tensor(input_ids).unsqueeze(0).to(self.device)
            attn = self.torch.ones_like(input_ids_t)
            with self.torch.no_grad():
                logits = self.model(input_ids_t, attn)
            preds = logits.argmax(dim=-1)[0].cpu().tolist()[1:1 + len(chunk_tokens)]
            for i, p in enumerate(preds):
                idx = start + i
                if idx < len(all_preds):
                    all_preds[idx] = p  # overwrite (later window 우선)
                    all_counts[idx] += 1
            if start + self.max_len - 2 >= len(tokens):
                break

        # B-SENT 위치 → sentence start
        sentences: list[str] = []
        current_start: int | None = None
        for tok_i, (s, e) in enumerate(offsets):
            pred = all_preds[tok_i]
            if pred == 1:  # B-SENT
                if current_start is not None:
                    sent = text[current_start:s].strip()
                    if sent:
                        sentences.append(sent)
                current_start = s
        if current_start is not None:
            sent = text[current_start:].strip()
            if sent:
                sentences.append(sent)

        return sentences


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--ensemble", action="store_true", help="Parser ensemble + selection 사용")
    args = ap.parse_args()

    # 1. Text extraction (single parser or ensemble)
    if args.ensemble:
        text, best, scores = extract_text_ensemble(args.file)
        print(f"[ensemble] best={best}, scores: {scores}", file=sys.stderr)
        fmt = best
    else:
        text, fmt = extract_text(args.file)
    print(f"[{fmt}] extracted {len(text)} chars", file=sys.stderr)

    # 2. KoCharELECTRA BIO → sentence_list
    inf = BIOInferer(args.checkpoint)
    sentences = inf.extract_sentences(text)

    print(f"Sentences ({len(sentences)}):")
    for i, s in enumerate(sentences):
        print(f"  [{i:02d}] {s}")


if __name__ == "__main__":
    main()
