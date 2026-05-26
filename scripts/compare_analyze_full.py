"""실제 /analyze pipeline 그대로 호출 — Claude vs Hybrid 비교.

backend/app/routers/notice.py:909 analyze_notice 본문과 동일한 단계 수행:
  [2.5b] extract_sentences  (Hybrid → ok:hybrid / Claude → _call_claude)
  [3]    extract_todos       (윤정 KoELECTRA)
  [3']   extract_title       (윤정 휴리스틱)
  [2]    extract_summary_regex_slots
  [4]    classify_category   (경이 KcELECTRA, _build_item 안에서)
  [6']   build_cards         (윤정 todo + 경이 분류 + 번역 → cards)
  [6.5]  build_info_cards    (sentence_list → info_cards + 번역)

판정 축: 1) 누락, 2) 변형, 3) 자연스러움 (cards/info_cards 단위).

사용:
  docker compose exec -T backend python /app/scripts/compare_analyze_full.py \\
      --pdf "/app/data/2025. 겨울방학 도서관 이용 및 독서캠프 신청 안내.pdf" \\
      --lang vi \\
      --out /app/sentence_extraction/data/full_pipeline_compare.md
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/app")

from app.services.layout_normalizer import extract_sentences, _call_claude  # noqa: E402
from app.services.extractor import extract_todos, extract_title  # noqa: E402
from app.services.parser import preprocess_notice_text  # noqa: E402
from app.services.slot_extractor import extract_summary_regex_slots  # noqa: E402
from app.services.card_builder import build_cards  # noqa: E402
from app.services.info_card_builder import (  # noqa: E402
    build_info_cards_from_sentence_document,
    raw_text_to_sentence_list,
)


def _structured_to_sentence_doc(structured: dict | None, fallback_text: str):
    if structured and structured.get("sentence_list"):
        from app.models.schemas import SentenceListDocument, SentenceListItem
        try:
            items = [
                SentenceListItem(
                    sentence_id=s.get("sentence_id", f"s{i:04d}"),
                    text=s.get("text", ""),
                    role_hint=s.get("role_hint", ""),
                    source_order=s.get("source_order", i),
                    is_action_candidate=s.get("is_action_candidate", False),
                )
                for i, s in enumerate(structured["sentence_list"])
                if s.get("text")
            ]
            return SentenceListDocument(document_title=structured.get("document_title", ""), items=items)
        except Exception as e:
            print(f"  sentence_doc build failed: {e}, falling back to raw_text", file=sys.stderr)
    return raw_text_to_sentence_list(fallback_text)


def run_pipeline(label: str, structured: dict, raw_text: str, target_lang: str) -> dict:
    """structured/raw_text 받아서 todos/cards/info_cards 만들고 dict 반환."""
    print(f"  [{label}] todos 추출...", file=sys.stderr)
    cleaned = (structured.get("cleaned_text") or "").strip() or raw_text
    cleaned = preprocess_notice_text(cleaned)

    sentences = [s.strip() for s in cleaned.split("\n") if s.strip()]
    todos: list = []
    for sent in sentences:
        try:
            todos.extend(extract_todos(sent))
        except Exception as e:
            print(f"    extract_todos fail: {e}", file=sys.stderr)

    title_ko = (structured.get("document_title") or "").strip() or (extract_title(raw_text) or "")
    print(f"  [{label}] title: {title_ko!r}", file=sys.stderr)

    regex_slots = extract_summary_regex_slots(cleaned, target_lang)
    print(f"  [{label}] cards 빌드 (번역 포함)...", file=sys.stderr)
    top_todos = sorted(todos, key=lambda t: -t.confidence)[:30]
    cards = build_cards(top_todos, regex_slots, target_lang)[:30]

    print(f"  [{label}] info_cards 빌드...", file=sys.stderr)
    sent_doc = _structured_to_sentence_doc(structured, cleaned)
    info_cards = build_info_cards_from_sentence_document(sent_doc, target_lang)[:30]

    return {
        "title_ko": title_ko,
        "todos_count": len(todos),
        "todos_sample": [
            {"text": (t.text or "")[:120], "action": t.action_hint, "conf": round(t.confidence, 3)}
            for t in top_todos[:10]
        ],
        "cards_count": len(cards),
        "cards": [
            {
                "header_ko": c.header_ko,
                "header_translated": c.header_translated,
                "value_ko": c.value_ko,
                "value_translated": c.value_translated,
                "category": getattr(c, "category", ""),
            }
            for c in cards
        ],
        "info_cards_count": len(info_cards),
        "info_cards": [
            {
                "header_ko": ic.header_ko,
                "header_translated": ic.header_translated,
                "value_ko": ic.value_ko,
                "value_translated": ic.value_translated,
            }
            for ic in info_cards
        ],
    }


def render_md(pdf: Path, lang: str, hy: dict, cl: dict, hy_t: float, cl_t: float, out: Path) -> None:
    L: list[str] = []
    L.append(f"# Full Pipeline: Claude vs Hybrid — `{pdf.name}`\n")
    L.append(f"target_lang: **{lang}**\n")
    L.append(f"| | Claude | Hybrid |")
    L.append(f"|---|---|---|")
    L.append(f"| 총 시간 | {cl_t:.1f}s | {hy_t:.1f}s |")
    L.append(f"| 제목 | `{cl['title_ko']}` | `{hy['title_ko']}` |")
    L.append(f"| todo 추출 수 | {cl['todos_count']} | {hy['todos_count']} |")
    L.append(f"| cards (todo 분류 + 번역) | {cl['cards_count']} | {hy['cards_count']} |")
    L.append(f"| info_cards (sentence 정보) | {cl['info_cards_count']} | {hy['info_cards_count']} |")
    L.append("")

    for label, src in [("Claude", cl), ("Hybrid", hy)]:
        L.append(f"## {label} — todos sample (top 10)")
        L.append("```json")
        L.append(json.dumps(src["todos_sample"], ensure_ascii=False, indent=2))
        L.append("```")
        L.append(f"\n## {label} — cards (윤정 todo + 경이 분류 + 번역)")
        for i, c in enumerate(src["cards"]):
            L.append(f"### [{i:02d}] {c.get('category','-')} | {c['header_ko']} ({c.get('header_translated','')})")
            L.append(f"- ko : `{c['value_ko']}`")
            L.append(f"- {lang}: `{c['value_translated']}`")
        L.append(f"\n## {label} — info_cards (sentence 단위)")
        for i, ic in enumerate(src["info_cards"]):
            L.append(f"### [{i:02d}] {ic['header_ko']} ({ic.get('header_translated','')})")
            L.append(f"- ko : `{ic['value_ko']}`")
            L.append(f"- {lang}: `{ic['value_translated']}`")
        L.append("\n---\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"\nDone: {out}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--lang", default="vi")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    raw = args.pdf.read_bytes()

    print("Hybrid extract_sentences...", file=sys.stderr)
    t0 = time.time()
    hy_struct, hy_status, _ = extract_sentences(inline_data=(raw, "application/pdf"))
    print(f"  status={hy_status}, sentences={len(hy_struct.get('sentence_list',[]))}", file=sys.stderr)

    print("Claude _call_claude...", file=sys.stderr)
    cl_struct, cl_status, _ = _call_claude(text="", inline_data=(raw, "application/pdf"))
    print(f"  status={cl_status}, cleaned_text_len={len(cl_struct.get('cleaned_text',''))}", file=sys.stderr)

    raw_text = ""  # fallback (not used if structured has cleaned_text)
    print("Hybrid pipeline...", file=sys.stderr)
    t1 = time.time()
    hy = run_pipeline("Hybrid", hy_struct, raw_text, args.lang)
    hy_t = time.time() - t1

    print("Claude pipeline...", file=sys.stderr)
    t1 = time.time()
    cl = run_pipeline("Claude", cl_struct, raw_text, args.lang)
    cl_t = time.time() - t1

    render_md(args.pdf, args.lang, hy, cl, hy_t, cl_t, args.out)


if __name__ == "__main__":
    main()
