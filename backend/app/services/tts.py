import uuid
from pathlib import Path

import edge_tts

VOICE_VI = "vi-VN-HoaiMyNeural"
STATIC_DIR = Path("/app/static/tts")
STATIC_DIR.mkdir(parents=True, exist_ok=True)


async def generate_tts_file(text: str, voice: str = VOICE_VI) -> str:
    """Generate a Vietnamese mp3 file and return the relative static URL."""
    if not text or not text.strip():
        return ""
    filename = f"{uuid.uuid4()}.mp3"
    out_path = STATIC_DIR / filename
    await edge_tts.Communicate(text=text, voice=voice).save(str(out_path))
    return f"/static/tts/{filename}"
