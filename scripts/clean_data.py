"""학습 데이터 txt 전체 정제.

처리 항목:
  ① 3배+ 글자 중복 제거 (어어어 → 어)
  ② 2배 글자 중복 제거 (어어 → 어) — 20개+ 발생 시
  ③ 빈/초단 파일 제외 (10자 미만)
  ④ 초대형 파일 제외 (100KB+, 주소 덩어리)
  ⑤ 제목줄 반복 dedup (같은 줄 3회+ → 1회)
  ⑥ 기호 노이즈 연속 제거 (□■▣◆ 5개+)

사용: python clean_data.py <data_dir>
"""
import re
import sys
from pathlib import Path
from collections import Counter

_TRIPLE_KO  = re.compile(r"([가-힣])\1{2,}")
_TRIPLE_NUM = re.compile(r"(\d)\1{2,}")
_DOUBLE_KO  = re.compile(r"([가-힣])\1{1}(?!\1)")
_NOISE      = re.compile(r"[□■▣◆◇○●◎▷◁△▽★☆※]{5,}")
_REPEAT_LN  = re.compile(r"^((.+)\n)(\2\n)+", re.MULTILINE)


def clean(text: str) -> tuple[str, list[str]]:
    applied = []

    # ①② 글자 중복
    t = _TRIPLE_KO.sub(r"\1", text)
    t = _TRIPLE_NUM.sub(r"\1", t)
    if t != text:
        applied.append("3배중복")
        text = t

    doubles = _DOUBLE_KO.findall(text)
    if len(doubles) > 20:
        t = _DOUBLE_KO.sub(r"\1", text)
        if t != text:
            applied.append("2배중복")
            text = t

    # ⑤ 제목줄 반복 dedup
    t = _REPEAT_LN.sub(r"\1", text)
    if t != text:
        applied.append("줄반복")
        text = t

    # ⑥ 기호 노이즈
    t = _NOISE.sub(" ", text)
    if t != text:
        applied.append("기호노이즈")
        text = t

    return text, applied


def should_exclude(text: str) -> str | None:
    if len(text.strip()) < 10:
        return "빈파일"
    if len(text) > 100_000:
        return "초대형"
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: clean_data.py <data_dir>")
        sys.exit(1)

    data_dir = Path(sys.argv[1])
    txts = list(data_dir.rglob("*.txt"))
    print(f"전체: {len(txts)}개")

    stats = Counter()
    excluded = []

    for txt in txts:
        try:
            original = txt.read_text(encoding="utf-8", errors="ignore")

            reason = should_exclude(original)
            if reason:
                txt.unlink()
                stats[f"제외({reason})"] += 1
                excluded.append((reason, txt.name[:50]))
                continue

            cleaned, applied = clean(original)
            if applied:
                txt.write_text(cleaned, encoding="utf-8")
                for a in applied:
                    stats[f"정제({a})"] += 1
            else:
                stats["변경없음"] += 1

        except Exception as e:
            stats["오류"] += 1

    print("\n=== 결과 ===")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}개")

    if excluded:
        print(f"\n제외된 파일 ({len(excluded)}개):")
        for reason, name in excluded[:10]:
            print(f"  [{reason}] {name}")
        if len(excluded) > 10:
            print(f"  ... 외 {len(excluded)-10}개")


if __name__ == "__main__":
    main()
