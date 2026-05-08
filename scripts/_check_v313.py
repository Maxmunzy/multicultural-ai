import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
lines = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v3.1.3_dual_labeled.jsonl").read_text("utf-8").splitlines()
sample = [json.loads(l) for l in lines[:3] if l.strip()]
for r in sample:
    print(list(r.keys()), "| is_todo_prob:", r.get("is_todo_prob", "NONE"))
print("총:", len([l for l in lines if l.strip()]))
