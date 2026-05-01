"""정제 후 데이터 품질 심층 검증."""
import re
from pathlib import Path
from collections import Counter
import random

tmp = Path("/app/external_data/raw/tmp")
txts = list(tmp.rglob("*.txt"))
random.seed(42)

_TRIPLE    = re.compile(r"([가-힣\d])\1{2,}")
_DOUBLE_KO = re.compile(r"([가-힣])\1{1}(?!\1)")
_NOISE     = re.compile(r"[□■▣◆◇○●◎▷◁△▽★☆※]{5,}")
_REPEAT_LN = re.compile(r"^(.{5,})\n\1\n\1", re.MULTILINE)
_HAN_RATIO = re.compile(r"[가-힣]")

issues = Counter()
bad_files = []

for txt in txts:
    try:
        text = txt.read_text(encoding="utf-8", errors="ignore")
        name = txt.name[:55]
        found = []

        if _TRIPLE.search(text):
            found.append("3배중복 잔재")
        if len(_DOUBLE_KO.findall(text)) > 20:
            found.append("2배중복 잔재")
        if _REPEAT_LN.search(text):
            found.append("줄반복 잔재")
        if _NOISE.search(text):
            found.append("기호노이즈 잔재")
        if len(text.strip()) < 10:
            found.append("빈파일 잔재")
        if len(text) > 100_000:
            found.append("초대형 잔재")

        # 한글 비율 체크
        hangul = len(_HAN_RATIO.findall(text))
        if hangul / max(len(text), 1) < 0.2:
            found.append("한글비율낮음(20%미만)")

        # 너무 짧은 파일 (10-30자)
        if 10 <= len(text.strip()) <= 30:
            found.append("초단문(10-30자)")

        if found:
            for f in found:
                issues[f] += 1
            bad_files.append((found, name, text[:80]))

    except Exception as e:
        issues["읽기오류"] += 1

# 랜덤 샘플 10개 확인
print("=== 정상 파일 랜덤 샘플 10개 ===")
normal = [t for t in txts if t not in [Path(b[1]) for b in bad_files]]
samples = random.sample(txts, min(10, len(txts)))
for s in samples:
    text = s.read_text(encoding="utf-8", errors="ignore")
    print(f"  [{len(text)}자] {s.name[:40]} | {text[:50].strip()!r}")

print(f"\n=== 검증 결과: 전체 {len(txts)}개 ===")
if not issues:
    print("  ✅ 이상 없음")
else:
    for k, v in sorted(issues.items(), key=lambda x: -x[1]):
        print(f"  ⚠️  {k}: {v}개")
    print(f"\n문제 파일 샘플 (최대 5개):")
    for found, name, preview in bad_files[:5]:
        print(f"  [{', '.join(found)}] {name}")
        print(f"    {preview[:60]!r}")
