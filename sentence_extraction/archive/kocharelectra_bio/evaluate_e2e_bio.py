"""End-to-end 평가 — Claude vs Parser+BIO+KoELECTRA.

흐름:
  A. Claude → sentence_list → KoELECTRA → todo (정답)
  B. Parser ensemble → BIO sentence_list → KoELECTRA → todo (자체화)
  A vs B의 todo recall·precision 측정

사용:
    docker run with backend mounted:
    python evaluate_e2e_bio.py \\
        --checkpoint data/kocharelectra_bio_best.pt \\
        --pdf-dir /app/data \\
        --out data/eval_bio.json \\
        --ensemble
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

# stdout utf-8 (extract_sentences module 가 import 시 또 변경하므로 미리)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# backend 모듈 활용 — Docker 환경에선 BACKEND_PATH=/app
_BACKEND = os.environ.get("BACKEND_PATH") or str(Path(__file__).resolve().parent.parent / "backend")
sys.path.insert(0, _BACKEND)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_sentences import BIOInferer, extract_text


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
    """backend extract_todos (KoELECTRA) — 윤정님 모델."""
    from app.services.extractor import extract_todos
    todos = extract_todos(cleaned_text)
    return [t.text for t in todos]


def get_bio_result(
    pdf_path: Path,
    bio_inferer: BIOInferer,
    use_ensemble: bool = True,
) -> tuple[list[str], str, str, dict[str, float]]:
    """Parser → BIO → sentence_list (+ 표는 BIO 통과 안 하고 별도 append).

    Returns (sentences, cleaned_text, best_parser_name, all_scores)
    """
    table_sents: list[str] = []
    if use_ensemble:
        from parser_ensemble import extract_text as ensemble_extract
        text, best, scores, table_sents = ensemble_extract(pdf_path)
    else:
        text, fmt = extract_text(pdf_path)
        best, scores = fmt, {fmt: 1.0}

    bio_sents = bio_inferer.extract_sentences(text)
    # 표 sentence는 BIO 통과 안 함 (이미 row 단위)
    sentences = bio_sents + table_sents
    cleaned = "\n".join(sentences)
    return sentences, cleaned, best, scores


def evaluate_pdf(
    pdf_path: Path,
    bio_inferer: BIOInferer,
    use_ensemble: bool = True,
) -> dict[str, Any]:
    """한 PDF에 대해 Claude vs BIO 비교."""
    # A. Claude (정답)
    t0 = time.time()
    try:
        claude_sents, claude_cleaned = get_claude_result(pdf_path)
        claude_todos = extract_todos_from_cleaned(claude_cleaned)
    except Exception as e:
        print(f"  Claude FAIL: {e}", file=sys.stderr)
        claude_sents, claude_todos = [], []
    t_claude = time.time() - t0

    # B. BIO (자체화)
    t0 = time.time()
    try:
        bio_sents, bio_cleaned, best, scores = get_bio_result(pdf_path, bio_inferer, use_ensemble)
        bio_todos = extract_todos_from_cleaned(bio_cleaned)
    except Exception as e:
        print(f"  BIO FAIL: {e}", file=sys.stderr)
        bio_sents, bio_todos, best, scores = [], [], "", {}
    t_bio = time.time() - t0

    # 비교 (evaluate_e2e와 동일 알고리즘 — substring 매칭)
    def norm(s: str) -> str:
        return "".join(s.split())

    claude_norm = {norm(t): t for t in claude_todos}
    bio_norm = {norm(t): t for t in bio_todos}

    matched = set()
    for ck in claude_norm:
        for bk in bio_norm:
            if ck == bk or ck in bk or bk in ck:
                matched.add(ck)
                break

    recall = len(matched) / max(len(claude_todos), 1)
    precision = len(matched) / max(len(bio_todos), 1)

    return {
        "pdf": pdf_path.name,
        "claude_sentences": len(claude_sents),
        "bio_sentences": len(bio_sents),
        "claude_todos": claude_todos,
        "bio_todos": bio_todos,
        "matched_count": len(matched),
        "recall": recall,
        "precision": precision,
        "time_claude_sec": t_claude,
        "time_bio_sec": t_bio,
        "best_parser": best,
        "parser_scores": scores,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--ensemble", action="store_true")
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 필요", file=sys.stderr)
        sys.exit(1)
    os.environ["ANTHROPIC_API_KEY"] = api_key

    bio_inferer = BIOInferer(args.checkpoint)

    EXCLUDE = ["용역", "결혼이민자", "어휘 교육", "양상 비교"]
    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    pdfs = [p for p in pdfs if not any(k in p.name for k in EXCLUDE)]
    print(f"평가 대상: {len(pdfs)} PDFs (ensemble={args.ensemble})")

    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        try:
            r = evaluate_pdf(pdf, bio_inferer, use_ensemble=args.ensemble)
            results.append(r)
            print(f"  Claude todos: {len(r['claude_todos'])}, BIO todos: {len(r['bio_todos'])}")
            print(f"  matched: {r['matched_count']}, recall: {r['recall']:.3f}, precision: {r['precision']:.3f}")
            print(f"  time: claude {r['time_claude_sec']:.1f}s, BIO {r['time_bio_sec']:.1f}s")
            print(f"  best_parser: {r['best_parser']}")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)

    if results:
        valid = [r for r in results if r["claude_todos"]]
        if valid:
            avg_recall = sum(r["recall"] for r in valid) / len(valid)
            avg_prec = sum(r["precision"] for r in valid) / len(valid)
            avg_t_claude = sum(r["time_claude_sec"] for r in valid) / len(valid)
            avg_t_bio = sum(r["time_bio_sec"] for r in valid) / len(valid)
            print("\n" + "=" * 60)
            print(f"전체 평균 (Claude 성공 {len(valid)}장 기준)")
            print(f"  recall    : {avg_recall:.3f}")
            print(f"  precision : {avg_prec:.3f}")
            print(f"  claude    : {avg_t_claude:.1f}s/PDF")
            print(f"  bio       : {avg_t_bio:.1f}s/PDF")
            if avg_t_bio > 0:
                print(f"  속도 비율 : {avg_t_claude/avg_t_bio:.1f}x faster")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
