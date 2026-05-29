"""kiwi + camelot 기반 가정통신문 문장 추출 (LLM API 비의존, 변형 0).

본문: pdfplumber word(표 영역 제외) → char stream → kiwipiepy split_into_sents
표:   camelot cell = 1문장 (결정적, 모델 미경유)
merge: y좌표 정렬

- 변형 0: kiwi offset으로 원본 char substring만 취함 (char stream = 원본 word space-join).
- LLM/번역 호출 없음. 한국어 종결어미(EF) 기반 문장 경계.
- camelot은 표 cell 구조를 결정적으로 파싱 (학습 모델 아님).
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_kiwi = None


def _get_kiwi():
    """Kiwi 싱글톤 (형태소 모델 로딩 1회만)."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        logger.info("Loading Kiwi (kiwipiepy)...")
        _kiwi = Kiwi()
        logger.info("Kiwi loaded.")
    return _kiwi


def _in_any_table(w: dict, bboxes: list) -> bool:
    cx = (w["x0"] + w["x1"]) / 2
    cy = (w["top"] + w["bottom"]) / 2
    return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in bboxes)


# ── word 정제 — sentence_extraction/parser_ensemble.py에서 vendoring ──
# backend가 research 디렉토리(sentence_extraction)에 sys.path로 의존하지 않도록
# 순수 함수만 내장 (컨테이너엔 sentence_extraction이 COPY되지 않음).

def _is_mergeable_singleton(text: str) -> bool:
    """Merge 대상 한 글자인지 — 한글/영문/숫자만, 특수문자(dash, bullet) 제외."""
    s = text.strip()
    return len(s) == 1 and s.isalnum()


def _merge_singleton_words(
    words: list, same_line_tol: float = 5.0, max_merged_len: int = 20,
) -> list:
    """같은 line의 연속된 한글자 word 합침 — 자간 큰 헤더("가 정 통 신 문") 복원.

    dash/bullet 한 글자는 제외(절취선 폭주 방지), 합친 길이 max_merged_len 제한.
    입력 word dict는 pdfplumber.extract_words() 형식 (x0, x1, top, bottom, text).
    """
    if not words:
        return words
    merged: list = []
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


def _dedup_overlapping_words(words: list, pos_tol: float = 2.0) -> list:
    """디자인 더블 프린팅 제거 — 같은 text를 1~2px offset으로 두 번 인쇄해 bold
    흉내내는 PDF가 pdfplumber에서 word 2배 추출되는 문제 해결.

    같은 좌표(top/x0/x1 ±pos_tol) + 같은 text가 이미 있으면 skip.
    표 셀 반복값은 좌표가 다르므로 안전.
    """
    if not words:
        return words
    kept: list = []
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


def _body_sentences(words: list) -> list[tuple[str, float]]:
    """본문 word → char stream → kiwi 문장. Returns [(sentence, y_top)]."""
    if not words:
        return []
    parts: list[str] = []
    c2w: list[int] = []
    for wi, w in enumerate(words):
        t = w["text"]
        if not t:
            continue
        if parts:
            parts.append(" ")
            c2w.append(wi - 1 if wi > 0 else 0)
        for ch in t:
            parts.append(ch)
            c2w.append(wi)
    text = "".join(parts)
    if not text.strip():
        return []

    kiwi = _get_kiwi()
    out: list[tuple[str, float]] = []
    for sent in kiwi.split_into_sents(text):
        s = text[sent.start:sent.end].strip()  # 변형 0: 원본 substring
        if not s:
            continue
        wi = c2w[sent.start] if sent.start < len(c2w) else (c2w[-1] if c2w else 0)
        y = words[wi]["top"] if 0 <= wi < len(words) else 0.0
        out.append((s, y))
    return out


def _table_sentences(pdf_path: str, page_idx: int, table_bboxes: list,
                     H: float) -> list[tuple[str, float]]:
    """camelot 표 cell = 1문장 (결정적). Returns [(sentence, y_top)]."""
    if not table_bboxes:
        return []
    try:
        import camelot
    except ImportError:
        return []
    areas = [f"{b[0]},{H - b[1]},{b[2]},{H - b[3]}" for b in table_bboxes]
    try:
        tables = camelot.read_pdf(
            pdf_path, flavor="lattice", pages=str(page_idx + 1), table_areas=areas,
        )
    except Exception as e:
        logger.warning("camelot read failed p%d: %s", page_idx, e)
        return []

    out: list[tuple[str, float]] = []

    def cell(r: int, c: int, df) -> str:
        # cell 내부 token 단일 공백 join (PDF 셀 폭 줄바꿈 제거 — 내용 변형 아님)
        return " ".join(str(df.iloc[r][c]).split())

    for tbl in tables:
        df = tbl.df
        nr, nc = len(df), len(df.columns)
        if nr < 2:
            for c in range(nc):
                t = cell(0, c, df)
                if t:
                    out.append((t, H - tbl.cells[0][c].y2))
        else:
            hdr = [cell(0, c, df) for c in range(nc)]
            for r in range(1, nr):
                for c in range(nc):
                    v = cell(r, c, df)
                    if not v:
                        continue
                    out.append((f"{hdr[c]}: {v}" if hdr[c] else v, H - tbl.cells[r][c].y2))
    return out


def _extract_page(pdf_path: str, page_idx: int, page) -> list[str]:
    """단일 page → 본문(kiwi) + 표(camelot) merge sentence list."""
    W, H = page.width, page.height
    if W <= 0 or H <= 0:
        return []
    words = page.extract_words(
        use_text_flow=True, keep_blank_chars=False, x_tolerance=3, y_tolerance=3,
    )
    words = _merge_singleton_words(_dedup_overlapping_words(words))
    try:
        tbboxes = [t.bbox for t in page.find_tables()]
    except Exception:
        tbboxes = []
    body = [w for w in words if not _in_any_table(w, tbboxes)]

    merged = _body_sentences(body) + _table_sentences(pdf_path, page_idx, tbboxes, H)
    merged.sort(key=lambda x: x[1])
    return [s for s, _ in merged]


def extract_sentences_from_pdf_bytes(raw_bytes: bytes) -> list[str]:
    """PDF bytes → sentence list (kiwi 본문 + camelot 표). 변형 0."""
    import pdfplumber

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name
    try:
        all_sents: list[str] = []
        with pdfplumber.open(tmp_path) as pdf:
            for pi, page in enumerate(pdf.pages):
                try:
                    all_sents.extend(_extract_page(tmp_path, pi, page))
                except Exception as e:
                    logger.warning("page %d extract failed: %s", pi, e)
        return all_sents
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass
