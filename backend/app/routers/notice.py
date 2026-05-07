import json
import logging
import mimetypes
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from app.auth import get_user, require_teacher, require_user
from app.models.schemas import (
    AnalyzeItem, ApiResponse, Category, Notice, NoticeAnalyzeRequest,
    NoticeSendRequest, SlotCard, SlotEntry, SummarySlots, UserProfile,
    YunjeongTodo,
)
from app.services.extractor import extract_todos, extract_title
from app.services.parser import ParserError, parse_bytes_to_text
from app.services.translator import translate_short_sentence, translate_term
from app.services.classifier import classify_category
from app.services.tts import generate_tts_file
from app.services.slot_extractor import (
    extract_summary_regex_slots, find_when_in_text,
    split_supply_tokens, strip_markers,
)
from app.services.card_builder import build_cards
from app.services.highlight_mapper import build_highlights_from_cards
from app.services.layout_normalizer import (
    normalize_text as llm_normalize_text,
    extract_sentences,
    VISION_SUPPORTED_MIMES,
)
from app.services.ocr_slot_corrector import apply_ocr_slot_corrections
from app.models.schemas import OcrCorrectionEntry
from app.services.mock import MOCK_TODOS

logger = logging.getLogger(__name__)

router = APIRouter()

_notices: dict[str, Notice] = {}
MAX_CARDS = 16  # 학년별 표(공용+개인 12행) 같은 다중 카드 통신문 누락 방지

NOTICES_DIR = Path("/app/static/notices")


def _save_original(notice_id: str, raw_bytes: bytes, filename: str) -> tuple[str, str | None]:
    """업로드된 원본 파일을 static/notices/{notice_id}{ext}로 저장.

    HWP/HWPX는 안드 표준 viewer 없으므로 LibreOffice로 PDF 변환해서 저장.
    그 외(PDF/이미지/텍스트)는 원본 그대로 저장.

    Returns (url, mime_type). 실패 시 mime_type=None.
    """
    import tempfile
    from pathlib import Path as _Path
    from app.services.parser import hwp_to_pdf, ParserError

    ext = os.path.splitext(filename or "")[1].lower()
    if not ext:
        if raw_bytes.startswith(b"%PDF"):
            ext = ".pdf"
        elif raw_bytes[:3] == b"\xff\xd8\xff":
            ext = ".jpg"
        elif raw_bytes.startswith(b"\x89PNG"):
            ext = ".png"

    NOTICES_DIR.mkdir(parents=True, exist_ok=True)

    # HWP/HWPX → PDF 변환 (안드 풀화면 표시용)
    if ext in (".hwp", ".hwpx"):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = _Path(tmp)
                src = tmp_dir / f"input{ext}"
                src.write_bytes(raw_bytes)
                pdf_path = hwp_to_pdf(src, tmp_dir)
                pdf_bytes = pdf_path.read_bytes()
            safe_name = f"{notice_id}.pdf"
            (NOTICES_DIR / safe_name).write_bytes(pdf_bytes)
            return f"/static/notices/{safe_name}", "application/pdf"
        except (ParserError, Exception) as e:
            logger.warning("[upload] HWP→PDF 변환 실패, 원본 HWP 저장: %s", e)
            # fallback: HWP 원본 저장 (안드는 표시 못 하지만 다운로드 링크로 fallback)

    # 일반 경로: 원본 그대로 저장
    safe_name = f"{notice_id}{ext}"
    (NOTICES_DIR / safe_name).write_bytes(raw_bytes)
    mime_type, _ = mimetypes.guess_type(safe_name)
    return f"/static/notices/{safe_name}", mime_type


@router.post("/send", response_model=ApiResponse)
async def send_notice(
    req: NoticeSendRequest,
    user: UserProfile = Depends(require_teacher),
):
    """선생님이 가정통신문 발송 → 부모 수신함에 저장."""
    if user.user_id != req.teacher_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 선생님 ID로만 발송 가능합니다",
        )
    parent = get_user(req.parent_id)
    if parent is None or parent.role != "parent":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"학부모 계정을 찾을 수 없습니다: {req.parent_id}",
        )
    notice_id = str(uuid.uuid4())
    notice = Notice(
        notice_id=notice_id,
        teacher_id=req.teacher_id,
        parent_id=req.parent_id,
        text=req.text,
        todos=[],
    )
    _notices[notice_id] = notice
    return ApiResponse.success(data={"notice_id": notice_id}, message="발송 완료")


