import uuid
from fastapi import APIRouter
from app.models.schemas import (
    ApiResponse, Notice, NoticeAnalyzeResponse,
    NoticeSendRequest,
)
from app.services.mock import (
    MOCK_TODOS, MOCK_EASY_KO, MOCK_VI_TEXT,
    MOCK_QUALITY_NOTE, MOCK_REVIEW_NEEDED,
)
from app.services.tts import generate_tts_file

router = APIRouter()

# 임시 인메모리 저장소 (추후 DB 교체)
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


@router.post("/analyze/{notice_id}", response_model=ApiResponse)
async def analyze_notice(notice_id: str):
    """수신된 가정통신문 → 분석 결과 + 실시간 베트남어 TTS 생성."""
    if notice_id not in _notices:
        return ApiResponse.error(message="가정통신문을 찾을 수 없습니다")

    notice = _notices[notice_id]

    # 추출/분류는 아직 mock, 번역도 mock 사용. TTS만 실시간 Edge-TTS로 생성.
    try:
        tts_url = await generate_tts_file(MOCK_VI_TEXT)
    except Exception as error:
        tts_url = ""
        print(f"[TTS error] {error}")

    result = NoticeAnalyzeResponse(
        notice_id=notice_id,
        raw_text=notice.text,
        todos=MOCK_TODOS,
        easy_ko_text=MOCK_EASY_KO,
        vi_text=MOCK_VI_TEXT,
        quality_note=MOCK_QUALITY_NOTE,
        review_needed=MOCK_REVIEW_NEEDED,
        tts_url=tts_url,
    )
    return ApiResponse.success(data=result)
