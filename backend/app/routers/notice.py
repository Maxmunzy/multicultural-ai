import uuid
from fastapi import APIRouter
from app.models.schemas import (
    ApiResponse, Notice, NoticeAnalyzeRequest,
    NoticeSendRequest,
)
from app.services.extractor import extract_todos
from app.services.translator import translate_and_review
from app.services.classifier import review_todos
from app.services.tts import generate_tts_file
from app.services.mock import (
    MOCK_TODOS, MOCK_EASY_KO, MOCK_VI_TEXT,
    MOCK_QUALITY_NOTE, MOCK_REVIEW_NEEDED,
)

router = APIRouter()

_notices: dict[str, Notice] = {}


@router.post("/send", response_model=ApiResponse)
async def send_notice(req: NoticeSendRequest):
    """선생님이 가정통신문 발송 → 부모 수신함에 저장."""
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
async def get_inbox(parent_id: str):
    """부모가 수신된 가정통신문 목록 조회."""
    inbox = [n for n in _notices.values() if n.parent_id == parent_id]
    return ApiResponse.success(data=inbox)


@router.delete("/inbox/{parent_id}", response_model=ApiResponse)
async def clear_inbox(parent_id: str):
    """parent_id 수신함 초기화 (시연용)."""
    targets = [nid for nid, n in _notices.items() if n.parent_id == parent_id]
    for nid in targets:
        del _notices[nid]
    return ApiResponse.success(
        data={"deleted": len(targets)},
        message=f"{parent_id} 수신함 {len(targets)}개 삭제",
    )


@router.post("/analyze/{notice_id}", response_model=ApiResponse)
async def analyze_notice(
    notice_id: str,
    req: NoticeAnalyzeRequest = NoticeAnalyzeRequest(),
):
    """수신된 가정통신문 → 추출(윤정) + 검수(경이) + 번역(세종) + TTS 통합."""
    if notice_id not in _notices:
        return ApiResponse.error(message="가정통신문을 찾을 수 없습니다")

    notice = _notices[notice_id]
    target_lang = req.target_language or "vi"

    # 1. 추출 (윤정 KoELECTRA): raw_text → todos[]
    try:
        todos = extract_todos(notice.text)
        if not todos:
            todos = MOCK_TODOS
    except Exception as error:
        print(f"[analyze] extractor failed: {error}")
        todos = MOCK_TODOS

    # 2. 분류 검수 (경이 모델): 윤정 todos를 재평가
    classifier_review = ""
    try:
        classifier_review = review_todos(todos)
    except Exception as error:
        print(f"[analyze] classifier review failed: {error}")

    # 3. 번역 + 검수 (세종 NLLB + glossary): raw_text → easy_ko + translation
    try:
        review = translate_and_review(notice.text, target_lang=target_lang)
        easy_ko_text = review["easy_ko_text"] or MOCK_EASY_KO
        translation = review["translation"]
        vi_text = review["vi_text"]
        quality_note = review["quality_note"] or MOCK_QUALITY_NOTE
        review_needed = review["review_needed"] or MOCK_REVIEW_NEEDED
    except Exception as error:
        print(f"[analyze] translator failed: {error}")
        easy_ko_text = MOCK_EASY_KO
        translation = MOCK_VI_TEXT if target_lang == "vi" else ""
        vi_text = MOCK_VI_TEXT if target_lang == "vi" else ""
        quality_note = MOCK_QUALITY_NOTE
        review_needed = MOCK_REVIEW_NEEDED

    # 경이 검수 결과를 review_needed에 합침
    if classifier_review:
        review_needed = (
            f"{review_needed}\n\n[경이 모델 교차검증]\n{classifier_review}".strip()
            if review_needed
            else f"[경이 모델 교차검증]\n{classifier_review}"
        )

    # 4. TTS (Edge-TTS): 선택 언어 음성 → mp3
    # ko_easy면 easy_ko_text 한국어 음성, 그 외엔 translation 해당 언어 음성
    tts_text = easy_ko_text if target_lang == "ko_easy" else translation
    try:
        tts_url = await generate_tts_file(tts_text, target_lang=target_lang) if tts_text else ""
    except Exception as error:
        print(f"[analyze] TTS failed: {error}")
        tts_url = ""

    # 안드 호환: target_language별 동적 키 (en_text, ru_text, vi_text 등)
    response = {
        "notice_id": notice_id,
        "raw_text": notice.text,
        "todos": [t.model_dump() for t in todos],
        "easy_ko_text": easy_ko_text,
        "vi_text": vi_text,
        "translation": translation,
        "target_language": target_lang,
        "quality_note": quality_note,
        "review_needed": review_needed,
        "tts_url": tts_url,
    }
    if target_lang not in ("vi", "ko_easy") and translation:
        response[f"{target_lang}_text"] = translation

    return ApiResponse.success(data=response)
