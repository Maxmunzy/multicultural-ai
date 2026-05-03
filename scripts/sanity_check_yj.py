"""윤정님 sample.jsonl과 우리 v3_dual_labeled.jsonl 라벨 일치 검증."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

with open('model/extraction/data/label_sample.jsonl', encoding='utf-8') as f:
    yj = [json.loads(l) for l in f if l.strip()]

with open('model/extraction/data/v3_dual_labeled.jsonl', encoding='utf-8') as f:
    ours = [json.loads(l) for l in f if l.strip()]

# text → label 맵
ours_map = {r['text'].strip(): r for r in ours}

print(f"윤정님 sample: {len(yj)}행")
print(f"우리 데이터: {len(ours)}행\n")

match_total = 0
mismatch_todo = []
mismatch_title = []
not_found = []

for r in yj:
    text = r['text'].strip()
    yj_todo = r.get('is_todo', False)
    yj_title = r.get('is_title', False)

    if text not in ours_map:
        not_found.append((text, yj_todo, yj_title))
        continue

    our = ours_map[text]
    our_todo = our.get('is_todo', False)
    our_title = our.get('is_title', False)

    if yj_todo == our_todo and yj_title == our_title:
        match_total += 1
    else:
        if yj_todo != our_todo:
            mismatch_todo.append((text, yj_todo, our_todo))
        if yj_title != our_title:
            mismatch_title.append((text, yj_title, our_title))

print(f"전체 일치: {match_total}/{len(yj) - len(not_found)} ({match_total / max(1, len(yj) - len(not_found)) * 100:.1f}%)")
print(f"우리 데이터에 없음 (dedup으로 사라진 행): {len(not_found)}")
print(f"is_todo 불일치: {len(mismatch_todo)}")
print(f"is_title 불일치: {len(mismatch_title)}")

if mismatch_todo:
    print("\n=== is_todo 불일치 ===")
    for text, yj_t, our_t in mismatch_todo[:30]:
        print(f"  [윤정={yj_t}, 우리={our_t}] {text[:100]}")

if mismatch_title:
    print("\n=== is_title 불일치 ===")
    for text, yj_t, our_t in mismatch_title[:20]:
        print(f"  [윤정={yj_t}, 우리={our_t}] {text[:100]}")

# yj only-true 패턴 확인 — 정밀도/재현율 계산
yj_todos = sum(1 for r in yj if r.get('is_todo'))
yj_titles = sum(1 for r in yj if r.get('is_title'))
print(f"\n윤정 sample 전체: todo={yj_todos}, title={yj_titles}")

# precision/recall
matched_yj = [r for r in yj if r['text'].strip() in ours_map]
tp_todo = sum(1 for r in matched_yj if r.get('is_todo') and ours_map[r['text'].strip()].get('is_todo'))
fp_todo = sum(1 for r in matched_yj if not r.get('is_todo') and ours_map[r['text'].strip()].get('is_todo'))
fn_todo = sum(1 for r in matched_yj if r.get('is_todo') and not ours_map[r['text'].strip()].get('is_todo'))

precision = tp_todo / max(1, tp_todo + fp_todo) * 100
recall = tp_todo / max(1, tp_todo + fn_todo) * 100
print(f"\nis_todo (vs 윤정 sample 매칭된 {len(matched_yj)}행 기준):")
print(f"  TP={tp_todo}, FP={fp_todo}, FN={fn_todo}")
print(f"  Precision: {precision:.1f}%")
print(f"  Recall:    {recall:.1f}%")
