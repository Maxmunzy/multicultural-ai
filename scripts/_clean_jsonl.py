import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

src  = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v4_relabeled.jsonl")
dst  = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\data\train\v4_clean.jsonl")
MIN_LEN = 10

records = [json.loads(l) for l in src.read_text("utf-8").splitlines() if l.strip()]
before = len(records)

# 짧은 문장 제거
records = [r for r in records if len(r["text"]) >= MIN_LEN]
after_short = len(records)

# 중복 제거 — 같은 text 여러 개면 is_todo=True 우선 보존
seen: dict[str, dict] = {}
for r in records:
    text = r["text"]
    if text not in seen:
        seen[text] = r
    else:
        # True가 있으면 True를 유지
        if r.get("is_todo") and not seen[text].get("is_todo"):
            seen[text] = r

records = list(seen.values())
after_dedup = len(records)

dst.parent.mkdir(parents=True, exist_ok=True)
with dst.open("w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

true_cnt  = sum(1 for r in records if r.get("is_todo"))
false_cnt = len(records) - true_cnt
print(f"원본:          {before:>6}개")
print(f"len<10 제거:   {before - after_short:>6}개  →  {after_short}개 남음")
print(f"중복 제거:     {after_short - after_dedup:>6}개  →  {after_dedup}개 남음")
print(f"is_todo=True : {true_cnt}개 ({true_cnt/len(records)*100:.1f}%)")
print(f"is_todo=False: {false_cnt}개 ({false_cnt/len(records)*100:.1f}%)")
print(f"저장: {dst}")
