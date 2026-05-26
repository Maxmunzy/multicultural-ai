"""PointerDoc 학습 텐서 변환 — kd_train_pointerdoc.jsonl + page_images → train.pt

각 학습 sample = 한 PDF (모든 페이지 합쳐서). 페이지는 vertical concat 또는 multi-page batching.
여기서는 단순화 위해 **PDF 첫 페이지만** 사용 (1-2장 가정통신문 가정).

출력 (각 sample):
- image: PIL Image (학습 시 DINOv2 processor로 변환)
- bboxes: (N_rows, 4) — normalized [0, 1]
- row_pages: (N_rows,) — page index (0-base)
- sentence_row_ids: list of list[int] — 각 sentence의 row indices
- N_rows, N_sentences

사용:
    python sentence_extraction/prepare_pointerdoc.py \\
        --jsonl sentence_extraction/data/kd_train_pointerdoc.jsonl \\
        --image-dir sentence_extraction/data/page_images \\
        --out sentence_extraction/data/pointerdoc_train.jsonl \\
        --max-rows 128 --max-sentences 32
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


_NON_WORD = re.compile(r"[^\w가-힣]")


def normalize_for_match(s: str) -> str:
    """매칭용 정규화 — 띄어쓰기·구두점·기호 제거. 한글·영숫자만 유지."""
    return _NON_WORD.sub("", s)


def sequential_alignment(
    rows_text: list[str],
    sentences: list[dict[str, Any]],
    jaccard_threshold: float = 0.6,
    sentence_coverage_min: float = 0.7,
    row_in_sent_min: float = 0.5,
) -> int:
    """Bidirectional Jaccard + Minimal contiguous range matching.

    개선점:
    - **Bidirectional**: sentence chars X% in row range AND row chars Y% in sentence
      (sentence-side coverage 보장 + row over-extension 막음)
    - **Minimal range**: sentence chars의 sentence_coverage_min 충족하는 가장 작은 range
      (over-grouping 막음)
    - **Cursor flex**: cursor는 매칭된 range의 마지막 row + 1로 이동 (monotonic)
      매칭 실패 sentence면 cursor 유지 (다른 후보 시도 안 함)

    Args:
        jaccard_threshold: |s & r| / |s | r| 임계값 (최종 match 여부)
        sentence_coverage_min: sentence chars의 X% 이상이 row range chars에 있어야
        row_in_sent_min: row range chars의 X% 이상이 sentence chars에 있어야

    Returns:
        매칭된 sentence 수
    """
    row_chars: list[set[str]] = [set(normalize_for_match(r)) for r in rows_text]
    sent_chars: list[set[str]] = [set(normalize_for_match(s.get("text", ""))) for s in sentences]

    for s in sentences:
        s["row_ids"] = []

    n = len(rows_text)
    cursor = 0
    matched = 0

    for si, s_set in enumerate(sent_chars):
        if not s_set or cursor >= n:
            continue

        best_range: tuple[int, int] | None = None
        best_jaccard = 0.0
        # 가장 작은 range로 sentence를 충족하는 거 선호 — over-group 막음
        best_size = float("inf")

        for start in range(cursor, n):
            acc_chars: set[str] = set()
            for end in range(start, n):
                acc_chars |= row_chars[end]
                size = end - start + 1

                s_cov = len(s_set & acc_chars) / max(len(s_set), 1)
                r_cov = len(s_set & acc_chars) / max(len(acc_chars), 1)
                jaccard = len(s_set & acc_chars) / max(len(s_set | acc_chars), 1)

                # 양방향 임계값 둘 다 만족해야 후보
                if s_cov >= sentence_coverage_min and r_cov >= row_in_sent_min:
                    # 더 작은 range + 더 높은 jaccard 선호
                    if jaccard > best_jaccard or (jaccard == best_jaccard and size < best_size):
                        best_jaccard = jaccard
                        best_range = (start, end)
                        best_size = size

                # acc_chars가 sentence 충족 못해도 계속 확장하면 row over-add
                # → s_cov가 0.95+ 도달하면 그 range로 stop (extension 안 함)
                if s_cov >= 0.98 and r_cov >= row_in_sent_min:
                    break
            # 충분히 좋으면 outer loop도 끝
            if best_jaccard >= 0.95:
                break

        if best_range is not None and best_jaccard >= jaccard_threshold:
            sentences[si]["row_ids"] = list(range(best_range[0], best_range[1] + 1))
            cursor = best_range[1] + 1
            matched += 1

    return matched


def fuzzy_enhance_row_ids(
    rows_text: list[str],
    sentences: list[dict[str, Any]],
    row_overlap_threshold: float = 0.65,
    sentence_coverage_threshold: float = 0.6,
) -> int:
    """row_ids=[]인 sentence를 char-overlap 기반으로 추가 매칭.

    Args:
        rows_text: 행 텍스트 리스트
        sentences: sentence dict 리스트 (row_ids in-place 수정)
        row_overlap_threshold: row chars의 X% 이상이 sentence chars에 있어야 후보
        sentence_coverage_threshold: 할당된 row들의 chars가 sentence chars의 X% 이상이면 stop

    Returns:
        fuzzy로 새로 매칭된 sentence 수
    """
    # 이미 precise 매칭으로 할당된 row는 재사용 안 함 (한 row = 한 sentence)
    used_rows: set[int] = set()
    for s in sentences:
        used_rows.update(s.get("row_ids", []))

    row_chars = [set(normalize_for_match(r)) for r in rows_text]

    newly_matched = 0
    for s in sentences:
        if s.get("row_ids"):
            continue
        s_chars = set(normalize_for_match(s.get("text", "")))
        if not s_chars:
            continue

        candidates: list[tuple[int, float]] = []
        for ri, rcs in enumerate(row_chars):
            if ri in used_rows or not rcs:
                continue
            overlap = len(rcs & s_chars) / len(rcs)
            if overlap >= row_overlap_threshold:
                candidates.append((ri, overlap))

        if not candidates:
            continue

        candidates.sort(key=lambda x: -x[1])
        assigned: list[int] = []
        covered: set[str] = set()
        for ri, _ in candidates:
            assigned.append(ri)
            covered |= row_chars[ri]
            used_rows.add(ri)
            if len(covered & s_chars) / max(len(s_chars), 1) >= sentence_coverage_threshold:
                break
        if assigned:
            s["row_ids"] = sorted(assigned)
            newly_matched += 1

    return newly_matched


def normalize_bbox(bbox: list[float], page_w: float, page_h: float) -> list[float]:
    """pdfplumber pt 좌표를 [0, 1]로 정규화. bbox = [x0, y0, x1, y1]."""
    x0, y0, x1, y1 = bbox
    return [
        max(0.0, min(1.0, x0 / page_w)),
        max(0.0, min(1.0, y0 / page_h)),
        max(0.0, min(1.0, x1 / page_w)),
        max(0.0, min(1.0, y1 / page_h)),
    ]


def process_record(
    rec: dict[str, Any],
    image_dir: Path,
    max_rows: int,
    max_sents: int,
    use_fuzzy: bool = True,
    use_sequential: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """한 PDF record → 학습 sample.

    페이지 0(첫 페이지)만 사용. row_ids 매핑은 0페이지에 속한 row로 제한.
    use_fuzzy=True 면 row_ids=[]인 sentence에 fuzzy char-overlap 매칭 시도.

    Returns:
        (sample dict 또는 None, stats {precise, fuzzy_added})
    """
    stats = {"precise": 0, "fuzzy_added": 0}
    pdf_name = rec["pdf"]
    stem = Path(pdf_name).stem
    img_path = image_dir / f"{stem}__p0.png"
    if not img_path.exists():
        return None, stats

    rows = rec.get("rows", [])
    if not rows:
        return None, stats

    # 페이지 0의 row만
    page0_rows = [(i, r) for i, r in enumerate(rows) if r.get("page", 0) == 0]
    if not page0_rows:
        return None, stats

    # 원본 row index → 페이지0 내 새 index 매핑
    orig_to_p0: dict[int, int] = {}
    p0_bboxes: list[list[float]] = []
    p0_texts: list[str] = []
    for new_idx, (orig_idx, r) in enumerate(page0_rows):
        orig_to_p0[orig_idx] = new_idx
        pw, ph = r.get("page_width", 595.0), r.get("page_height", 842.0)
        p0_bboxes.append(normalize_bbox(r["bbox"], pw, ph))
        p0_texts.append(r["text"])

    if len(p0_bboxes) > max_rows:
        return None, stats

    # 모든 sentence를 페이지 0 인덱스로 매핑 — fuzzy 호출 위해 unmatched 도 유지
    sentences_p0: list[dict[str, Any]] = []
    for s in rec.get("sentences", []):
        orig_ids = s.get("row_ids", [])
        new_ids = [orig_to_p0[i] for i in orig_ids if i in orig_to_p0]
        sentences_p0.append({
            "text": s.get("text", ""),
            "role_hint": s.get("role_hint", "etc"),
            "row_ids": new_ids,
        })
    stats["precise"] = sum(1 for s in sentences_p0 if s["row_ids"])

    # 매핑 알고리즘 선택
    if use_sequential:
        # 기존 precise row_ids 무시하고 sequential alignment로 새로 매핑
        before = sum(1 for s in sentences_p0 if s["row_ids"])
        n_matched = sequential_alignment(p0_texts, sentences_p0)
        stats["fuzzy_added"] = n_matched - 0  # sequential은 처음부터 매핑
        stats["precise"] = n_matched  # 통계용 (precise vs fuzzy 구분 없음)
    elif use_fuzzy:
        stats["fuzzy_added"] = fuzzy_enhance_row_ids(p0_texts, sentences_p0)

    # row_ids 있는 sentence만 keep
    sent_row_ids: list[list[int]] = []
    sent_texts: list[str] = []
    for s in sentences_p0:
        if s["row_ids"]:
            sent_row_ids.append(s["row_ids"])
            sent_texts.append(s["text"])

    if not sent_row_ids:
        return None, stats
    if len(sent_row_ids) > max_sents:
        sent_row_ids = sent_row_ids[:max_sents]
        sent_texts = sent_texts[:max_sents]

    sample = {
        "pdf": pdf_name,
        "image_path": str(img_path),
        "bboxes": p0_bboxes,
        "row_texts": p0_texts,
        "sentence_row_ids": sent_row_ids,
        "sentence_texts": sent_texts,
        "n_rows": len(p0_bboxes),
        "n_sentences": len(sent_row_ids),
    }
    return sample, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jsonl", required=True, type=Path, help="kd_train_pointerdoc.jsonl")
    ap.add_argument("--image-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-rows", type=int, default=128)
    ap.add_argument("--max-sentences", type=int, default=32)
    ap.add_argument("--no-fuzzy", action="store_true",
                    help="fuzzy char-overlap 매칭 비활성화 (디버깅용)")
    ap.add_argument("--sequential", action="store_true",
                    help="sequential alignment 사용 (순서 보존 + 연속 row + cursor monotonic)")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    kept = 0
    skipped_no_img = 0
    skipped_no_data = 0
    total_precise = 0
    total_fuzzy_added = 0
    total_final_matched = 0

    with open(args.jsonl, encoding="utf-8") as f_in, open(args.out, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except Exception:
                continue
            sample, stats = process_record(
                rec, args.image_dir, args.max_rows, args.max_sentences,
                use_fuzzy=not args.no_fuzzy and not args.sequential,
                use_sequential=args.sequential,
            )
            total_precise += stats["precise"]
            total_fuzzy_added += stats["fuzzy_added"]
            if sample is None:
                stem = Path(rec.get("pdf", "")).stem
                if not (args.image_dir / f"{stem}__p0.png").exists():
                    skipped_no_img += 1
                else:
                    skipped_no_data += 1
                continue
            total_final_matched += sample["n_sentences"]
            f_out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            kept += 1

    print(f"Total records:           {total}")
    print(f"Kept:                    {kept}")
    print(f"Skipped (no image):      {skipped_no_img}")
    print(f"Skipped (no data):       {skipped_no_data}")
    print(f"Sentence matching:")
    print(f"  precise (char-substr): {total_precise}")
    print(f"  fuzzy added:           {total_fuzzy_added}")
    print(f"  final (in samples):    {total_final_matched}")
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()
