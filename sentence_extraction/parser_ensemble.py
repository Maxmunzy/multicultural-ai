"""Parser Ensemble — Format별 여러 parser 병렬 실행 + Selection.

PDF: pymupdf + pdfplumber + pdfminer.six 병렬
HWP: pyhwp (hwp5txt)
HWPX: zip + XML 직접 파싱

Selection: rule-based quality metric (짧은 row 비율, 평균 row 길이, 단어 끊김).
나중에 LM perplexity 기반으로 확장 가능.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable


# ─── PDF parsers ────────────────────────────────────────────────────────────

_BULLET_RE = re.compile(r"[▪▸•◦○◆◇▶]")


def _is_mergeable_singleton(text: str) -> bool:
    """Merge 대상 한 글자인지 — 한글/영문/숫자만, 특수문자(dash, bullet 등) 제외."""
    s = text.strip()
    return len(s) == 1 and s.isalnum()


def merge_singleton_words(
    words: list[dict],
    same_line_tol: float = 5.0,
    max_merged_len: int = 20,
) -> list[dict]:
    """같은 line의 연속된 한글자 word들을 합침.

    PDF의 자간 큰 헤더 ("가 정 통 신 문" / "제 공 서 비 스" 등)가
    pdfplumber에서 한 글자씩 word로 분리되는 문제 해결.

    주의: dash/bullet 같은 특수문자 한 글자는 합치지 않음 (절취선 등에서 폭주 방지).
    합친 결과 길이도 max_merged_len자로 제한.

    입력 word dict는 pdfplumber.extract_words() 형식 (x0, x1, top, bottom, text).
    """
    if not words:
        return words
    merged: list[dict] = []
    i = 0
    while i < len(words):
        cur = dict(words[i])
        if _is_mergeable_singleton(cur["text"]):
            j = i + 1
            while (
                j < len(words)
                and _is_mergeable_singleton(words[j]["text"])
                and abs(words[j]["top"] - cur["top"]) < same_line_tol
                and len(cur["text"]) + len(words[j]["text"]) <= max_merged_len
            ):
                cur["text"] += words[j]["text"]
                # bbox union — min/max로 reading order 거꾸로인 경우도 안전
                cur["x0"] = min(cur["x0"], words[j]["x0"])
                cur["x1"] = max(cur["x1"], words[j]["x1"])
                cur["top"] = min(cur["top"], words[j]["top"])
                cur["bottom"] = max(cur["bottom"], words[j]["bottom"])
                j += 1
            merged.append(cur)
            i = j
        else:
            merged.append(cur)
            i += 1
    return merged


def dedup_overlapping_words(
    words: list[dict],
    pos_tol: float = 2.0,
) -> list[dict]:
    """디자인 더블 프린팅 제거 — 같은 텍스트를 1~2px offset으로 두 번 인쇄해
    bold 효과 흉내내는 PDF 트릭이 pdfplumber.extract_words에서 word를 2배로
    추출하는 문제 해결 (예: AIEP 동의서 헤더).

    같은 좌표 (top/x0/x1 ±pos_tol) + 같은 text가 이미 결과에 있으면 skip.
    표 셀에 같은 값이 위/아래 반복되는 경우는 좌표가 다르므로 안전.
    """
    if not words:
        return words
    kept: list[dict] = []
    for w in words:
        is_dup = any(
            k["text"] == w["text"]
            and abs(k["top"] - w["top"]) <= pos_tol
            and abs(k["x0"] - w["x0"]) <= pos_tol
            and abs(k["x1"] - w["x1"]) <= pos_tol
            for k in kept
        )
        if not is_dup:
            kept.append(w)
    return kept


def _split_cell_bullets(value: str) -> list[str]:
    """cell 안의 bullet marker로 분리. 없으면 원본 1개 list.

    Bullet 1개짜리는 그대로, 2개 이상이면 각 항목 별도 sentence 생성용.
    """
    parts = _BULLET_RE.split(value)
    parts = [p.strip() for p in parts if p.strip()]
    return parts if len(parts) > 1 else [value.strip()]


def _detect_table_orientation(rows: list[list[str]]) -> str:
    """col-major vs row-major 자동 판별 (cell 길이 분산 기반).

    가정: 같은 attribute의 값들은 길이/패턴이 비슷 → 분산 작음.
    - col-major (col=entity, row=attr): 한 row 안 cell들이 같은 attr → row 분산 작음
    - row-major (row=entity, col=attr): 한 col 안 cell들이 같은 attr → col 분산 작음
    """
    import statistics
    if len(rows) < 3 or len(rows[0]) < 3:
        return "row-major"  # 작은 표는 단순화

    # header row/col 제외한 body cell 길이
    body_lens = [[len(rows[i][j]) for j in range(1, len(rows[0]))] for i in range(1, len(rows))]
    if not body_lens or not body_lens[0]:
        return "row-major"

    # row별 분산
    row_vars = [statistics.pstdev(r) for r in body_lens if len(r) > 1]
    # col별 분산
    col_vars = []
    for j in range(len(body_lens[0])):
        col = [body_lens[i][j] for i in range(len(body_lens))]
        if len(col) > 1:
            col_vars.append(statistics.pstdev(col))

    if not row_vars or not col_vars:
        return "row-major"

    avg_row_var = statistics.mean(row_vars)
    avg_col_var = statistics.mean(col_vars)

    return "col-major" if avg_row_var < avg_col_var else "row-major"


def _table_to_row_join(table: list[list[str | None]]) -> list[str]:
    """L 옵션 — 표 row 단위 cells join (v4와 동일, 긴 sentence).

    PDF reading order 일치 → norm-match 매칭률 ↑.
    """
    if not table or len(table) < 1:
        return []
    sentences: list[str] = []
    max_cell_len = max(
        (len((c or "").strip()) for row in table for c in row), default=0
    )
    if max_cell_len > 500:
        return []
    for row in table:
        cells = [(c or "").strip().replace("\n", " ") for c in row]
        cells = [c for c in cells if c]
        if not cells:
            continue
        sentences.append(" ".join(cells))
    return sentences


def _table_to_entity_oneline(table: list[list[str | None]]) -> list[str]:
    """J 옵션 — entity 단위 한 줄 sentence (긴 sentence, 매칭 어렵지만 entity 학습 신호).

    각 entity name + 그 entity의 모든 attr이 한 sentence로 묶임.
    col-major / row-major 자동 판별 후 entity별 한 줄.
    """
    if not table or len(table) < 1:
        return []
    rows = [[(c or "").strip().replace("\n", " ") for c in row] for row in table]
    max_cell_len = max((len(c) for row in rows for c in row), default=0)
    if max_cell_len > 500:
        return []

    if len(rows) <= 2:
        return []  # 1-row, 2-row 표는 L (row join)으로만 처리

    sentences: list[str] = []
    orientation = _detect_table_orientation(rows)

    if orientation == "col-major":
        attr_names = [rows[i][0] if rows[i] else "" for i in range(1, len(rows))]
        for j in range(1, len(rows[0])):
            entity = rows[0][j]
            if not entity:
                continue
            parts = [entity]
            for ri, i in enumerate(range(1, len(rows))):
                attr = attr_names[ri]
                value = rows[i][j] if j < len(rows[i]) else ""
                if not value:
                    continue
                parts.append(f"{attr}: {value}" if attr else value)
            sentences.append(" ".join(parts))
    else:
        attr_names = rows[0]
        for i in range(1, len(rows)):
            entity = rows[i][0] if rows[i] else ""
            if not entity:
                continue
            parts = [entity]
            for j in range(1, len(attr_names)):
                attr = attr_names[j]
                value = rows[i][j] if j < len(rows[i]) else ""
                if not value:
                    continue
                parts.append(f"{attr}: {value}" if attr else value)
            sentences.append(" ".join(parts))

    return sentences


def _table_to_entity_blocks(table: list[list[str | None]]) -> list[str]:
    """표 → entity 단위 블록 (Claude 패턴: entity name 단독 + 각 attr 별도, prefix 없음).

    출력 예 (어린이날 col-major):
      "오늘은 내가 과학왕!"        ← entity name
      "내용: 미션 도장깨기 (...)"
      "운영 시간: 상시"
      "참여 방법: 현장 참여"
      "사이언스 매직쇼"
      "내용: 신기한 마술 ..."
      ...

    학습 데이터 라벨링용. _table_to_sentences (entity prefix 붙는 형식)와 다름.
    """
    if not table or len(table) < 1:
        return []
    rows = [[(c or "").strip().replace("\n", " ") for c in row] for row in table]
    max_cell_len = max((len(c) for row in rows for c in row), default=0)
    if max_cell_len > 500:
        return []

    sentences: list[str] = []

    def _emit_value(attr: str, value: str) -> None:
        """한 cell의 value를 bullet 별로 split해서 emit."""
        for v in _split_cell_bullets(value):
            if attr:
                sentences.append(f"{attr}: {v}")
            else:
                sentences.append(v)

    if len(rows) == 1:
        return [c for c in rows[0] if c]

    if len(rows) == 2:
        header, body = rows[0], rows[1]
        for h, v in zip(header, body):
            if not v:
                continue
            if h:
                sentences.append(f"{h}: {v}")
            else:
                sentences.append(v)
        return sentences

    orientation = _detect_table_orientation(rows)

    if orientation == "col-major":
        # col = entity (row 0 = entity names), row = attr (col 0 = attr names)
        attr_names = [rows[i][0] if rows[i] else "" for i in range(1, len(rows))]
        for j in range(1, len(rows[0])):
            entity = rows[0][j]
            if entity:
                sentences.append(entity)
            for ri, i in enumerate(range(1, len(rows))):
                attr = attr_names[ri]
                value = rows[i][j] if j < len(rows[i]) else ""
                if not value:
                    continue
                _emit_value(attr, value)
    else:
        # row-major: row = entity (col 0 = entity names), col = attr (row 0 = attr names)
        attr_names = rows[0]
        for i in range(1, len(rows)):
            entity = rows[i][0] if rows[i] else ""
            if entity:
                sentences.append(entity)
            for j in range(1, len(attr_names)):
                attr = attr_names[j]
                value = rows[i][j] if j < len(rows[i]) else ""
                if not value:
                    continue
                _emit_value(attr, value)

    return sentences


def _table_to_sentences(table: list[list[str | None]]) -> list[str]:
    """표 → entity별 한 sentence (orientation 자동 판별).

    Cases:
    - 1-row: 각 cell이 독립 정보
    - 2-row (header + body): "{h}: {v}" 페어
    - 3+ row: col/row-major 판별 후 entity별 attr 묶음
    """
    if not table or len(table) < 1:
        return []
    rows = [[(c or "").strip().replace("\n", " ") for c in row] for row in table]
    # layout container (한 셀에 거대한 텍스트) 제외
    max_cell_len = max((len(c) for row in rows for c in row), default=0)
    if max_cell_len > 500:
        return []

    if len(rows) == 1:
        return [c for c in rows[0] if c]

    if len(rows) == 2:
        header, body = rows[0], rows[1]
        return [f"{h}: {v}" if h else v for h, v in zip(header, body) if v]

    orientation = _detect_table_orientation(rows)
    sentences: list[str] = []

    def _emit(entity: str, attr: str, value: str) -> None:
        for v in _split_cell_bullets(value):
            kv = f"{attr}: {v}" if attr else v
            sentences.append(f"{entity} - {kv}" if entity else kv)

    if orientation == "col-major":
        # col = entity (row 0 = entity names), row = attr (col 0 = attr names)
        header = rows[0]
        for j in range(1, len(header)):
            entity = header[j]
            for i in range(1, len(rows)):
                attr = rows[i][0] if rows[i] else ""
                value = rows[i][j] if j < len(rows[i]) else ""
                if not value:
                    continue
                _emit(entity, attr, value)
    else:
        # row-major: row = entity (col 0 = entity names), col = attr (row 0 = attr names)
        header_attrs = rows[0]
        for i in range(1, len(rows)):
            entity = rows[i][0] if rows[i] else ""
            for j in range(1, len(header_attrs)):
                attr = header_attrs[j]
                value = rows[i][j] if j < len(rows[i]) else ""
                if not value:
                    continue
                _emit(entity, attr, value)

    return sentences


def extract_pdf_pymupdf(pdf_path: Path) -> str:
    """pymupdf get_text('dict') — block-aware join (현재 main)."""
    import fitz
    doc = fitz.open(pdf_path)
    text_blocks: list[str] = []
    for page in doc:
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            lines: list[str] = []
            for line in b.get("lines", []):
                t = " ".join(s["text"] for s in line.get("spans", [])).strip()
                if t:
                    lines.append(t)
            if lines:
                text_blocks.append(" ".join(lines))
    doc.close()
    return "\n".join(text_blocks)


def _bbox_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """두 bbox의 IoU. (x0, y0, x1, y1) 형식."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = (ax1 - ax0) * (ay1 - ay0)
    return inter / max(area_a, 1)  # block 면적 대비 overlap 비율