@router.post("/extract-text", response_model=ApiResponse)
async def extract_text(
    file: UploadFile = File(...),
    user: UserProfile = Depends(require_user),
):
    """파일 → 텍스트 추출 + (HWP/PDF/이미지) 미리보기 URL.

    선생님 발송 전 미리보기용. Notice 저장·발송 X.
    HWP는 PDF로 변환해서 임시 저장 + URL 응답 → 안드 풀화면 미리보기.
    실제 발송 시 /notice/upload는 같은 변환 한 번 더 (단순함 우선).
    """
    raw_bytes = await file.read()
    try:
        text = parse_bytes_to_text(raw_bytes, file.filename or "")
    except ParserError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"파일 변환 실패: {error}",
        )
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="파일에서 추출된 텍스트가 비어있습니다",
        )

    # 미리보기 파일 저장 (preview-{uuid}.{ext}) → 선생님 안드 풀화면 표시
    preview_id = f"preview-{uuid.uuid4().hex[:12]}"
    try:
        preview_url, preview_mime = _save_original(preview_id, raw_bytes, file.filename or "")
    except Exception as e:
        logger.warning("[extract-text] preview 저장 실패: %s", e)
        preview_url, preview_mime = None, None

    return ApiResponse.success(
        data={
            "text": text,
            "char_count": len(text),
            "filename": file.filename,
            "preview_file_url": preview_url,
            "preview_mime_type": preview_mime,
        },
        message=f"텍스트 추출 완료 ({file.filename})",
    )


@router.post("/upload", response_model=ApiResponse)
async def upload_notice(
    teacher_id: str = Form(...),
    parent_id: str = Form(...),
    file: UploadFile = File(...),
    user: UserProfile = Depends(require_teacher),
):
    """선생님이 HWP/PDF 파일로 가정통신문 발송. 파일 → 텍스트 변환 후 send와 동일 흐름."""
    if user.user_id != teacher_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 선생님 ID로만 발송 가능합니다",
        )
    parent = get_user(parent_id)
    if parent is None or parent.role != "parent":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"학부모 계정을 찾을 수 없습니다: {parent_id}",
        )

    raw_bytes = await file.read()
    try:
        text = parse_bytes_to_text(raw_bytes, file.filename or "")
    except ParserError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"파일 변환 실패: {error}",
        )
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="파일에서 추출된 텍스트가 비어있습니다",
        )
    text, raw_corrections = apply_ocr_slot_corrections(text)
    ocr_entries = [OcrCorrectionEntry(**{k: v for k, v in c.items() if k in OcrCorrectionEntry.model_fields}) for c in raw_corrections]

    notice_id = str(uuid.uuid4())
    original_url, mime_type = _save_original(notice_id, raw_bytes, file.filename or "")
    notice = Notice(
        notice_id=notice_id,
        teacher_id=teacher_id,
        parent_id=parent_id,
        text=text,
        todos=[],
        original_file_url=original_url,
        original_filename=file.filename,
        mime_type=mime_type,
        ocr_corrections=ocr_entries,
    )
    _notices[notice_id] = notice
    return ApiResponse.success(
        data={"notice_id": notice_id, "char_count": len(text), "text": text},
        message=f"파일 업로드 완료 ({file.filename})",
    )


@router.post("/upload-self", response_model=ApiResponse)
async def upload_notice_self(
    parent_id: str = Form(...),
    file: UploadFile = File(...),
    user: UserProfile = Depends(require_user),
):
    """학부모가 종이 통신문 사진/파일을 직접 업로드 → 수신함에 self-send 형태로 저장.

    teacher_id = parent_id (자기 자신이 발신자)로 저장되며
    이후 /analyze/{notice_id} 흐름은 동일.
    """
    if user.role != "parent" or user.user_id != parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 학부모 ID로만 업로드 가능합니다",
        )

    raw_bytes = await file.read()
    try:
        text = parse_bytes_to_text(raw_bytes, file.filename or "")
    except ParserError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"파일 변환 실패: {error}",
        )
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="파일에서 추출된 텍스트가 비어있습니다",
        )
    text, raw_corrections = apply_ocr_slot_corrections(text)
    ocr_entries = [OcrCorrectionEntry(**{k: v for k, v in c.items() if k in OcrCorrectionEntry.model_fields}) for c in raw_corrections]

    notice_id = str(uuid.uuid4())
    original_url, mime_type = _save_original(notice_id, raw_bytes, file.filename or "")
    _notices[notice_id] = Notice(
        notice_id=notice_id,
        teacher_id=parent_id,
        parent_id=parent_id,
        text=text,
        todos=[],
        original_file_url=original_url,
        original_filename=file.filename,
        mime_type=mime_type,
        ocr_corrections=ocr_entries,
    )
    return ApiResponse.success(
        data={"notice_id": notice_id, "char_count": len(text), "text": text},
        message=f"업로드 완료 ({file.filename})",
    )


