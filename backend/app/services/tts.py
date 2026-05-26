import hashlib
import re
import wave
from pathlib import Path

import edge_tts
import numpy as np

TTS_ENGINE_EDGE = "edge"
TTS_ENGINE_MMS_MALE = "mms_male"

# Android language code -> Edge-TTS voice.
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

# MMS-TTS checkpoints currently verified for the demo language set.
# Chinese/Japanese standard checkpoints were not available in the probe.
MMS_LANG_TO_MODEL = {
    "vi": "facebook/mms-tts-vie",
    "en": "facebook/mms-tts-eng",
    "ru": "facebook/mms-tts-rus",
    "ms": "facebook/mms-tts-zlm",
    "mn": "facebook/mms-tts-mon",
    "th": "facebook/mms-tts-tha",
}

STATIC_DIR = Path("/app/static/tts")
STATIC_DIR.mkdir(parents=True, exist_ok=True)


async def generate_tts_file(
    text: str,
    target_lang: str = "vi",
    tts_engine: str = TTS_ENGINE_EDGE,
) -> str:
    """Generate a TTS file and return an Android-playable static path.

    Edge-TTS remains the MVP default. MMS-TTS is an A/B candidate for users
    who prefer the alternative voice. Unsupported MMS languages fall back to
    Edge so the demo does not break.
    """
    if not text or not text.strip():
        return ""

    if tts_engine == TTS_ENGINE_MMS_MALE and target_lang in MMS_LANG_TO_MODEL:
        return await _generate_mms_tts_file(text, target_lang)

    if tts_engine == TTS_ENGINE_MMS_MALE:
        print(f"[tts] MMS unavailable for lang={target_lang}; fallback to Edge-TTS")
    return await _generate_edge_tts_file(text, target_lang)


async def _generate_edge_tts_file(text: str, target_lang: str) -> str:
    voice = LANG_TO_VOICE.get(target_lang)
    if not voice:
        print(f"[tts] no voice for lang={target_lang}")
        return ""

    cache_key = hashlib.sha256(
        f"edge\n{target_lang}\n{voice}\n{text.strip()}".encode("utf-8")
    ).hexdigest()[:24]
    safe_lang = re.sub(r"[^a-zA-Z0-9_-]", "_", target_lang)
    filename = f"{safe_lang}-{cache_key}.mp3"
    out_path = STATIC_DIR / filename
    if out_path.exists() and out_path.stat().st_size > 0:
        return f"/static/tts/{filename}"

    try:
        await edge_tts.Communicate(text=text, voice=voice).save(str(out_path))
    except Exception as error:
        print(f"[tts] Edge generation failed for lang={target_lang}: {error}")
        try:
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
        except Exception:
            pass
        return ""
    return f"/static/tts/{filename}"


async def _generate_mms_tts_file(text: str, target_lang: str) -> str:
    model_name = MMS_LANG_TO_MODEL[target_lang]
    cache_key = hashlib.sha256(
        f"mms_male\n{target_lang}\n{model_name}\n{text.strip()}".encode("utf-8")
    ).hexdigest()[:24]
    safe_lang = re.sub(r"[^a-zA-Z0-9_-]", "_", target_lang)
    filename = f"{safe_lang}-mms-{cache_key}.wav"
    out_path = STATIC_DIR / filename
    if out_path.exists() and out_path.stat().st_size > 0:
        return f"/static/tts/{filename}"

    try:
        import torch
        from transformers import AutoTokenizer, VitsModel

        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = VitsModel.from_pretrained(model_name)
        model.eval()

        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = model(**inputs).waveform.squeeze().detach().cpu().numpy()

        _write_wav(out_path, waveform, model.config.sampling_rate)
    except Exception as error:
        print(f"[tts] MMS generation failed for lang={target_lang}: {error}")
        try:
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
        except Exception:
            pass
        return await _generate_edge_tts_file(text, target_lang)
    return f"/static/tts/{filename}"


def _write_wav(path: Path, waveform: np.ndarray, sample_rate: int) -> None:
    waveform = np.asarray(waveform, dtype=np.float32)
    waveform = np.clip(waveform, -1.0, 1.0)
    pcm = (waveform * 32767).astype(np.int16)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