def extract_pdf_tableware(pdf_path: Path) -> str:
    """본문 + 표를 같은 1D text로 통합 — 표 row 한 줄로 join.

    핵심 아이디어:
      - 본문은 pymupdf block 단위로 추출
      - 표 영역은 pdfplumber로 인식
      - 표 영역과 겹치는 pymupdf block은 skip (중복 방지)
      - 표 row는 cell들을 " | " 또는 ", "로 join해서 한 줄 sentence로
      - 표 위치(y 좌표)에 표 row sentence들 삽입 → BIO가 본문/표 동일 패턴 처리

    BIO 학습 데이터 재생성 시 같은 함수 사용해야 distribution 일치.
    """
    import fitz
    import pdfplumber

    pages_output: list[str] = []
    with pdfplumber.open(pdf_path) as plumb_doc, fitz.open(pdf_path) as fitz_doc:
        for page_idx in range(len(fitz_doc)):
            plumb_page = plumb_doc.pages[page_idx]
            fitz_page = fitz_doc[page_idx]

            # 1. 표 영역 bbox 추출
            tables = plumb_page.find_tables()
            table_regions: list[tuple[tuple[float, float, float, float], list[list[str | None]]]] = []
            for t in tables:
                bbox = t.bbox  # (x0, top, x1, bottom) in pdfplumber 좌표 (top-left origin)
                rows = t.extract()
                if rows:
                    table_regions.append((bbox, rows))

            # 2. pymupdf block 추출 + 표 영역과 겹치지 않는 것만
            items: list[tuple[float, str]] = []  # (y_position, text)
            for b in fitz_page.get_text("dict").get("blocks", []):
                if b.get("type", 0) != 0:
                    continue
                b_bbox = b.get("bbox", (0, 0, 0, 0))  # pymupdf도 top-left origin
                # 표 영역과 70% 이상 겹치면 skip
                in_table = any(_bbox_overlap(b_bbox, tr_bbox) > 0.5 for tr_bbox, _ in table_regions)
                if in_table:
                    continue
                lines: list[str] = []
                for line in b.get("lines", []):
                    t = " ".join(s["text"] for s in line.get("spans", [])).strip()
                    if t:
                        lines.append(t)
                if lines:
                    y_pos = b_bbox[1]
                    items.append((y_pos, " ".join(lines)))

            # 3. 표 row → 한 줄 sentence (cell join). col/row-major 판별 X — 단순 join
            for tr_bbox, rows in table_regions:
                y_top = tr_bbox[1]
                for row in rows:
                    cells = [(c or "").strip().replace("\n", " ") for c in row]
                    cells = [c for c in cells if c]
                    if not cells:
                        continue
                    row_text = " | ".join(cells)  # cell separator
                    # 표 row를 표 영역 y_top 기준 약간씩 stagger해서 같은 위치
                    items.append((y_top, row_text))
                    y_top += 0.01  # 같은 표 안 row 순서 유지

            # 4. y 좌표 순으로 정렬 (자연스러운 reading order)
            items.sort(key=lambda x: x[0])
            page_text = "\n".join(t for _, t in items)
            if page_text:
                pages_output.append(page_text)

    return "\n".join(pages_output)


