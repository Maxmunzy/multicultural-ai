import json
from pathlib import Path
lines = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v4_relabeled.jsonl").read_text("utf-8").splitlines()
records = [json.loads(l) for l in lines if l.strip()]
lengths = [len(r["text"]) for r in records]
print(f"전체: {len(records)}개")
print(f"len<5:  {sum(1 for l in lengths if l < 5)}개")
print(f"len<10: {sum(1 for l in lengths if l < 10)}개")
print(f"len<15: {sum(1 for l in lengths if l < 15)}개")
texts = [r["text"] for r in records]
print(f"중복:   {len(texts) - len(set(texts))}개")
print("len<10 샘플:", [r["text"] for r in records if len(r["text"]) < 10][:15])
