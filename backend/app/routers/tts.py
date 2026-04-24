from fastapi import APIRouter
from app.models.schemas import ApiResponse, TTSRequest

router = APIRouter()


@router.post("/generate", response_model=ApiResponse)
async def generate_tts(req: TTSRequest):
    """할 일 목록 → 음성 파일 생성. Edge-TTS 연결은 services/tts.py 에 붙일 예정."""
    return ApiResponse.success(message="TTS 연결 전")
