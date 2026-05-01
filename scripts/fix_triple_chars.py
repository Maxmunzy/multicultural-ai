"""HWP→ODT 변환 시 draw:frame 중복으로 발생하는 3배 글자 아티팩트 정제.

사용:
  python scripts/fix_triple_chars.py <데이터폴더>
  python scripts/fix_triple_chars.py model/extraction/data

변경 내용:
  - 한글 글자 3배+ 중복 제거 (어어어린린린 → 어린)
  - 숫자 3배+ 중복 제거 (222000222666 → 2026)
  - txt 파일 in-place 수정

원인: LibreOffice HWP→ODT 변환 시 일부 파일의 draw:frame(텍스트 상자)
안 텍스트가 본문에 중복 기록됨. backend/app/services/parser.py의
draw:frame 제외 fix 이후 재변환 시에는 발생하지 않음.
"""
import re
import sys
from pathlib import Path

_TRIPLE_KO = re.compile(r'([가-힣])\1{2,}')
_TRIPLE_NUM = re.compile(r'(\d)\1{2,}')


def fix(text: str) -> str:
    text = _TRIPLE_KO.sub(r'\1', text)
    text = _TRIPLE_NUM.sub(r'\1', text)
    return text


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: fix_triple_chars.py <data_dir>")
        sys.exit(1)

    data_dir = Path(sys.argv[1])
    if not data_dir.exists():
        print(f"폴더 없음: {data_dir}")
        sys.exit(1)

    fixed = 0
    skipped = 0
    for txt in sorted(data_dir.rglob("*.txt")):
        try:
            original = txt.read_text(encoding="utf-8", errors="ignore")
            cleaned = fix(original)
            if cleaned != original:
                txt.write_text(cleaned, encoding="utf-8")
                fixed += 1
        except Exception as e:
            print(f"  오류: {txt.name} — {e}")
            skipped += 1

    print(f"완료: {fixed}개 수정 / {skipped}개 오류")


if __name__ == "__main__":
    main()
