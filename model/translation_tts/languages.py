"""언어별 NLLB target code 및 Edge-TTS voice 매핑."""

LANGUAGES = {
    "easy_ko": {
        "label": "쉬운 한국어",
        "nllb_code": None,          # 번역 없음, easy_korean() 결과 그대로 사용
        "tts_voice": "ko-KR-SunHiNeural",
    },
    "en": {
        "label": "영어",
        "nllb_code": "eng_Latn",
        "tts_voice": "en-US-JennyNeural",
    },
    "ru": {
        "label": "러시아어",
        "nllb_code": "rus_Cyrl",
        "tts_voice": "ru-RU-SvetlanaNeural",
    },
    "ms": {
        "label": "말레이시아어",
        "nllb_code": "zsm_Latn",
        "tts_voice": "ms-MY-YasminNeural",
    },
    "mn": {
        "label": "몽골어",
        "nllb_code": "khk_Cyrl",
        "tts_voice": "mn-MN-YesuiNeural",
    },
    "vi": {
        "label": "베트남어",
        "nllb_code": "vie_Latn",
        "tts_voice": "vi-VN-HoaiMyNeural",
    },
    "zh": {
        "label": "중국어",
        "nllb_code": "zho_Hans",
        "tts_voice": "zh-CN-XiaoxiaoNeural",
    },
    "th": {
        "label": "태국어",
        "nllb_code": "tha_Thai",
        "tts_voice": "th-TH-PremwadeeNeural",
    },
    "ja": {
        "label": "일본어",
        "nllb_code": "jpn_Jpan",
        "tts_voice": "ja-JP-NanamiNeural",
    },
}

DEFAULT_LANGUAGE = "vi"
