import json, sys, re
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

src = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v4_clean.jsonl")
dst = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v4_clean.jsonl")

MODEL_RELABEL_MIN_CONF = 0.97

records = [json.loads(l) for l in src.read_text("utf-8").splitlines() if l.strip()]
before_true = sum(1 for r in records if r.get("is_todo"))

reverted = 0
for r in records:
    reason = r.get("label_reason", "")
    if reason.startswith("model_relabel"):
        m = re.search(r"conf=([\d.]+)", reason)
        if m and float(m.group(1)) < MODEL_RELABEL_MIN_CONF:
            r["is_todo"] = False
            reverted += 1

after_true  = sum(1 for r in records if r.get("is_todo"))
after_false = len(records) - after_true

with dst.open("w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"전체:          {len(records)}개")
print(f"재정제 기준:   model_relabel conf < {MODEL_RELABEL_MIN_CONF} → False 전환")
print(f"전환(True→False): {reverted}개")
print(f"is_todo=True : {before_true}개 → {after_true}개 ({after_true/len(records)*100:.1f}%)")
print(f"is_todo=False: {len(records)-before_true}개 → {after_false}개 ({after_false/len(records)*100:.1f}%)")
print(f"저장: {dst}")
