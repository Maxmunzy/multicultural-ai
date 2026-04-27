import uuid
from pathlib import Path

import edge_tts

# 안드 언어 코드 → Edge-TTS voice
LANG_TO_VOICE = {
    "vi": "vi-VN-HoaiMyNeural",
    "en": "en-US-JennyNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ms": "ms-MY-YasminNeural",
    "mn": "mn-MN-YesuiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "th": "th-TH-PremwadeeNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko_easy": "ko-KR-SunHiNeural",
}

STATIC_DIR = Path("/app/static/tts")
STATIC_DIR.mkdir(parents=True, exist_ok=True)


async def generate_tts_file(text: str, target_lang: str = "vi") -> str:
    """선택 언어의 텍스트 → mp3 파일 생성. 안드가 BASE_URL과 합쳐 재생할 상대 경로 반환."""
    if not text or not text.strip():
        return ""
    voice = LANG_TO_VOICE.get(target_lang)
    if not voice:
        print(f"[tts] no voice for lang={target_lang}")
        return ""
    filename = f"{uuid.uuid4()}.mp3"
    out_path = STATIC_DIR / filename
    try:
        await edge_tts.Communicate(text=text, voice=voice).save(str(out_path))
    except Exception as error:
        print(f"[tts] generation failed for lang={target_lang}: {error}")
        return ""
    return f"/static/tts/{filename}"