def extract_pdf_pdfplumber(pdf_path: Path) -> str:
    """pdfplumber extract_text — layout flag."""
    import pdfplumber
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text(layout=False) or ""
            parts.append(txt)
    return "\n".join(parts)


def extract_pdf_pdfminer(pdf_path: Path) -> str:
    """pdfminer.six (별도 layout 분석)."""
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(pdf_path)) or ""
    except Exception as e:
        print(f"pdfminer failed: {e}", file=sys.stderr)
        return ""


def extract_pdf_tables(pdf_path: Path) -> list[str]:
    """pdfplumber.extract_tables() — 표를 sentence 단위로 추출.

    Layout container (전체 페이지를 한 셀로 묶은 frame) 자동 제외.
    """
    import pdfplumber
    all_sentences: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                all_sentences.extend(_table_to_sentences(table))
    return all_sentences


def extract_pdf_table_entities(pdf_path: Path) -> list[str]:
    """pdfplumber.extract_tables() — 표를 entity 단위 블록으로 추출 (Claude 패턴).

    entity name 단독 + 각 attr 별도 sentence (prefix 없음).
    학습 데이터 라벨링용 — v5 axis.
    """
    import pdfplumber
    all_sentences: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                all_sentences.extend(_table_to_entity_blocks(table))
    return all_sentences


