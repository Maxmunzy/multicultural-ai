import re
from pathlib import Path
from collections import Counter

tmp = Path("/app/external_data/raw/tmp")
txts = list(tmp.rglob("*.txt"))

_TRIPLE    = re.compile(r"([가-힣\d])\1{2,}")
_DOUBLE_KO = re.compile(r"([가-힣])\1{1}(?!\1)")  # 2배 (3배 아닌)
_NOISE     = re.compile(r"[□■▣◆◇○●◎▷◁△▽★☆※]{5,}")  # 기호 5개+ 연속
_REPEAT_LINE = re.compile(r"^(.{5,})\n\1\n\1", re.MULTILINE)  # 같은 줄 3번 반복

issues = Counter()
samples = {}

for txt in txts:
    try:
        text = txt.read_text(encoding="utf-8", errors="ignore")
        name = txt.name[:50]

        # 3배+ 글자 중복
        if _TRIPLE.search(text):
            issues["① 3배+ 글자 중복"] += 1
            if "①" not in samples:
                samples["①"] = name

        # 2배 글자 중복 (3배 아닌 것만)
        if not _TRIPLE.search(text) and _DOUBLE_KO.search(text):
            # 실제 2배인지 확인 (단어 내 반복 한글이 많으면)
            doubles = _DOUBLE_KO.findall(text)
            if len(doubles) > 20:
                issues["② 2배 글자 중복 의심"] += 1
                if "②" not in samples:
                    samples["②"] = name

        # 빈/초단
        if len(text.strip()) < 10:
            issues["③ 빈/초단(10자미만)"] += 1
            if "③" not in samples:
                samples["③"] = (name, repr(text.strip()))

        # 초대형
        if len(text) > 100_000:
            issues["④ 초대형(100KB+)"] += 1
            if "④" not in samples:
                samples["④"] = (name, f"{len(text)//1000}KB")

        # 제목 줄 반복 (헤더 중복)
        if _REPEAT_LINE.search(text):
            issues["⑤ 제목줄 3회+ 반복"] += 1
            if "⑤" not in samples:
                samples["⑤"] = name

        # 기호 노이즈 (□■▣ 5개+)
        if _NOISE.search(text):
            issues["⑥ 기호 노이즈 연속"] += 1

    except Exception:
        issues["⑦ 읽기 오류"] += 1

print(f"전체: {len(txts)}개\n")
print("=== 오류 현황 (중복 포함) ===")
for k, v in sorted(issues.items()):
    pct = v / len(txts) * 100
    key = k[0]
    s = samples.get(key, "")
    sample_str = f" | 예: {s}" if s else ""
    print(f"  {k}: {v}개 ({pct:.1f}%){sample_str}")
