"""3단계 비교 dump — 원본 PDF text + parser 추출 word + 모델 sentence.

각 PDF의 page별로:
  1. fitz extract_text (PDF 원문)
  2. pdfplumber extract_words → dedup → merge (모델에 들어가는 text)
  3. HybridInferer.extract_sentences (모델 최종 출력)

사용:
    docker compose exec -T backend python /app/sentence_extraction/dump_3stage_comparison.py \\
        --checkpoint /app/sentence_extraction/data/hybrid_v7_crf_best.pt \\
        --out /app/sentence_extraction/data/3stage_comparison.md
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hybrid_infer import HybridInferer
from parser_ensemble import dedup_overlapping_words, merge_singleton_words


# 대표 PDF 3장 — dedup 효과 + CRF 표/본문 통합 효과 골고루
PDFS = [
    (
        "AIEP 동의서 (디자인 더블 프린팅 dedup 케이스)",
        "/app/sentence_extraction/data/heldout_20/(부평초)+인공지능+맞춤형+교수학습+플랫폼(AIEP)+개인정보동의서.pdf",
    ),
    (
        "2025-147 스마트 수학 탐험대 (HWP→PDF, 표 통합 케이스)",
        "/app/sentence_extraction/data/hwp_to_pdf/2025-147 「스마트 수학 탐험대」 안내.pdf",
    ),
    (
        "2025-144 자전거 안전 (HWP→PDF, 본문 통합 케이스)",
        "/app/sentence_extraction/data/hwp_to_pdf/2025-144 2025학년도 자전거 안전한 이용 문화 확산 및 자전거 통학 금지 안내.pdf",
    ),
]


def dump_pdf(label: str, pdf_path: Path, inferer: HybridInferer) -> str:
    import fitz
    import pdfplumber

    lines: list[str] = []
    lines.append(f"# {label}\n")
    lines.append(f"**파일**: `{pdf_path.name}`\n")

    # 1. fitz 원문
    lines.append("## 1단계 — PDF 원문 (fitz `get_text()`)\n")
    doc = fitz.open(pdf_path)
    n_pages = len(doc)
    lines.append("```")
    for pi in range(n_pages):
        lines.append(f"--- page {pi+1}/{n_pages} ---")
        lines.append(doc[pi].get_text().rstrip())
    lines.append("```\n")
    doc.close()

    # 2. parser word (raw → dedup → merge)
    lines.append("## 2단계 — 파서 추출 word (pdfplumber → dedup → merge)\n")
    with pdfplumber.open(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages):
            raw = page.extract_words(
                use_text_flow=True, keep_blank_chars=False,
                x_tolerance=3, y_tolerance=3,
            )
            deduped = dedup_overlapping_words(raw)
            merged = merge_singleton_words(deduped)
            removed_dedup = len(raw) - len(deduped)
            removed_merge = len(deduped) - len(merged)  # 음수면 길이 늘어남 (merge로 word↑)
            lines.append(
                f"**page {pi+1}**: raw {len(raw)} → dedup {len(deduped)} "
                f"(중복 {removed_dedup}개 제거) → merge {len(merged)} "
                f"(한글자 묶기로 {-removed_merge}개 합쳐짐)"
            )
            lines.append("```")
            lines.append(" ".join(w["text"] for w in merged))
            lines.append("```")
    lines.append("")

    # 3. 모델 출력
    sents = inferer.extract_sentences(pdf_path)
    lines.append(f"## 3단계 — 모델 출력 sentence ({len(sents)}개)\n")
    lines.append("```")
    for i, s in enumerate(sents):
        lines.append(f"[{i:02d}] {s}")
    lines.append("```\n")

    lines.append("---\n")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    inferer = HybridInferer(args.checkpoint)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Hybrid v7 CRF + dedup — 3단 비교 문서\n\n")
        f.write("**1단계** PDF 원문 (fitz) | **2단계** 파서 추출 word (dedup + merge 후) | **3단계** 모델 sentence 출력\n\n")
        f.write("---\n\n")
        for label, path_str in PDFS:
            path = Path(path_str)
            print(f"=== {label} ===", file=sys.stderr)
            try:
                md = dump_pdf(label, path, inferer)
                f.write(md)
                f.write("\n")
            except Exception as e:
                f.write(f"# {label}\n\nFAIL: {e}\n\n---\n\n")
                print(f"  FAIL: {e}", file=sys.stderr)
    print(f"\nDone: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
