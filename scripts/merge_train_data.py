"""
merge_train_data.py
===================
v3.1.3_dual_labeled.jsonl + v4_clean.jsonl → v4_merged_train.jsonl

v4 데이터에 소프트 라벨(is_todo_prob) 부여:
  - model_relabel(conf=X) True  → is_todo_prob = X (모델 확신도 그대로)
  - 규칙 기반 True              → is_todo_prob = 0.90
  - False                       → is_todo_prob = 0.05
"""
import json, re, sys
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
V313 = ROOT / "model/extraction/data/train/v3.1.3_dual_labeled.jsonl"
V4   = ROOT / "model/extraction/data/train/v4_clean.jsonl"
OUT  = ROOT / "model/extraction/data/train/v4_merged_train.jsonl"

# v3.1.3 로드 (소프트 라벨 그대로)
v313_records = [json.loads(l) for l in V313.read_text("utf-8").splitlines() if l.strip()]

# v4_clean 로드 + 소프트 라벨 부여
v4_records = []
for r in [json.loads(l) for l in V4.read_text("utf-8").splitlines() if l.strip()]:
    reason = r.get("label_reason", "")
    is_todo = r.get("is_todo", False)

    if is_todo:
        m = re.search(r"conf=([\d.]+)", reason)
        if m:
            prob = float(m.group(1))   # 모델 확신도
        else:
            prob = 0.90                # 규칙 기반 True
    else:
        prob = 0.05                    # False

    v4_records.append({
        "text":         r["text"],
        "is_todo":      is_todo,
        "is_todo_prob": prob,
        "is_title":     r.get("is_title", False),
        "label_group":  "v4",
    })

merged = v313_records + v4_records

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", encoding="utf-8") as f:
    for r in merged:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# 통계
all_probs = [r.get("is_todo_prob", float(r.get("is_todo", False))) for r in merged]
true_cnt  = sum(1 for r in merged if r.get("is_todo"))
print(f"v3.1.3 : {len(v313_records):>6}개")
print(f"v4     : {len(v4_records):>6}개")
print(f"합계   : {len(merged):>6}개")
print(f"is_todo=True : {true_cnt}개 ({true_cnt/len(merged)*100:.1f}%)")
print(f"is_todo=False: {len(merged)-true_cnt}개 ({(len(merged)-true_cnt)/len(merged)*100:.1f}%)")
prob_dist = Counter(round(p, 2) for p in all_probs)
print("\nis_todo_prob 분포:")
for p in sorted(prob_dist):
    print(f"  p={p:.2f}: {prob_dist[p]:>5}개")
print(f"\n저장: {OUT}")
