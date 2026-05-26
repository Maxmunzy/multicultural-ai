"""Heldout 20장에 대한 Hybrid sentence_list 정성 평가 dump.

Claude cache 없으니 정량 X. Hybrid 출력만 markdown으로 정리해서 형식별 처리 능력 확인.

사용:
    docker exec project-backend-1 python /app/sentence_extraction/dump_hybrid_heldout.py \\
        --checkpoint /app/sentence_extraction/data/hybrid_best.pt \\
        --pdf-dir /app/sentence_extraction/data/heldout_20 \\
        --out /app/sentence_extraction/data/heldout_qualitative.md
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


def dump_pdf(pdf_path: Path, inferer: HybridInferer) -> str:
    """한 PDF에 대해 Hybrid BIO 단독 dump → markdown. 룰 결합 없음."""
    lines: list[str] = [f"## {pdf_path.name}\n"]
    try:
        bio_sents = inferer.extract_sentences(pdf_path)
    except Exception as e:
        lines.append(f"❌ Hybrid FAIL: {e}\n")
        return "\n".join(lines)

    lines.append(f"- BIO sentences: **{len(bio_sents)}** (룰 미사용)\n")

    lines.append("### Hybrid BIO 단독 출력")
    lines.append("```")
    for i, s in enumerate(bio_sents):
        s_display = s.replace("\n", " ⏎ ")
        lines.append(f"[{i:02d}] {s_display}")
    lines.append("```")
    lines.append("\n---\n")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    inferer = HybridInferer(args.checkpoint)

    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    print(f"Heldout dump: {len(pdfs)} PDFs", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Heldout 20장 Hybrid 정성 평가 dump\n\n")
        f.write("학습 안 본 PDF 20장에 대한 Hybrid 모델 출력. Claude 비교 없이 sentence_list 형식 + 자연스러움 정성 검토용.\n\n")
        f.write("---\n\n")
        for i, pdf in enumerate(pdfs, 1):
            print(f"  [{i}/{len(pdfs)}] {pdf.name}", file=sys.stderr)
            md = dump_pdf(pdf, inferer)
            f.write(md)
            f.write("\n")
    print(f"\nDone: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
