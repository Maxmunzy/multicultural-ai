import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from app.auth import get_user, require_teacher, require_user
from app.models.schemas import (
    AnalyzeItem, ApiResponse, Category, Notice, NoticeAnalyzeRequest,
    NoticeSendRequest, SlotEntry, SummarySlots, UserProfile, YunjeongTodo,
)
from app.services.extractor import extract_todos
from app.services.translator import translate_short_sentence, translate_term
from app.services.classifier import classify_category
from app.services.tts import generate_tts_file
from app.services.slot_extractor import (
    extract_summary_regex_slots, find_when_in_text,
    split_supply_tokens, strip_markers,
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
def _amount_to_ko(amount: int | None) -> str | None:
    if amount is None:
        return None
    return f"{amount:,}원"


def _build_item(todo: YunjeongTodo, target_lang: str) -> AnalyzeItem:
    """YunjeongTodo + 경이님 카테고리 → AnalyzeItem.

    - category : 경이님 6-class 분류 (주제)
    - action_hint : 윤정님 추출 결과 (행동: 신청/제출/...)
    - due_date / amount : 윤정님 모델 결과 신뢰 (정규식 [2]는 summary 전체 단위 담당)
    - when : 자유텍스트의 일시 표현은 정규식으로 추가 추출
    - what : 준비물 카테고리일 때만 토큰 분해
    - 마크업(■)은 보존, TTS 빌더에서만 strip.
    """
    text = todo.text
    category = classify_category(text)

    when = find_when_in_text(text, target_lang)

    what: list[str] = []
    if category == Category.supplies:
        what = split_supply_tokens(text)

    title_translated = translate_short_sentence(text, target_lang) or text

    return AnalyzeItem(
        category=category,
        action_hint=todo.action_hint,
        title_ko=text,
        title_translated=title_translated,
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

    # [3] 윤정 추출 → list[YunjeongTodo] (할일 없으면 [])
    try:
        todos = extract_todos(notice.text)
        if not todos:
            todos = MOCK_TODOS
    except Exception as error:
        print(f"[analyze] extractor failed: {error}")
        todos = MOCK_TODOS

    # [2] 정규식 슬롯 (전체 통신문 단위, summary 재료)
    regex_slots = extract_summary_regex_slots(notice.text, target_lang)

    # [4]+[6] items: 각 todo에 경이님 카테고리 + 슬롯 결합
    items = [_build_item(t, target_lang) for t in todos]

    # [6] summary 집계: 정규식 + items 모델 슬롯 통합
    summary = _build_summary(regex_slots, items, target_lang)

    # [7] TTS: 슬롯+할일 합쳐 한 문장씩, importance 내림차순
    tts_text = _build_tts_text(summary, items, target_lang)
    try:
        tts_url = await generate_tts_file(tts_text, target_lang=target_lang) if tts_text else ""
    except Exception as error:
        print(f"[analyze] TTS failed: {error}")
        tts_url = ""

    response = {
        "notice_id": notice_id,
        "raw_text": notice.text,
        "target_language": target_lang,
        "summary": summary.model_dump(),
        "items": [item.model_dump() for item in items],
        "tts_text": tts_text,
        "tts_url": tts_url,
        "quality_note": "",
        "review_needed": "",
    }
    return ApiResponse.success(data=response)


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
