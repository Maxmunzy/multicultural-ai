"""pdfplumber 텍스트를 윤정님 jsonl 스키마로 변환.

스키마: id / source_type / original_text / category / keywords / importance /
       action_required / easy_korean / vietnamese / tts_target

- original_text는 \n을 공백으로 치환하고 다중 공백 정리
- 라벨 필드(category/keywords/importance)는 빈 문자열 (모델이 채울 것)
"""
import json
import re
import sys
from pathlib import Path


def normalize(text: str) -> str:
    text = text.replace("\x00", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def main():
    if len(sys.argv) < 4:
        print("usage: txt_to_jsonl.py <input.txt> <output.jsonl> <id> [source_type]")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    entry_id = int(sys.argv[3])
    source_type = sys.argv[4] if len(sys.argv) > 4 else "초등학교"

    text = normalize(src.read_text(encoding="utf-8"))

    record = {
        "id": entry_id,
        "source_type": source_type,
        "original_text": text,
        "category": "",
        "keywords": "",
        "importance": "",
        "action_required": "",
        "easy_korean": "",
        "vietnamese": "",
        "tts_target": "",
    }

    line = json.dumps(record, ensure_ascii=False) + "\n"
    dst.write_text(line, encoding="utf-8")
    print(f"wrote: {dst}")
    print(f"  id={entry_id}, source_type={source_type}, chars={len(text)}")


if __name__ == "__main__":
    main()
