import uuid
from pathlib import Path

import edge_tts

VOICE_VI = "vi-VN-HoaiMyNeural"
STATIC_DIR = Path("/app/static/tts")
STATIC_DIR.mkdir(parents=True, exist_ok=True)


async def generate_tts_file(text: str, voice: str = VOICE_VI) -> str:
    """베트남어 텍스트 → mp3 파일 생성. 안드가 BASE_URL과 합쳐 재생할 상대 경로 반환."""
    if not text or not text.strip():
        return ""
    filename = f"{uuid.uuid4()}.mp3"
    out_path = STATIC_DIR / filename
    await edge_tts.Communicate(text=text, voice=voice).save(str(out_path))
    return f"/static/tts/{filename}"
