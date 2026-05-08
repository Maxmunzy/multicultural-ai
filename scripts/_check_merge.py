import json, sys
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")

merged = [json.loads(l) for l in
    Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v4_merged_train.jsonl")
    .read_text("utf-8").splitlines() if l.strip()]

# 레코드별 키 집합 분포
key_sets = Counter(frozenset(r.keys()) for r in merged)
print("=== 필드 구성 분포 ===")
for keys, cnt in key_sets.most_common():
    print(f"  {cnt:>6}개: {sorted(keys)}")

# v3.1.3 샘플 (label_group != 'v4')
v313 = [r for r in merged if r.get("label_group") != "v4"]
v4   = [r for r in merged if r.get("label_group") == "v4"]
print(f"\nv3.1.3 샘플:")
for r in v313[:2]:
    print(f"  {r}")
print(f"\nv4 샘플:")
for r in v4[:2]:
    print(f"  {r}")
