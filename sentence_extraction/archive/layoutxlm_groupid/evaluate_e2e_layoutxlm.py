"""End-to-end 평가 — Claude vs LayoutXLM+KoELECTRA.

흐름:
  A. Claude → sentence_list → KoELECTRA → todo (정답)
  B. LayoutXLM (자체) → sentence_list → attr별 후처리 → KoELECTRA → todo
  A vs B의 todo recall·precision 측정

사용:
    docker run with backend mounted:
    python evaluate_e2e_layoutxlm.py \\
        --checkpoint data/layoutxlm_best.pt \\
        --pdf-dir /app/data \\
        --out data/eval_layoutxlm.json
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

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

_BACKEND = os.environ.get("BACKEND_PATH") or str(Path(__file__).resolve().parent.parent / "backend")
sys.path.insert(0, _BACKEND)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from layoutxlm_infer import LayoutXLMInferer, post_process


def get_claude_result(pdf_path: Path) -> tuple[list[str], str]:
    """backend extract_sentences (Claude) → (sentences, cleaned_text)."""
    from app.services.layout_normalizer import extract_sentences
    with open(pdf_path, "rb") as f:
        raw = f.read()
    structured, status, _ = extract_sentences(text="", inline_data=(raw, "application/pdf"))
    sentences = [s.get("text", "") for s in structured.get("sentence_list", [])]
    cleaned = structured.get("cleaned_text", "")
    return sentences, cleaned


def extract_todos_from_cleaned(cleaned_text: str) -> list[str]:
    """backend extract_todos (KoELECTRA)."""
    from app.services.extractor import extract_todos
    todos = extract_todos(cleaned_text)
    return [t.text for t in todos]


def get_layoutxlm_result(
    pdf_path: Path, inferer: LayoutXLMInferer, split_attr: bool = True,
) -> tuple[list[str], str]:
    raw_sents = inferer.extract_sentences(pdf_path)
    sents = post_process(raw_sents, split_attr=split_attr)
    cleaned = "\n".join(sents)
    return sents, cleaned


def evaluate_pdf(
    pdf_path: Path, inferer: LayoutXLMInferer, split_attr: bool = True,
) -> dict[str, Any]:
    t0 = time.time()
    try:
        claude_sents, claude_cleaned = get_claude_result(pdf_path)
        claude_todos = extract_todos_from_cleaned(claude_cleaned)
    except Exception as e:
        print(f"  Claude FAIL: {e}", file=sys.stderr)
        claude_sents, claude_todos = [], []
    t_claude = time.time() - t0

    t0 = time.time()
    try:
        lx_sents, lx_cleaned = get_layoutxlm_result(pdf_path, inferer, split_attr)
        lx_todos = extract_todos_from_cleaned(lx_cleaned)
    except Exception as e:
        print(f"  LayoutXLM FAIL: {e}", file=sys.stderr)
        lx_sents, lx_todos = [], []
    t_lx = time.time() - t0

    def norm(s: str) -> str:
        return "".join(s.split())

    claude_norm = {norm(t): t for t in claude_todos}
    lx_norm = {norm(t): t for t in lx_todos}

    matched = set()
    for ck in claude_norm:
        for bk in lx_norm:
            if ck == bk or ck in bk or bk in ck:
                matched.add(ck)
                break

    recall = len(matched) / max(len(claude_todos), 1)
    precision = len(matched) / max(len(lx_todos), 1)

    return {
        "pdf": pdf_path.name,
        "claude_sentences": len(claude_sents),
        "layoutxlm_sentences": len(lx_sents),
        "claude_todos": claude_todos,
        "layoutxlm_todos": lx_todos,
        "matched_count": len(matched),
        "recall": recall,
        "precision": precision,
        "time_claude_sec": t_claude,
        "time_layoutxlm_sec": t_lx,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--no-split-attr", action="store_true", help="attr별 분리 후처리 끄기")
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 필요", file=sys.stderr)
        sys.exit(1)
    os.environ["ANTHROPIC_API_KEY"] = api_key

    inferer = LayoutXLMInferer(args.checkpoint)

    EXCLUDE = ["용역", "결혼이민자", "어휘 교육", "양상 비교"]
    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    pdfs = [p for p in pdfs if not any(k in p.name for k in EXCLUDE)]
    print(f"평가 대상: {len(pdfs)} PDFs (split_attr={not args.no_split_attr})")

    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        try:
            r = evaluate_pdf(pdf, inferer, split_attr=not args.no_split_attr)
            results.append(r)
            print(f"  Claude todos: {len(r['claude_todos'])}, LayoutXLM todos: {len(r['layoutxlm_todos'])}")
            print(f"  matched: {r['matched_count']}, recall: {r['recall']:.3f}, precision: {r['precision']:.3f}")
            print(f"  time: claude {r['time_claude_sec']:.1f}s, LayoutXLM {r['time_layoutxlm_sec']:.1f}s")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)

    if results:
        valid = [r for r in results if r["claude_todos"]]
        if valid:
            avg_recall = sum(r["recall"] for r in valid) / len(valid)
            avg_prec = sum(r["precision"] for r in valid) / len(valid)
            avg_t_claude = sum(r["time_claude_sec"] for r in valid) / len(valid)
            avg_t_lx = sum(r["time_layoutxlm_sec"] for r in valid) / len(valid)
            print("\n" + "=" * 60)
            print(f"전체 평균 (Claude 성공 {len(valid)}장 기준)")
            print(f"  recall    : {avg_recall:.3f}")
            print(f"  precision : {avg_prec:.3f}")
            print(f"  claude    : {avg_t_claude:.1f}s/PDF")
            print(f"  layoutxlm : {avg_t_lx:.1f}s/PDF")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
