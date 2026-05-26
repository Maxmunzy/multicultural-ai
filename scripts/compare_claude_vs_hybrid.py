"""Claude API vs Hybrid 교차 검증 — sentence 추출 + 8개 언어 번역 옆에 두고 비교.

판정 축:
  1. 내용 누락 (원문 정보 빠뜨림)
  2. 변형 (원문에 없는 표현 — Claude hallucinate / Hybrid는 변형 0 보장)
  3. 자연스러움 (단편화 / over-merge / 사람 읽기 흐름)

사용:
  docker compose exec -T backend python /app/scripts/compare_claude_vs_hybrid.py \\
      --pdf "/app/data/2025. 겨울방학 도서관 이용 및 독서캠프 신청 안내.pdf" \\
      --out /app/sentence_extraction/data/claude_vs_hybrid.md
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/app")

from app.services.layout_normalizer import (  # noqa: E402
    extract_sentences,
    _call_claude,
)
from app.services.translator import LANG_TO_NLLB, translate_short_sentence_batch  # noqa: E402

LANG_LABEL = {
    "vi": "베트남어",
    "en": "영어",
    "zh": "중국어",
    "ja": "일본어",
    "th": "태국어",
    "ru": "러시아어",
    "ms": "말레이어",
    "mn": "몽골어",
}


def extract_original_pdf_text(pdf_path: Path) -> str:
    import fitz
    doc = fitz.open(pdf_path)
    chunks = []
    for pi in range(len(doc)):
        chunks.append(f"--- page {pi+1}/{len(doc)} ---")
        chunks.append(doc[pi].get_text().rstrip())
    doc.close()
    return "\n".join(chunks)


def get_sentences_via_hybrid(raw: bytes) -> tuple[list[str], float, str]:
    t0 = time.time()
    result, status, _ = extract_sentences(inline_data=(raw, "application/pdf"))
    sents = [s["text"] for s in result.get("sentence_list", [])]
    return sents, time.time() - t0, status


def get_sentences_via_claude(raw: bytes) -> tuple[list[str], float, str]:
    t0 = time.time()
    result, status, _ = _call_claude(text="", inline_data=(raw, "application/pdf"))
    cleaned = result.get("cleaned_text", "")
    sent_list = result.get("sentence_list", [])
    if sent_list:
        sents = [s.get("text", "") for s in sent_list if s.get("text")]
    else:
        sents = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    return sents, time.time() - t0, status


def translate_all(sents: list[str], langs: list[str]) -> dict[str, list[str]]:
    out = {}
    for lang in langs:
        try:
            out[lang] = translate_short_sentence_batch(sents, lang)
        except Exception as e:
            print(f"  translate {lang} FAIL: {e}", file=sys.stderr)
            out[lang] = [f"[FAIL: {e}]" for _ in sents]
    return out


def render(pdf_path: Path, out_path: Path) -> None:
    print(f"=== {pdf_path.name} ===", file=sys.stderr)
    raw = pdf_path.read_bytes()
    print("  원문 추출...", file=sys.stderr)
    original = extract_original_pdf_text(pdf_path)
    print("  Hybrid 추론...", file=sys.stderr)
    hy_sents, hy_t, hy_status = get_sentences_via_hybrid(raw)
    print(f"    {len(hy_sents)} sentences in {hy_t:.1f}s ({hy_status})", file=sys.stderr)
    print("  Claude API 호출...", file=sys.stderr)
    cl_sents, cl_t, cl_status = get_sentences_via_claude(raw)
    print(f"    {len(cl_sents)} sentences in {cl_t:.1f}s ({cl_status})", file=sys.stderr)

    langs = list(LANG_TO_NLLB.keys())
    print(f"  Hybrid 번역 ({len(langs)} 언어)...", file=sys.stderr)
    hy_tr = translate_all(hy_sents, langs)
    print(f"  Claude 번역 ({len(langs)} 언어)...", file=sys.stderr)
    cl_tr = translate_all(cl_sents, langs)

    L: list[str] = []
    L.append(f"# Claude API vs Hybrid — `{pdf_path.name}`\n")
    L.append("**판정 축**: 1) 내용 누락 X, 2) 원문 변형 X, 3) 자연스러움\n")

    L.append("## 1. PDF 원문 (fitz `get_text()`)\n")
    L.append("```")
    L.append(original)
    L.append("```\n")

    L.append(f"## 2. Sentence 추출 결과\n")
    L.append(f"| | Claude API | Hybrid v7+dedup |")
    L.append(f"|---|---|---|")
    L.append(f"| 추출 sentence 수 | {len(cl_sents)} | {len(hy_sents)} |")
    L.append(f"| 추출 시간 (sec) | {cl_t:.2f} | {hy_t:.2f} |")
    L.append(f"| 상태 | `{cl_status}` | `{hy_status}` |")
    L.append("")

    L.append("### Claude API sentence")
    L.append("```")
    for i, s in enumerate(cl_sents):
        L.append(f"[{i:02d}] {s}")
    L.append("```\n")

    L.append("### Hybrid sentence")
    L.append("```")
    for i, s in enumerate(hy_sents):
        L.append(f"[{i:02d}] {s}")
    L.append("```\n")

    L.append("## 3. 8개 언어 번역 비교\n")
    for lang in langs:
        L.append(f"### {LANG_LABEL.get(lang, lang)} ({lang} → {LANG_TO_NLLB[lang]})\n")
        L.append("**Claude API 번역**")
        L.append("```")
        for i, t in enumerate(cl_tr[lang]):
            L.append(f"[{i:02d}] {t}")
        L.append("```\n")
        L.append("**Hybrid 번역**")
        L.append("```")
        for i, t in enumerate(hy_tr[lang]):
            L.append(f"[{i:02d}] {t}")
        L.append("```\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"\nDone: {out_path}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    render(args.pdf, args.out)


if __name__ == "__main__":
    main()
