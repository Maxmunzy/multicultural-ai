import json, sys
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")

records = [json.loads(l) for l in
    Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v4_clean.jsonl")
    .read_text("utf-8").splitlines() if l.strip()]

true_records = [r for r in records if r.get("is_todo")]

# 라벨 이유별 분류
reason_counter = Counter(r.get("label_reason", "unknown") for r in true_records)
print(f"=== True 문장 총 {len(true_records)}개 ===\n")
print("라벨 이유 분포:")
for reason, cnt in reason_counter.most_common():
    print(f"  {reason:<40} {cnt:>5}개")

# model_relabel vs 규칙 기반 분리
rule_true   = [r for r in true_records if not r.get("label_reason","").startswith("model_relabel")]
model_true  = [r for r in true_records if r.get("label_reason","").startswith("model_relabel")]
print(f"\n규칙 기반 True: {len(rule_true)}개")
print(f"모델 relabel True: {len(model_true)}개")

# 규칙 기반 샘플 20개
import random
random.seed(42)
print("\n--- 규칙 기반 True 샘플 20개 ---")
for r in random.sample(rule_true, min(20, len(rule_true))):
    print(f"  [{r.get('label_reason','?'):<25}] {r['text'][:70]}")

# 모델 relabel 샘플 30개 (의심 대상)
print("\n--- model_relabel True 샘플 30개 ---")
for r in random.sample(model_true, min(30, len(model_true))):
    conf = r.get("label_reason","")
    print(f"  [{conf:<35}] {r['text'][:70]}")
