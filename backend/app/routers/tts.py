from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.models.schemas import TTSRequest

router = APIRouter()


@router.post("/generate")
async def generate_tts(req: TTSRequest):
    """
    할 일 목록 → 음성 파일 생성.
    Edge-TTS 연결은 services/tts.py 에 붙일 예정.
    """
    return JSONResponse({"message": "TTS 연결 전", "user_id": req.user_id})