def extract_pdf_table_v6(pdf_path: Path) -> list[str]:
    """v6 — L + J 조합. row join (PDF order, 매칭률 ↑) + entity oneline (entity 학습 신호).

    학습 데이터의 표 sentence가 다 긴 형식 → v5b의 짧은 sentence 문제 해결.
    """
    import pdfplumber
    all_sentences: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                all_sentences.extend(_table_to_row_join(table))  # L
                all_sentences.extend(_table_to_entity_oneline(table))  # J
    return all_sentences


def extract_pdf_ensemble(pdf_path: Path, workers: int = 3) -> dict[str, str]:
    """모든 PDF parser 병렬 실행 → name → text. (본문만)"""
    parsers: dict[str, Callable[[Path], str]] = {
        "pymupdf": extract_pdf_pymupdf,
        "pdfplumber": extract_pdf_pdfplumber,
        "pdfminer": extract_pdf_pdfminer,
    }
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fn, pdf_path): name for name, fn in parsers.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                print(f"{name} FAIL: {e}", file=sys.stderr)
                results[name] = ""
    return results


# ─── HWP / HWPX parsers ─────────────────────────────────────────────────────

def extract_hwp_hwp5txt(hwp_path: Path) -> str:
    """pyhwp hwp5txt CLI 호출."""
    r = subprocess.run(
        ["hwp5txt", str(hwp_path)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if r.returncode != 0:
        return ""
    # `<표>`, `<그림>` 마커 제거
    text = r.stdout
    text = re.sub(r"<[^>]+>", "", text)
    return text


def extract_hwpx_xml(hwpx_path: Path) -> str:
    """HWPX = zip + XML — paragraph text 추출."""
    import xml.etree.ElementTree as ET
    texts: list[str] = []
    with zipfile.ZipFile(hwpx_path) as z:
        section_names = [n for n in z.namelist() if "section" in n.lower() and n.endswith(".xml")]
        for sec_name in section_names:
            sec_xml = z.read(sec_name).decode("utf-8")
            root = ET.fromstring(sec_xml)
            for elem in root.iter():
                t = (elem.text or "").strip()
                if t:
                    texts.append(t)
    return "\n".join(texts)


def extract_hwp_ensemble(hwp_path: Path) -> dict[str, str]:
    return {"hwp5txt": extract_hwp_hwp5txt(hwp_path)}


def extract_hwpx_ensemble(hwpx_path: Path) -> dict[str, str]:
    return {"hwpx_xml": extract_hwpx_xml(hwpx_path)}


# ─── Selection — quality scoring ────────────────────────────────────────────

_TERMINATOR = re.compile(r"[.!?][\"'」』)\]\s]*$|다\.\s*$|요\.\s*$|니다\.\s*$|까\?\s*$")


def score_text(text: str) -> float:
    """Rule-based quality score. 높을수록 더 자연스러운 한국어 통신문 텍스트.

    Factors:
      + 평균 row 길이 (긴 row = 의미 paragraph 보존)
      - 너무 짧은 row 비율 (< 4 chars = noise / 깨짐)
      + sentence terminator로 끝나는 row 비율 (자연스러운 문장 boundary)
      - 줄바꿈 비율 (chars 대비)
    """
    if not text.strip():
        return -1e9
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return -1e9
    total_chars = sum(len(l) for l in lines)
    n = len(lines)
    avg_len = total_chars / n
    short_ratio = sum(1 for l in lines if len(l) < 4) / n
    term_ratio = sum(1 for l in lines if _TERMINATOR.search(l)) / n
    newline_ratio = n / max(total_chars, 1)

    score = avg_len * 1.0
    score -= short_ratio * 30.0      # 짧은 row 페널티
    score += term_ratio * 20.0       # 자연스러운 종결
    score -= newline_ratio * 100.0   # 과한 줄바꿈 페널티
    return score


def select_best(results: dict[str, str]) -> tuple[str, str, dict[str, float]]:
    """후보 중 score 높은 거 선택. Returns (parser_name, text, all_scores)."""
    scores = {name: score_text(text) for name, text in results.items()}
    best_name = max(scores, key=scores.get)
    return best_name, results[best_name], scores


# ─── Top-level interface ────────────────────────────────────────────────────

def extract_text(file_path: Path) -> tuple[str, str, dict[str, float], list[str]]:
    """Format detection + ensemble + selection + tables (별도).

    표는 selection 대상이 아니라 별도 sentence list로 반환.
    BIO 통과 안 시키고 그대로 KoELECTRA에 전달 (이미 row 단위 정리됨).

    Returns:
        (cleaned_text, best_parser_name, all_scores, table_sentences)
    """
    suffix = file_path.suffix.lower()
    table_sentences: list[str] = []
    if suffix == ".pdf":
        results = extract_pdf_ensemble(file_path)
        try:
            table_sentences = extract_pdf_tables(file_path)
        except Exception as e:
            print(f"tables FAIL: {e}", file=sys.stderr)
    elif suffix == ".hwp":
        results = extract_hwp_ensemble(file_path)
    elif suffix == ".hwpx":
        results = extract_hwpx_ensemble(file_path)
    else:
        raise ValueError(f"Unsupported format: {suffix}")

    best_name, text, scores = select_best(results)
    return text, best_name, scores, table_sentences


if __name__ == "__main__":
    import argparse
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--show-all", action="store_true", help="모든 parser 결과 출력")
    args = ap.parse_args()

    text, best, scores = extract_text(args.file)
    print(f"=== Scores ===")
    for name, score in sorted(scores.items(), key=lambda x: -x[1]):
        marker = " ⭐" if name == best else ""
        print(f"  {name:>12}: {score:.2f}{marker}")
    print()
    if args.show_all:
        suffix = args.file.suffix.lower()
        if suffix == ".pdf":
            results = extract_pdf_ensemble(args.file)
        else:
            text_only, _, _ = extract_text(args.file)
            results = {best: text_only}
        for name, t in results.items():
            print(f"--- {name} ({len(t)} chars) ---")
            for i, line in enumerate(t.split("\n")):
                if line.strip():
                    print(f"  [{i:02d}] {line}")
            print()
    else:
        print(f"=== Best ({best}) ===")
        print(text[:2000])