@router.get("/inbox/{parent_id}", response_model=ApiResponse)
async def get_inbox(
    parent_id: str,
    user: UserProfile = Depends(require_user),
):
    """부모가 수신된 가정통신문 목록 조회. 본인 ID만 허용."""
    if user.role != "parent" or user.user_id != parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 수신함만 조회할 수 있습니다",
        )
    inbox = [n for n in _notices.values() if n.parent_id == parent_id]
    return ApiResponse.success(data=inbox)


@router.delete("/inbox/{parent_id}", response_model=ApiResponse)
async def clear_inbox(
    parent_id: str,
    user: UserProfile = Depends(require_user),
):
    """parent_id 수신함 초기화 (시연용). 본인 ID만 허용."""
    if user.role != "parent" or user.user_id != parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 수신함만 삭제할 수 있습니다",
        )
    targets = [nid for nid, n in _notices.items() if n.parent_id == parent_id]
    for nid in targets:
        del _notices[nid]
    return ApiResponse.success(
        data={"deleted": len(targets)},
        message=f"{parent_id} 수신함 {len(targets)}개 삭제",
    )


@router.delete("/{notice_id}", response_model=ApiResponse)
async def delete_notice(
    notice_id: str,
    user: UserProfile = Depends(require_user),
):
    """개별 가정통신문 삭제 — 학부모 본인 수신함의 카드만 삭제 가능."""
    notice = _notices.get(notice_id)
    if notice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="가정통신문을 찾을 수 없습니다",
        )
    if user.role != "parent" or user.user_id != notice.parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 수신함의 가정통신문만 삭제할 수 있습니다",
        )
    # pop with default — 동시 요청으로 이미 삭제됐어도 KeyError(500) 방지
    _notices.pop(notice_id, None)
    return ApiResponse.success(
        data={"notice_id": notice_id},
        message="가정통신문 삭제 완료",
    )


# ── 슬롯 기반 응답 빌더 ───────────────────────────────────────────
# 강사 처방(2026-04-28):
#   1. 템플릿 슬롯 출력 (summary)
#   2. 정규식 + 모델 하이브리드 (regex source 표시)
#   3. 핵심 명사(준비물·금액) 누락 가시화 (빈 슬롯 즉시 노출)
def _amount_to_ko(amount: int | None) -> str | None:
    if amount is None:
        return None
    return f"{amount:,}원"


