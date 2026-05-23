"""Generate short Edge-TTS voice samples for demo review.

This script is intentionally separate from the MVP pipeline so voice/rate
experiments do not require running NLLB translation.
"""

import argparse
import asyncio
from pathlib import Path

import edge_tts

from languages import DEFAULT_LANGUAGE, LANGUAGES

DEFAULT_TEXT = {
    "easy_ko": "내일까지 신청서를 제출해 주세요. 준비물은 물병과 실내화입니다.",
    "en": "Please submit the application form by tomorrow. Please bring a water bottle and indoor shoes.",
    "ru": "Пожалуйста, сдайте заявление до завтра. Подготовьте бутылку воды и сменную обувь.",
    "ms": "Sila hantar borang permohonan sebelum esok. Sila bawa botol air dan kasut dalam bangunan.",
    "mn": "Маргааш хүртэл өргөдлийн маягтыг өгнө үү. Усны сав болон дотор гутал бэлдэнэ үү.",
    "vi": "Vui lòng nộp đơn đăng ký trước ngày mai. Hãy chuẩn bị bình nước và giày đi trong nhà.",
    "zh": "请在明天之前提交申请表。请准备水瓶和室内鞋。",
    "th": "กรุณาส่งใบสมัครภายในวันพรุ่งนี้ และเตรียมขวดน้ำกับรองเท้าใส่ในอาคาร",
    "ja": "明日までに申請書を提出してください。水筒と上履きを準備してください。",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Generate Edge-TTS voice samples.")
    parser.add_argument("--lang", default=DEFAULT_LANGUAGE, choices=list(LANGUAGES.keys()))
    parser.add_argument("--voice", default="", help="Override Edge-TTS voice name.")
    parser.add_argument("--text", default="", help="Text to synthesize. Defaults to a short school notice sample.")
    parser.add_argument("--rate", default="-12%", help="Speaking rate, e.g. -15%, -12%, +0%.")
    parser.add_argument("--volume", default="+0%", help="Volume, e.g. +0%, +10%.")
    parser.add_argument("--pitch", default="-2Hz", help="Pitch, e.g. -5Hz, -2Hz, +0Hz.")
    parser.add_argument("--output", default="", help="Output mp3 path.")
    return parser.parse_args()


async def synthesize(text, voice, output, rate, volume, pitch):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )
    await communicate.save(str(output))


def main():
    args = parse_args()
    config = LANGUAGES[args.lang]
    voice = args.voice or config["tts_voice"]
    text = args.text or DEFAULT_TEXT[args.lang]
    output = Path(args.output or f"outputs/tts_voice_probe/comfort_{args.lang}.mp3")
    output.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(synthesize(text, voice, output, args.rate, args.volume, args.pitch))
    print(f"saved={output}")
    print(f"lang={args.lang} voice={voice} rate={args.rate} volume={args.volume} pitch={args.pitch}")


if __name__ == "__main__":
    main()