"""End-to-end 평가 — Claude vs PointerDoc.

흐름:
1. PoC PDF 각각에 대해:
   A. Claude → sentence_list → KoELECTRA → todo (정답)
   B. pdfplumber + PNG render → PointerDoc → sentence_list → KoELECTRA → todo (자체화)
2. A vs B의 todo recall·precision 측정

사용:
    python sentence_extraction/evaluate_e2e_pointerdoc.py \\
        --checkpoint sentence_extraction/data/pointerdoc_best.pt \\
        --pdf-dir backend/data \\
        --out sentence_extraction/data/eval_pointerdoc.json
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# backend 모듈 활용 — Docker 환경에선 BACKEND_PATH=/app 환경변수로 override
_BACKEND = os.environ.get("BACKEND_PATH") or str(Path(__file__).resolve().parent.parent / "backend")
sys.path.insert(0, _BACKEND)

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from pointerdoc_infer import PointerDocInferer


def get_claude_result(pdf_path: Path) -> tuple[list[str], str]:
    """backend extract_sentences(PDF inline) → (sentences, cleaned_text)."""
    from app.services.layout_normalizer import extract_sentences
    with open(pdf_path, "rb") as f:
        raw = f.read()
    structured, status, _ = extract_sentences(text="", inline_data=(raw, "application/pdf"))
    sentences = [s.get("text", "") for s in structured.get("sentence_list", [])]
    cleaned = structured.get("cleaned_text", "")
    return sentences, cleaned


def extract_todos_from_cleaned(cleaned_text: str) -> list[str]:
    """backend extract_todos(cleaned_text) — KoELECTRA."""
    from app.services.extractor import extract_todos
    todos = extract_todos(cleaned_text)
    return [t.text for t in todos]


def evaluate_pdf(pdf_path: Path, inferer: PointerDocInferer) -> dict[str, Any]:
    """한 PDF에 대해 두 흐름 비교."""
    # A. Claude (정답)
    t0 = time.time()
    claude_sents, claude_cleaned = get_claude_result(pdf_path)
    claude_todos = extract_todos_from_cleaned(claude_cleaned)
    t_claude = time.time() - t0

    # B. PointerDoc (자체화)
    t0 = time.time()
    pointer_sents = inferer.extract_pdf(pdf_path)
    pointer_cleaned = "\n".join(pointer_sents)
    pointer_todos = extract_todos_from_cleaned(pointer_cleaned)
    t_pointer = time.time() - t0

    # Compare with substring matching (evaluate_e2e와 동일 알고리즘)
    def norm(s: str) -> str:
        return "".join(s.split())

    claude_norm = {norm(t): t for t in claude_todos}
    pointer_norm = {norm(t): t for t in pointer_todos}

    matched = set()
    for ck in claude_norm:
        for pk in pointer_norm:
            if ck == pk or ck in pk or pk in ck:
                matched.add(ck)
                break

    recall = len(matched) / max(len(claude_todos), 1)
    precision = len(matched) / max(len(pointer_todos), 1)

    return {
        "pdf": pdf_path.name,
        "claude_sentences": len(claude_sents),
        "pointer_sentences": len(pointer_sents),
        "claude_todos": claude_todos,
        "pointer_todos": pointer_todos,
        "matched_count": len(matched),
        "recall": recall,
        "precision": precision,
        "time_claude_sec": t_claude,
        "time_pointer_sec": t_pointer,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--api-key", default="", help="ANTHROPIC_API_KEY (없으면 환경변수)")
    ap.add_argument("--active-threshold", type=float, default=0.5)
    ap.add_argument("--row-threshold", type=float, default=0.5)
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 필요", file=sys.stderr)
        sys.exit(1)
    os.environ["ANTHROPIC_API_KEY"] = api_key

    inferer = PointerDocInferer(args.checkpoint)

    EXCLUDE = ["용역", "결혼이민자", "어휘 교육", "양상 비교"]
    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    pdfs = [p for p in pdfs if not any(k in p.name for k in EXCLUDE)]
    print(f"평가 대상: {len(pdfs)} PDFs")

    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        try:
            r = evaluate_pdf(pdf, inferer)
            results.append(r)
            print(f"  Claude todos: {len(r['claude_todos'])}, Pointer todos: {len(r['pointer_todos'])}")
            print(f"  matched: {r['matched_count']}, recall: {r['recall']:.3f}, precision: {r['precision']:.3f}")
            print(f"  time: claude {r['time_claude_sec']:.1f}s, pointer {r['time_pointer_sec']:.1f}s")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)

    if results:
        avg_recall = sum(r["recall"] for r in results) / len(results)
        avg_prec = sum(r["precision"] for r in results) / len(results)
        avg_t_claude = sum(r["time_claude_sec"] for r in results) / len(results)
        avg_t_pointer = sum(r["time_pointer_sec"] for r in results) / len(results)
        print("\n" + "=" * 60)
        print("전체 평균")
        print(f"  recall    : {avg_recall:.3f}")
        print(f"  precision : {avg_prec:.3f}")
        print(f"  claude    : {avg_t_claude:.1f}s/PDF")
        print(f"  pointer   : {avg_t_pointer:.1f}s/PDF")
        speedup = avg_t_claude / max(avg_t_pointer, 0.01)
        print(f"  속도 비율 : {speedup:.1f}x ({'faster' if speedup > 1 else 'slower'})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
