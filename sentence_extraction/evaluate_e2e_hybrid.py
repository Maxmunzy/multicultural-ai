"""End-to-end 평가 — Claude vs Hybrid (LayoutXLM+KoCharELECTRA+BIO).

흐름:
  A. Claude → cleaned_text → 윤정님 KoELECTRA → todo (정답)
  B. Hybrid → sentence_list → "\n".join → 윤정님 KoELECTRA → todo (자체화)
  A vs B의 todo recall·precision 측정

사용:
    docker run with backend mounted:
    python evaluate_e2e_hybrid.py \\
        --checkpoint data/hybrid_best.pt \\
        --pdf-dir /app/data \\
        --out data/eval_hybrid.json
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

from hybrid_infer import HybridInferer


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
    """backend extract_todos (윤정님 KoELECTRA)."""
    from app.services.extractor import extract_todos
    todos = extract_todos(cleaned_text)
    return [t.text for t in todos]


def get_hybrid_result(
    pdf_path: Path, inferer: HybridInferer, use_table_rule: bool = False,
) -> tuple[list[str], str, list[str], list[str]]:
    """Hybrid BIO 본문 + (옵션) 표 룰 결합. Returns (전체, cleaned, bio, table)."""
    bio_sents = inferer.extract_sentences(pdf_path)
    table_sents: list[str] = []
    if use_table_rule:
        try:
            from parser_ensemble import extract_pdf_tables
            table_sents = extract_pdf_tables(pdf_path)
        except Exception as e:
            print(f"  table rule FAIL: {e}", file=sys.stderr)
    all_sents = bio_sents + table_sents
    # cleaned_text(=윤정님 todo input)는 본문 sentence만 — 표 sentence는 info_card용
    # backend pipeline과 동일: cards(윤정 todo) vs info_cards(sentence_list) 분리
    cleaned = "\n".join(bio_sents)
    return all_sents, cleaned, bio_sents, table_sents


def evaluate_pdf(
    pdf_path: Path,
    inferer: HybridInferer,
    claude_cache: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    if claude_cache is not None and pdf_path.name in claude_cache:
        claude_todos = claude_cache[pdf_path.name]
        claude_sents = []  # cached일 땐 sentences 정보 없음
        t_claude = 0.0
    else:
        try:
            claude_sents, claude_cleaned = get_claude_result(pdf_path)
            claude_todos = extract_todos_from_cleaned(claude_cleaned)
        except Exception as e:
            print(f"  Claude FAIL: {e}", file=sys.stderr)
            claude_sents, claude_todos = [], []
        t_claude = time.time() - t0

    t0 = time.time()
    try:
        hy_sents, hy_cleaned, bio_only, table_only = get_hybrid_result(pdf_path, inferer, use_table_rule=False)
        hy_todos = extract_todos_from_cleaned(hy_cleaned)
    except Exception as e:
        print(f"  Hybrid FAIL: {e}", file=sys.stderr)
        hy_sents, hy_todos, bio_only, table_only = [], [], [], []
    t_hy = time.time() - t0

    def norm(s: str) -> str:
        return "".join(s.split())

    claude_norm = {norm(t): t for t in claude_todos}
    hy_norm = {norm(t): t for t in hy_todos}

    matched = set()
    for ck in claude_norm:
        for bk in hy_norm:
            if ck == bk or ck in bk or bk in ck:
                matched.add(ck)
                break

    recall = len(matched) / max(len(claude_todos), 1)
    precision = len(matched) / max(len(hy_todos), 1)

    return {
        "pdf": pdf_path.name,
        "claude_sentences": len(claude_sents),
        "hybrid_sentences": len(hy_sents),
        "claude_todos": claude_todos,
        "hybrid_todos": hy_todos,
        "matched_count": len(matched),
        "recall": recall,
        "precision": precision,
        "time_claude_sec": t_claude,
        "time_hybrid_sec": t_hy,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--api-key", default="")
    ap.add_argument(
        "--claude-cache", type=Path, default=None,
        help="이전 평가 결과 json (claude_todos 필드 활용, Claude API 호출 skip)",
    )
    ap.add_argument(
        "--use-table-rule", action="store_true",
        help="(deprecated) v5 _table_to_sentences 룰 결합 — 사용자 vision 위반. 기본 False.",
    )
    args = ap.parse_args()

    # Claude cache 로드 — pdf 이름 → claude_todos
    claude_cache: dict[str, list[str]] | None = None
    if args.claude_cache and args.claude_cache.exists():
        with open(args.claude_cache, encoding="utf-8") as f:
            cache_data = json.load(f)
        claude_cache = {
            r["pdf"]: r.get("claude_todos", [])
            for r in cache_data
            if "pdf" in r
        }
        print(f"Claude cache loaded: {len(claude_cache)} PDFs", file=sys.stderr)

    if claude_cache is None:
        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY 필요 (또는 --claude-cache 사용)", file=sys.stderr)
            sys.exit(1)
        os.environ["ANTHROPIC_API_KEY"] = api_key

    inferer = HybridInferer(args.checkpoint)

    EXCLUDE = ["용역", "결혼이민자", "어휘 교육", "양상 비교", "000002331245"]
    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    pdfs = [p for p in pdfs if not any(k in p.name for k in EXCLUDE)]
    print(f"평가 대상: {len(pdfs)} PDFs")

    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        try:
            r = evaluate_pdf(pdf, inferer, claude_cache=claude_cache)
            results.append(r)
            print(f"  Claude todos: {len(r['claude_todos'])}, Hybrid todos: {len(r['hybrid_todos'])}")
            print(f"  matched: {r['matched_count']}, recall: {r['recall']:.3f}, precision: {r['precision']:.3f}")
            print(f"  time: claude {r['time_claude_sec']:.1f}s, hybrid {r['time_hybrid_sec']:.1f}s")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)

    if results:
        valid = [r for r in results if r["claude_todos"]]
        if valid:
            avg_recall = sum(r["recall"] for r in valid) / len(valid)
            avg_prec = sum(r["precision"] for r in valid) / len(valid)
            avg_t_claude = sum(r["time_claude_sec"] for r in valid) / len(valid)
            avg_t_hy = sum(r["time_hybrid_sec"] for r in valid) / len(valid)
            print("\n" + "=" * 60)
            print(f"전체 평균 (Claude 성공 {len(valid)}장 기준)")
            print(f"  recall    : {avg_recall:.3f}")
            print(f"  precision : {avg_prec:.3f}")
            print(f"  claude    : {avg_t_claude:.1f}s/PDF")
            print(f"  hybrid    : {avg_t_hy:.1f}s/PDF")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
