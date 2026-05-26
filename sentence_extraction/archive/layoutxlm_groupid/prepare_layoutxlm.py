"""LayoutXLM 학습 데이터 자동 라벨링 (Claude sentence_list + 표 row ↔ pdfplumber word 매칭).

입력: kd_train_pointerdoc_pymupdf.jsonl + PDFs
출력: layoutxlm_train.jsonl (page 단위 record)

알고리즘:
1. pdfplumber로 word + bbox 추출 (page별, 좌표 0~1000 정규화)
2. Claude sentence_list 순회 (cursor 기반 norm-matching) — 본문 영역
3. 표 row sentence (pdfplumber find_tables → row별 cell join) — Phase 1 unlabeled word에만 라벨링
4. 매칭된 word 범위에 group_id (sentence index) 라벨

→ 표 영역도 학습 신호 받게 됨 (이전엔 표 word들이 모두 unlabeled → BIO에서 O로 학습돼 표 sentence 못 잡았던 문제 해결)

LayoutXLM input은 max 512 token이라 page 단위로 record 분리.
이미지는 학습 시 동적 렌더링 (저장 안 함).

사용:
    python sentence_extraction/prepare_layoutxlm.py \\
        --kd sentence_extraction/data/kd_train_pointerdoc_pymupdf.jsonl \\
        --pdf-dir sentence_extraction/data/all_pdfs \\
        --out sentence_extraction/data/layoutxlm_train.jsonl
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


def extract_words_with_bbox(pdf_path: Path) -> list[dict]:
    """모든 page의 word + bbox 추출 (좌표 0~1000 정규화).

    자간 큰 헤더로 인한 한글자 word 단편화를 merge_singleton_words로 해결.
    """
    import pdfplumber
    from parser_ensemble import merge_singleton_words

    words: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            W, H = page.width, page.height
            if W <= 0 or H <= 0:
                continue
            raw_words = page.extract_words(
                use_text_flow=True, keep_blank_chars=False,
                x_tolerance=3, y_tolerance=3,
            )
            # 한글자 word 합치기 (자간 큰 헤더 단편화 해결)
            raw_words = merge_singleton_words(raw_words)

            for w in raw_words:
                x0, y0, x1, y1 = w["x0"], w["top"], w["x1"], w["bottom"]
                words.append({
                    "text": w["text"],
                    "page": page_idx,
                    "bbox": [
                        max(0, min(1000, int(x0 / W * 1000))),
                        max(0, min(1000, int(y0 / H * 1000))),
                        max(0, min(1000, int(x1 / W * 1000))),
                        max(0, min(1000, int(y1 / H * 1000))),
                    ],
                })
    return words


def _norm_for_match(s: str) -> str:
    """매칭용 정규화 — 한글/영문/숫자만 (공백, 특수문자, 구두점, 화살표 등 제거).

    Claude가 추가하는 prefix (`:`, `,`, `→`) 와 PDF text 사이 불일치 해결.
    """
    return "".join(c for c in s if c.isalnum())


def build_norm_map(words: list[dict]) -> tuple[str, list[int]]:
    """word들의 text를 합쳐 norm-text + 각 norm char → word index 매핑.

    한글/영문/숫자만 보존 (특수문자, 공백 모두 제거) — _norm_for_match와 동일 기준.
    """
    norm_chars: list[str] = []
    norm_to_word: list[int] = []
    for wi, w in enumerate(words):
        for c in w["text"]:
            if c.isalnum():
                norm_chars.append(c)
                norm_to_word.append(wi)
    return "".join(norm_chars), norm_to_word


def extract_table_row_sentences(pdf_path: Path) -> list[str]:
    """v6 — L (row join) + J (entity oneline) 조합.

    v5 entity-block (짧은 sentence 다수) 학습 실패 → 짧은 sentence 문제 해결:
    - L: PDF reading order 그대로 row 단위 join (긴 sentence, 매칭률 ↑)
    - J: entity 단위 한 줄 (긴 sentence, entity 묶음 학습 신호)
    둘 다 긴 sentence → 본문 spillover X.
    """
    from parser_ensemble import extract_pdf_table_v6

    try:
        return extract_pdf_table_v6(pdf_path)
    except Exception:
        return []


def label_words(
    words: list[dict],
    sentences: list[dict | str],
    table_sentences: list[str] | None = None,
) -> tuple[list[int], int, int, int]:
    """Claude sentence_list + 표 row sentence로 word들에 group_id 라벨. -1 = unlabeled."""
    norm_text, norm_to_word = build_norm_map(words)
    labels = [-1] * len(words)

    # Phase 1: Claude sentence_list (cursor 기반, 본문 위주)
    cursor = 0
    matched = 0
    for sid, s in enumerate(sentences):
        s_text = s.get("text", "").strip() if isinstance(s, dict) else str(s).strip()
        if not s_text:
            continue
        # Claude가 표 cells 합쳐 만든 통합 sentence ("[프로그램: ... / 내용: ...]") 제외
        # — 우리 v5 표 라벨링이 이미 entity-block으로 처리하므로 중복
        if s_text.startswith("[") and "]" in s_text and "/" in s_text:
            continue
        s_norm = _norm_for_match(s_text)
        if not s_norm:
            continue

        found = norm_text.find(s_norm, cursor)
        if found < 0:
            found = norm_text.find(s_norm)
        if found < 0:
            continue

        end_norm = found + len(s_norm) - 1
        if end_norm >= len(norm_to_word):
            continue

        start_word = norm_to_word[found]
        end_word = norm_to_word[end_norm]

        for wi in range(start_word, end_word + 1):
            labels[wi] = sid

        cursor = end_norm + 1
        matched += 1

    # Phase 2: 표 sentence — "attr: value" 형식이면 value만 매칭 (PDF text와 일치성 ↑)
    matched_table = 0
    if table_sentences:
        next_sid = len(sentences)
        for ts in table_sentences:
            # "내용: 미션 도장깨기" → value "미션 도장깨기"만 매칭
            # entity name (콜론 없는 sentence)은 그대로
            if ":" in ts:
                _, value = ts.split(":", 1)
                target = value.strip()
            else:
                target = ts.strip()

            s_norm = _norm_for_match(target)
            if len(s_norm) < 4:
                continue
            found = norm_text.find(s_norm)
            if found < 0:
                continue
            end_norm = found + len(s_norm) - 1
            if end_norm >= len(norm_to_word):
                continue
            start_word = norm_to_word[found]
            end_word = norm_to_word[end_norm]
            if not all(labels[wi] < 0 for wi in range(start_word, end_word + 1)):
                continue
            new_sid = next_sid + matched_table
            for wi in range(start_word, end_word + 1):
                labels[wi] = new_sid
            matched_table += 1

    return labels, matched, matched_table, len(sentences)


def split_per_page(words: list[dict], labels: list[int]) -> list[dict]:
    """page별로 record 분리 — LayoutXLM 512 token 제한 대응."""
    by_page: dict[int, list[tuple[dict, int]]] = {}
    for w, lab in zip(words, labels):
        by_page.setdefault(w["page"], []).append((w, lab))

    records: list[dict] = []
    for page_idx in sorted(by_page.keys()):
        page_words = by_page[page_idx]
        records.append({
            "page": page_idx,
            "words": [w["text"] for w, _ in page_words],
            "bboxes": [w["bbox"] for w, _ in page_words],
            "labels": [lab for _, lab in page_words],
        })
    return records


def process_record(rec: dict[str, Any], pdf_dir: Path) -> list[dict[str, Any]]:
    pdf_name = rec.get("pdf", "")
    sentences = rec.get("sentences", [])
    if not pdf_name or not sentences:
        return []

    pdf_path = pdf_dir / pdf_name
    if not pdf_path.exists():
        return []

    try:
        words = extract_words_with_bbox(pdf_path)
    except Exception as e:
        print(f"  parser FAIL {pdf_name}: {e}", file=sys.stderr)
        return []

    if not words:
        return []

    try:
        table_sents = extract_table_row_sentences(pdf_path)
    except Exception:
        table_sents = []

    labels, matched, matched_table, total = label_words(words, sentences, table_sents)
    if matched == 0 and matched_table == 0:
        return []

    page_records = split_per_page(words, labels)
    n_words = len(words)
    match_rate = matched / max(total, 1)
    coverage = sum(1 for lab in labels if lab >= 0) / max(n_words, 1)

    out: list[dict[str, Any]] = []
    for pr in page_records:
        if not pr["words"]:
            continue
        out.append({
            "pdf": pdf_name,
            "page": pr["page"],
            "words": pr["words"],
            "bboxes": pr["bboxes"],
            "labels": pr["labels"],
            "n_words": len(pr["words"]),
            "n_sentences_total": total,
            "n_matched": matched,
            "n_matched_table": matched_table,
            "n_table_sents": len(table_sents),
            "match_rate": match_rate,
            "word_coverage": coverage,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kd", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    stats = {"total": 0, "ok_pdf": 0, "skip_match": 0, "page_records": 0}
    matched_sum = 0
    matched_table_sum = 0
    table_sents_sum = 0
    total_sents_sum = 0
    word_count = 0

    with open(args.kd, encoding="utf-8") as f_in, open(args.out, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            stats["total"] += 1
            if args.limit and stats["total"] > args.limit:
                break
            try:
                rec = json.loads(line)
            except Exception:
                continue
            samples = process_record(rec, args.pdf_dir)
            if not samples:
                stats["skip_match"] += 1
                continue
            stats["ok_pdf"] += 1
            stats["page_records"] += len(samples)
            first = samples[0]
            matched_sum += first["n_matched"]
            matched_table_sum += first.get("n_matched_table", 0)
            table_sents_sum += first.get("n_table_sents", 0)
            total_sents_sum += first["n_sentences_total"]
            for s in samples:
                word_count += s["n_words"]
                f_out.write(json.dumps(s, ensure_ascii=False) + "\n")
            if stats["ok_pdf"] % 100 == 0:
                print(f"  progress: {stats['ok_pdf']} PDFs / {stats['total']} total ({stats['page_records']} page records)", file=sys.stderr)

    print(f"Total PDFs:          {stats['total']}")
    print(f"OK PDFs:             {stats['ok_pdf']}")
    print(f"Page records:        {stats['page_records']}")
    print(f"Skipped (matching):  {stats['skip_match']}")
    print(f"Total words:         {word_count:,}")
    print(f"Claude sentence:     {matched_sum} / {total_sents_sum} ({100*matched_sum/max(total_sents_sum,1):.1f}%)")
    print(f"Table row sentence:  {matched_table_sum} / {table_sents_sum} ({100*matched_table_sum/max(table_sents_sum,1):.1f}%)")
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()