def _reconstruct_text_from_layout(layout_json) -> str | None:
    """ML Kit layout_json(라인별 bbox) → Y/X 좌표 기반 구조화 텍스트.

    같은 Y대에 있는 라인 → 한 행으로 묶고 X gap이 크면 열 구분(|).
    Y gap이 크면 빈 줄 삽입 → 두 단락/프로그램 블록 자연 분리.
    layout_json 없거나 파싱 불가면 None 반환 → 호출부가 notice.text 사용.
    """
    if not layout_json:
        return None
    items = layout_json if isinstance(layout_json, list) else None
    if not isinstance(items, list) or not items:
        return None

    entries = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        bbox = item.get("bbox") or {}
        entries.append({
            "page": item.get("page", 1),
            "x": float(bbox.get("x", 0)),
            "y": float(bbox.get("y", 0)),
            "w": float(bbox.get("width", 0)),
            "h": float(bbox.get("height", 20)),
            "text": text,
        })

    if not entries:
        return None

    entries.sort(key=lambda e: (e["page"], e["y"], e["x"]))

    heights = [e["h"] for e in entries if e["h"] > 0]
    median_h = sorted(heights)[len(heights) // 2] if heights else 20.0
    row_thr  = median_h * 0.65   # 같은 행 판정: Y 차이 < 65% 줄높이
    para_thr = median_h * 2.5    # 단락 구분: Y gap > 2.5배 줄높이
    col_thr  = median_h * 2.0    # 열 구분: X gap(이전 우단~현재 좌단) > 2배 줄높이

    rows: list[list[dict]] = []
    cur: list[dict] = [entries[0]]
    for e in entries[1:]:
        prev = cur[-1]
        if e["page"] == prev["page"] and abs(e["y"] - prev["y"]) <= row_thr:
            cur.append(e)
        else:
            rows.append(cur)
            cur = [e]
    rows.append(cur)

    out_lines: list[str] = []
    prev_page: int | None = None
    prev_y: float | None = None

    for row in rows:
        row_page = row[0]["page"]
        row_y    = row[0]["y"]

        if prev_y is not None and (prev_page != row_page or (row_y - prev_y) > para_thr):
            out_lines.append("")

        row.sort(key=lambda e: e["x"])
        parts: list[str] = []
        for j, e in enumerate(row):
            if j > 0:
                prev_right = row[j - 1]["x"] + row[j - 1]["w"]
                gap = e["x"] - prev_right
                parts.append(" | " if gap > col_thr else " ")
            parts.append(e["text"])
        out_lines.append("".join(parts))

        prev_page = row_page
        prev_y    = row_y

    return "\n".join(out_lines).strip() or None


def _page_count_from_layout(layout_json) -> int:
    """layout_json에서 페이지 수 추출. 없거나 형식 다르면 1."""
    if not layout_json:
        return 1
    payload = layout_json
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return 1
    if isinstance(payload, dict):
        pages = payload.get("pages")
        if isinstance(pages, list) and pages:
            return len(pages)
    if isinstance(payload, list):
        seen = {item.get("page", 1) for item in payload if isinstance(item, dict)}
        return max(len(seen), 1)
    return 1


def _build_item(todo: YunjeongTodo, target_lang: str) -> AnalyzeItem:
    """YunjeongTodo + 경이님 카테고리 → AnalyzeItem.

    - category : 경이님 6-class 분류 (주제)
    - action_hint : 윤정님 추출 결과 (행동: 신청/제출/...)
    - due_date / amount : 윤정님 모델 결과 신뢰 (정규식 [2]는 summary 전체 단위 담당)
    - when : 자유텍스트의 일시 표현은 정규식으로 추가 추출
    - what : 준비물 카테고리일 때만 토큰 분해
    - 마크업(■)은 보존, TTS 빌더에서만 strip.

    NOTE — title_translated NLLB 호출 제거 (2026-05-07 시간 단축):
    items 응답 필드는 deprecated (안드 미사용, _build_summary는 category/what/deadline
    만 사용, _build_tts_text는 호출처 없는 dead code). NLLB 14번 호출이 분석 시간
    89초 차지하던 것 제거. value_ko/title_ko는 그대로 — 응답 schema 호환.
    """
    text = todo.text
    category = classify_category(text)

    when = find_when_in_text(text, target_lang)

    what: list[str] = []
    if category == Category.supplies:
        what = split_supply_tokens(text)

    return AnalyzeItem(
        category=category,
        action_hint=todo.action_hint,
        title_ko=text,
        title_translated="",  # NLLB skip — items deprecated, 사용처 없음
        when=when,
        where=None,
        what=what,
        amount=_amount_to_ko(todo.amount),
        deadline=todo.due_date,
        importance=todo.confidence,
    )


def _slot_entry(ko: str, target_lang: str, source: str = "model") -> SlotEntry:
    return SlotEntry(ko=ko, translated=translate_term(ko, target_lang), source=source)


def _build_summary(
    regex_slots: dict[str, list[dict]],
    items: list[AnalyzeItem],
    target_lang: str,
) -> SummarySlots:
    """정규식 슬롯(dates/times/amounts/urls/phones) + items에서 모델 슬롯(supplies/deadlines) 집계."""
    summary = SummarySlots(
        dates=[SlotEntry(**s) for s in regex_slots["dates"]],
        times=[SlotEntry(**s) for s in regex_slots["times"]],
        amounts=[SlotEntry(**s) for s in regex_slots["amounts"]],
        urls=[SlotEntry(**s) for s in regex_slots.get("urls", [])],
        phones=[SlotEntry(**s) for s in regex_slots.get("phones", [])],
    )

    # supplies: category=supplies items의 what 토큰 집계 (중복 제거, 순서 보존)
    supplies: list[SlotEntry] = []
    seen_supplies: set[str] = set()
    for item in items:
        if item.category != Category.supplies:
            continue
        for token in item.what:
            if token in seen_supplies:
                continue
            seen_supplies.add(token)
            supplies.append(_slot_entry(token, target_lang, source="model"))
    summary.supplies = supplies

    # deadlines: items의 deadline 집계
    deadlines: list[SlotEntry] = []
    seen_deadlines: set[str] = set()
    for item in items:
        if not item.deadline or item.deadline in seen_deadlines:
            continue
        seen_deadlines.add(item.deadline)
        deadlines.append(_slot_entry(item.deadline, target_lang, source="model+regex"))
    summary.deadlines = deadlines

    return summary


@router.post("/analyze/{notice_id}", response_model=ApiResponse)
async def analyze_notice(
    notice_id: str,
    req: NoticeAnalyzeRequest,
    user: UserProfile = Depends(require_user),
):
    """수신된 가정통신문 → 슬롯 기반 분석 응답.

    파이프라인:
      [3] 윤정 추출 (binary + 정규식, list[YunjeongTodo])
      [2] 정규식 슬롯 (전체 통신문 단위)
      [4] 경이 6-class 분류 (각 todo.text)
      [5] 슬롯/짧은 문장 번역 (세종)
      [6] AnalyzeItem 결합 + summary 집계
      [7] TTS

    학부모 본인의 가정통신문만 분석 가능. target_language 필수.
    """
    if notice_id not in _notices:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="가정통신문을 찾을 수 없습니다",
        )

    notice = _notices[notice_id]
    if user.role != "parent" or user.user_id != notice.parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 가정통신문만 분석할 수 있습니다",
        )
    target_lang = req.target_language

    # 단계별 시간 측정 — 어디서 시간 잡아먹는지 진단용. 발표 후 logger.info로 낮출 것.
    _t_start = time.time()
    _t_marks: dict[str, float] = {}

    # [2.5a] bbox 기반 구조 재구성 — layout_json 있으면 좌표 기반 행/열 정리
    # (세종님 PR #133). 없으면 업로드 시 저장된 notice.text 그대로 사용.
    analysis_text = _reconstruct_text_from_layout(req.layout_json) or notice.text
    # title 추출은 Vision sentence_list로 덮어씌워지기 전 원본 텍스트에서 — Gemini가
    # sentence_list로 분해해버리면 첫 줄이 메타정보(날짜/담당) 라 윤정 heuristic이 제목 못 잡음.
    original_text = analysis_text
    _t_marks["bbox_recon"] = time.time() - _t_start

    # [2.5b] LLM normalizer — Gemini로 sentence list 추출.
    # Vision 우선 (PDF/이미지 disk 파일 → inlineData 전송) → 표/자간 자연 처리.
    # Vision 미지원 mime(HWP 변환 실패 케이스) 또는 호출 실패 시 text fallback.
    llm_status = "off"
    llm_elapsed = 0.0
    # Gemini가 명시 추출한 document_title (Vision 성공 시) — extract_title 휴리스틱보다 우선.
    gemini_title_override = ""
    if req.use_llm_normalizer:
        structured = None
        # Vision path 시도 — disk에 저장된 원본 파일이 있고 mime이 Vision 지원이면
        if (
            notice.original_file_url
            and notice.mime_type
            and notice.mime_type in VISION_SUPPORTED_MIMES
        ):
            file_name = Path(notice.original_file_url).name
            file_path = NOTICES_DIR / file_name
            if file_path.exists():
                try:
                    raw_bytes = file_path.read_bytes()
                    structured, llm_status, llm_elapsed = extract_sentences(
                        inline_data=(raw_bytes, notice.mime_type),
                    )
                    logger.warning(
                        "[analyze] llm_normalizer Vision: status=%s elapsed=%.2fs "
                        "file=%s mime=%s bytes=%d sentences=%d",
                        llm_status, llm_elapsed, file_name, notice.mime_type,
                        len(raw_bytes),
                        len(structured.get("sentence_list", [])),
                    )
                except Exception as error:
                    logger.warning(
                        "[analyze] Vision file read failed (%s), text fallback",
                        error,
                    )
                    structured = None

        # Vision 성공 → 윤정 input 만들 때 sentence_list를 단순 \n join 하지 말고
        # **section별 paragraph 재조합** — paragraph 흐름 보존이 핵심. 단순 \n join은
        # paragraph context 신호가 사라져 윤정 KoELECTRA가 todo 인식률 급락
        # (Gemini 3 Flash Preview 측정에서 cards 15→3 회귀로 확인).
        # 같은 section sentence들을 한 paragraph로 묶고, paragraph 사이는 \n\n.
        if structured is not None and llm_status == "ok":
            gemini_title_override = (structured.get("document_title") or "").strip()
            sentences = structured.get("sentence_list", [])
            paragraphs: dict[str, list[str]] = {}
            order: list[str] = []
            for s in sentences:
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                section = (s.get("section") or "").strip() or "_default"
                if section not in paragraphs:
                    paragraphs[section] = []
                    order.append(section)
                paragraphs[section].append(text)
            joined = "\n\n".join(" ".join(paragraphs[sec]) for sec in order)
            if joined:
                analysis_text = joined

        # Vision 미시도/실패 → text 기반 extract_sentences로 fallback
        if structured is None or llm_status != "ok":
            normalized, llm_status, llm_elapsed = llm_normalize_text(analysis_text)
            in_len = len(analysis_text)
            out_len = len(normalized)
            head = normalized[:200].replace("\n", " / ")
            tail = normalized[-200:].replace("\n", " / ") if out_len > 200 else ""
            logger.warning(
                "[analyze] llm_normalizer text-fallback: status=%s elapsed=%.2fs "
                "in=%d out=%d head=%r tail=%r",
                llm_status, llm_elapsed, in_len, out_len, head, tail,
            )
            if llm_status == "ok":
                analysis_text = normalized

    _t_marks["llm_normalizer"] = time.time() - _t_start - sum(_t_marks.values())

    # [3] 윤정 추출 → list[YunjeongTodo] (할일 없으면 [])
    try:
        todos = extract_todos(analysis_text)
        if not todos:
            todos = MOCK_TODOS
    except Exception as error:
        logger.warning("[analyze] extractor failed: %s", error)
        todos = MOCK_TODOS
    _t_marks["yunjeong_extract"] = time.time() - _t_start - sum(_t_marks.values())

    # [3'] 제목 추출 — Gemini document_title 우선, 없으면 원본 텍스트(Vision 적용 전)에서
    # 윤정님 PR #90 heuristic. analysis_text는 sentence_list로 덮어씌워졌을 수 있어
    # 첫 줄이 메타정보(날짜/담당) — 휴리스틱이 본문 한 줄을 제목으로 잘못 잡음.
    title_ko = gemini_title_override or extract_title(original_text) or ""
    title_translated = (
        translate_short_sentence(title_ko, target_lang) if title_ko else ""
    )

    # [2] 정규식 슬롯 (전체 통신문 단위, summary 재료)
    regex_slots = extract_summary_regex_slots(analysis_text, target_lang)

    # [4]+[6] items: 각 todo에 경이님 카테고리 + 슬롯 결합 (deprecated, 다음 PR 폐기)
    items = [_build_item(t, target_lang) for t in todos]
    _t_marks["title_items_classify"] = time.time() - _t_start - sum(_t_marks.values())

    # [6] summary 집계: 정규식 + items 모델 슬롯 통합 (deprecated, 다음 PR 폐기)
    summary = _build_summary(regex_slots, items, target_lang)

    # [6'] cards: 신규 슬롯 카드 응답 — 시연 안정성을 위해 상위 N개만 번역/TTS 대상으로 사용.
    top_todos = sorted(todos, key=lambda t: -t.confidence)[:MAX_CARDS]
    cards = build_cards(top_todos, regex_slots, target_lang)[:MAX_CARDS]
    _t_marks["card_build_nllb"] = time.time() - _t_start - sum(_t_marks.values())

    # [6''] highlights: layout_json 있을 때만 카드 ↔ bbox 매칭 — 없으면 빈 리스트.
    # layout_json은 안드 ML Kit OCR JSON 또는 backend pdfplumber probe JSON.
    try:
        highlights = build_highlights_from_cards(cards, req.layout_json)
    except Exception as error:
        logger.warning("[analyze] highlight mapping failed: %s", error)
        highlights = []
    page_count = _page_count_from_layout(req.layout_json)

    # [7] TTS: 두 갈래 — 번역 합본 + 쉬운 한국어 합본 (세종님 별도 버튼 요청)
    tts_text_translated = _build_tts_text_from_cards(cards, "translated")
    tts_text_easy_ko = _build_tts_text_from_cards(cards, "easy_ko")
    try:
        tts_url = await generate_tts_file(tts_text_translated, target_lang=target_lang) if tts_text_translated else ""
    except Exception as error:
        logger.warning("[analyze] TTS (translated) failed: %s", error)
        tts_url = ""
    try:
        tts_url_easy_ko = await generate_tts_file(tts_text_easy_ko, target_lang="ko_easy") if tts_text_easy_ko else ""
    except Exception as error:
        logger.warning("[analyze] TTS (easy_ko) failed: %s", error)
        tts_url_easy_ko = ""
    _t_marks["tts"] = time.time() - _t_start - sum(_t_marks.values())

    _t_total = time.time() - _t_start
    logger.warning(
        "[timing] cards=%d total=%.2fs | bbox=%.2fs llm=%.2fs yunjeong=%.2fs "
        "title_items=%.2fs cards_nllb=%.2fs tts=%.2fs",
        len(cards), _t_total,
        _t_marks.get("bbox_recon", 0),
        _t_marks.get("llm_normalizer", 0),
        _t_marks.get("yunjeong_extract", 0),
        _t_marks.get("title_items_classify", 0),
        _t_marks.get("card_build_nllb", 0),
        _t_marks.get("tts", 0),
    )

    response = {
        "notice_id": notice_id,
        "raw_text": notice.text,
        "target_language": target_lang,
        "page_count": page_count,
        "title": title_ko,
        "title_translated": title_translated,
        "highlights": highlights,
        "cards": [c.model_dump() for c in cards],
        "summary": summary.model_dump(),
        "items": [item.model_dump() for item in items],
        "tts_text": tts_text_translated,
        "tts_url": tts_url,
        "tts_url_easy_ko": tts_url_easy_ko,
        "quality_note": "",
        "review_needed": "",
        "ocr_corrections": [c.model_dump() for c in notice.ocr_corrections],
        "has_review_required": any(c.review_required for c in notice.ocr_corrections),
    }
    return ApiResponse.success(data=response)


