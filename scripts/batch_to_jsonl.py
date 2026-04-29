"""txt 폴더를 단일 jsonl 파일로 일괄 변환.

윤정님 스키마: id / source_type / original_text / category / keywords / importance /
              action_required / easy_korean / vietnamese / tts_target

라벨 필드(category/keywords/importance)는 빈 문자열 — 모델이 채울 것.
"""
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 4:
        print("usage: batch_to_jsonl.py <txt_dir> <output.jsonl> <start_id> [source_type]")
        sys.exit(1)

    txt_dir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    start_id = int(sys.argv[3])
    source_type = sys.argv[4] if len(sys.argv) > 4 else "초등학교"

    txt_files = sorted(p for p in txt_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == ".txt")

    if not txt_files:
        print(f"no .txt files in {txt_dir}")
        sys.exit(1)

    skipped = []
    with out_path.open("w", encoding="utf-8") as out:
        for i, txt in enumerate(txt_files):
            text = txt.read_text(encoding="utf-8").strip()
            if not text:
                skipped.append(txt.name)
                continue
            record = {
                "id": start_id + i,
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
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    written = len(txt_files) - len(skipped)
    print(f"wrote: {out_path}")
    print(f"  entries: {written}")
    print(f"  id range: {start_id} ~ {start_id + len(txt_files) - 1}")
    if skipped:
        print(f"  skipped (empty): {len(skipped)}")
        for name in skipped[:5]:
            print(f"    - {name}")


if __name__ == "__main__":
    main()
