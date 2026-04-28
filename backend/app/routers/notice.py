import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from app.auth import get_user, require_teacher, require_user
from app.models.schemas import (
    AnalyzeItem, ApiResponse, Category, Notice, NoticeAnalyzeRequest,
    NoticeSendRequest, SlotEntry, SummarySlots, TodoItem, UserProfile,
)
from app.services.extractor import extract_todos
from app.services.translator import translate_short_sentence, translate_term
from app.services.classifier import review_todos
from app.services.tts import generate_tts_file
from app.services.slot_extractor import (
    extract_summary_regex_slots, find_amount_in_text,
    find_deadline_in_text, find_when_in_text, split_supply_tokens,
)
from app.services.mock import MOCK_TODOS

router = APIRouter()

_notices: dict[str, Notice] = {}


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


# ── 슬롯 기반 응답 빌더 ───────────────────────────────────────────
# 강사 처방(2026-04-28):
#   1. 템플릿 슬롯 출력 (summary)
#   2. 정규식 + 모델 하이브리드 (regex source 표시)
#   3. 핵심 명사(준비물·금액) 누락 가시화 (빈 슬롯 즉시 노출)
def _build_item(todo: TodoItem, target_lang: str) -> AnalyzeItem:
    text = todo.text_ko
    when = find_when_in_text(text, target_lang)
    amount_ko = find_amount_in_text(text, target_lang)
    deadline_ko = find_deadline_in_text(text)

    what: list[str] = []
    if todo.category == Category.supplies:
        what = split_supply_tokens(text)

    # 짧은 문장 번역 실패 시 한국어 원문 fallback (세종님 정책: 안드에 한국어 노출이 NLLB 오역보다 안전).
    title_translated = translate_short_sentence(text, target_lang) or text

    return AnalyzeItem(
        category=todo.category,
        title_ko=text,
        title_translated=title_translated,
        when=when,
        where=None,                # NER 영역 — 추후 윤정님 추출기와 연동
        what=what,
        amount=amount_ko,
        deadline=deadline_ko,
        importance=todo.importance,
    )


def _slot_entry(ko: str, target_lang: str, source: str = "model") -> SlotEntry:
    return SlotEntry(ko=ko, translated=translate_term(ko, target_lang), source=source)


def _build_summary(
    regex_slots: dict[str, list[dict]],
    items: list[AnalyzeItem],
    target_lang: str,
) -> SummarySlots:
    """정규식 슬롯(dates/times/amounts) + items에서 모델 슬롯(supplies/deadlines) 집계."""
    summary = SummarySlots(
        dates=[SlotEntry(**s) for s in regex_slots["dates"]],
        times=[SlotEntry(**s) for s in regex_slots["times"]],
        amounts=[SlotEntry(**s) for s in regex_slots["amounts"]],
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

    파이프라인: 추출(윤정) → 검수(경이) → 정규식 슬롯(태수) → 슬롯 번역(세종) → TTS
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

    # 1. 추출 (윤정 KoELECTRA)
    try:
        todos = extract_todos(notice.text)
        if not todos:
            todos = MOCK_TODOS
    except Exception as error:
        print(f"[analyze] extractor failed: {error}")
        todos = MOCK_TODOS

    # 2. 분류 검수 (경이 모델)
    classifier_review = ""
    try:
        classifier_review = review_todos(todos)
    except Exception as error:
        print(f"[analyze] classifier review failed: {error}")

    # 3. 정규식 슬롯 (태수): notice 원문 → dates/times/amounts (LLM 의존 없는 안전 데이터)
    regex_slots = extract_summary_regex_slots(notice.text, target_lang)

    # 4. items: TodoItem → AnalyzeItem (슬롯 분해 + 짧은 문장 번역)
    items = [_build_item(t, target_lang) for t in todos]

    # 5. summary 집계: 정규식 + 모델 슬롯 통합
    summary = _build_summary(regex_slots, items, target_lang)

    # 6. TTS: 슬롯 카드를 음성으로 (한국어 화자, ko_easy면 한국어 자체)
    #    items title을 줄바꿈 연결 — 강사 지적 가독성 영역이라 1차 단순.
    tts_text = "\n".join(
        item.title_translated if target_lang != "ko_easy" else item.title_ko
        for item in items if item.title_ko
    )
    try:
        tts_url = await generate_tts_file(tts_text, target_lang=target_lang) if tts_text else ""
    except Exception as error:
        print(f"[analyze] TTS failed: {error}")
        tts_url = ""

    # 7. 검수 노트
    review_needed = (
        f"[경이 모델 교차검증]\n{classifier_review}" if classifier_review else ""
    )

    response = {
        "notice_id": notice_id,
        "raw_text": notice.text,
        "target_language": target_lang,
        "summary": summary.model_dump(),
        "items": [item.model_dump() for item in items],
        "tts_url": tts_url,
        "quality_note": "",
        "review_needed": review_needed,
    }
    return ApiResponse.success(data=response)