def _build_tts_text_from_cards(cards: list[SlotCard], mode: str) -> str:
    """슬롯 카드 → TTS 텍스트 (헤더 + 값 한 줄씩 합본).

    mode="translated": 대상 언어 TTS용 — value_translated + header_translated
    mode="easy_ko":    쉬운 한국어 TTS용 — value_easy_ko + header_ko
    """
    if not cards:
        return ""
    lines: list[str] = []
    for c in cards:
        if mode == "translated":
            header = c.header_translated or c.header_ko
            value = c.value_translated or c.value_ko
        else:  # easy_ko
            header = c.header_ko
            value = c.value_easy_ko or c.value_ko
        if not value:
            continue
        value = strip_markers(value)
        line = f"{header}. {value}" if header else value
        lines.append(line)
    return "\n".join(lines)


def _build_tts_text(
    summary: SummarySlots,
    items: list[AnalyzeItem],
    target_lang: str,
) -> str:
    """items 한 건씩 title + 슬롯 정보를 합쳐 한 문장으로 — 음성 정보량 최대화.

    슬롯 한국어 값(amount/deadline/what)은 summary의 translated 매핑으로 대상 언어 변환.
    정렬은 importance 내림차순. 경이 분리 후엔 action_required="Y" 우선으로 교체 예정.
    """
    if not items:
        return ""

    # 한국어 슬롯 → 대상 언어 매핑 (summary가 이미 translated 보유)
    supply_map = {s.ko: s.translated or s.ko for s in summary.supplies}
    amount_map = {s.ko: s.translated or s.ko for s in summary.amounts}
    deadline_map = {s.ko: s.translated or s.ko for s in summary.deadlines}

    sorted_items = sorted(items, key=lambda i: -i.importance)
    lines: list[str] = []
    for item in sorted_items:
        title = item.title_ko if target_lang == "ko_easy" else item.title_translated
        if not title:
            continue
        # 음성에서 ■ 등 장식 마크업은 노이즈 — TTS 직전 strip
        title = strip_markers(title)
        extras: list[str] = []
        if item.when:        # 이미 target_lang 포맷
            extras.append(item.when)
        if item.what:
            extras.append(", ".join(supply_map.get(w, w) for w in item.what))
        if item.amount:
            extras.append(amount_map.get(item.amount, item.amount))
        if item.deadline:
            extras.append(strip_markers(deadline_map.get(item.deadline, item.deadline)))
        line = title + (". " + ". ".join(extras) if extras else "")
        lines.append(line)
    return "\n".join(lines)
