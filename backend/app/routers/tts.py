from fastapi import APIRouter

from app.models.schemas import ApiResponse, TTSRequest
from app.services.tts import generate_tts_file

router = APIRouter()


@router.post("/generate", response_model=ApiResponse)
async def generate_tts(req: TTSRequest):
    """할 일 목록 → 베트남어 음성 파일 생성. 안드는 응답 url을 BASE_URL과 합쳐 재생."""
    text = "\n".join(item.text_vi for item in req.todo_items if item.text_vi)
    if not text.strip():
        return ApiResponse.error(message="베트남어 텍스트가 비어 있습니다")
    try:
        url = await generate_tts_file(text)
    except Exception as error:
        return ApiResponse.error(message=f"TTS 생성 실패: {error}")
    return ApiResponse.success(data={"tts_url": url})
