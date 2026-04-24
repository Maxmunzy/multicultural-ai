from fastapi import APIRouter
from pydantic import BaseModel
from app.models.schemas import ApiResponse, KoreanLevel, NoticeUploadResponse

router = APIRouter()


class NoticeRequest(BaseModel):
    user_id: str
    text: str
    level: KoreanLevel = KoreanLevel.beginner


@router.post("/analyze", response_model=ApiResponse)
async def analyze_notice(req: NoticeRequest):
    """가정통신문 텍스트 입력 → 할 일 체크리스트 반환."""
    result = NoticeUploadResponse(raw_text=req.text, todos=[])
    return ApiResponse.success(data=result)
