"""마지막 잔여 — 성취기준 코드(2수01-01) 포함된 학습목표 todo False 처리."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_todo = sum(1 for r in rows if r.get('is_todo'))

ACHIEVEMENT_RE = re.compile(r'\d+[가-힣]\d+-\d+')  # 성취기준 코드: 2수01-01, 4미02-03 등
changed = []

for i, r in enumerate(rows):
    if not r.get('is_todo'):
        continue
    text = r['text'].strip()
    if ACHIEVEMENT_RE.search(text):
        rows[i]['is_todo'] = False
        changed.append((i, text))

with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

after_todo = sum(1 for r in rows if r.get('is_todo'))
print(f"True→False (성취기준 코드): {len(changed)}건")
for i, t in changed:
    print(f"  {i}: {t[:100]}")
print(f"\nis_todo: {before_todo} → {after_todo}")
