"""Generate MMS-TTS samples for SchoolBridge TTS engine review.

MMS-TTS is evaluated as an optional alternative voice source when Edge-TTS
voices are uncomfortable for some users. Outputs are WAV files.
"""

import argparse
from pathlib import Path

import torch
from scipy.io.wavfile import write as write_wav
from transformers import AutoTokenizer, VitsModel

LANG_CONFIG = {
    "en": {
        "label": "English",
        "model": "facebook/mms-tts-eng",
        "text": "Please submit the application form by tomorrow. Please bring a water bottle and indoor shoes.",
    },
    "ru": {
        "label": "Russian",
        "model": "facebook/mms-tts-rus",
        "text": "Пожалуйста, сдайте заявление до завтра. Подготовьте бутылку воды и сменную обувь.",
    },
    "ms": {
        "label": "Malay",
        "model": "facebook/mms-tts-zlm",
        "text": "Sila hantar borang permohonan sebelum esok. Sila bawa botol air dan kasut dalam bangunan.",
    },
    "mn": {
        "label": "Mongolian",
        "model": "facebook/mms-tts-mon",
        "text": "Маргааш хүртэл өргөдлийн маягтыг өгнө үү. Усны сав болон дотор гутал бэлдэнэ үү.",
    },
    "vi": {
        "label": "Vietnamese",
        "model": "facebook/mms-tts-vie",
        "text": "Vui lòng nộp đơn đăng ký trước ngày mai. Hãy chuẩn bị bình nước và giày đi trong nhà.",
    },
    "zh": {
        "label": "Chinese Mandarin",
        "model": "",
        "text": "请在明天之前提交申请表。请准备水瓶和室内鞋。",
        "note": "No facebook MMS-TTS checkpoint was found for standard Mandarin Chinese.",
    },
    "th": {
        "label": "Thai",
        "model": "facebook/mms-tts-tha",
        "text": "กรุณาส่งใบสมัครภายในวันพรุ่งนี้ และเตรียมขวดน้ำกับรองเท้าใส่ในอาคาร",
    },
    "ja": {
        "label": "Japanese",
        "model": "",
        "text": "明日までに申請書を提出してください。水筒と上履きを準備してください。",
        "note": "No facebook MMS-TTS checkpoint was found for Japanese.",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description="Generate MMS-TTS samples.")
    parser.add_argument("--lang", default="vi", choices=[*LANG_CONFIG.keys(), "all"])
    parser.add_argument("--text", default="", help="Override text. Only valid for a single --lang.")
    parser.add_argument("--output-dir", default="outputs/tts_mms_probe")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    return parser.parse_args()


def resolve_device(device):
    if device == "cuda" and not torch.cuda.is_available():
        print("CUDA is not available. Falling back to CPU.")
        return "cpu"
    return device


def synthesize(lang, text, output_dir, device):
    config = LANG_CONFIG[lang]
    model_name = config.get("model", "")
    if not model_name:
        print(f"[{lang}] skipped: {config.get('note', 'MMS-TTS checkpoint is unavailable.')}")
        return

    text = text or config["text"]
    output_path = output_dir / f"mms_{lang}.wav"

    print(f"[{lang}] loading {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = VitsModel.from_pretrained(model_name).to(device)
    model.eval()

    inputs = tokenizer(text, return_tensors="pt").to(device)
    with torch.no_grad():
        waveform = model(**inputs).waveform.squeeze().detach().cpu().numpy()

    write_wav(output_path, model.config.sampling_rate, waveform)
    print(f"[{lang}] saved={output_path}")


def main():
    args = parse_args()
    if args.lang == "all" and args.text:
        raise ValueError("--text can only be used with a single --lang.")

    device = resolve_device(args.device)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    langs = LANG_CONFIG.keys() if args.lang == "all" else [args.lang]
    for lang in langs:
        synthesize(lang, args.text, output_dir, device)


if __name__ == "__main__":
    main()