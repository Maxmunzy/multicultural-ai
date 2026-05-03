"""is_title=True인데 80자+ 또는 인사말 포함된 케이스 상세 검증."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('model/extraction/data/v3_dual_labeled.jsonl', encoding='utf-8') as f:
    rows = [json.loads(l) for l in f if l.strip()]

titles = [r for r in rows if r.get('is_title')]
greet_re = re.compile(r'안녕하|학부모님께|보호자님|존경하는')

# 1. 80자+ is_title 모두 출력
long_titles = [r for r in titles if len(r['text']) > 80]
print(f"=== is_title=True인데 80자+ ({len(long_titles)}개) — 처음 15개 ===\n")
for i, r in enumerate(long_titles[:15], 1):
    print(f"[{i}] [{len(r['text'])}자]")
    print(f"  {r['text']}")
    print()

print(f"\n{'='*80}\n")

# 2. 인사말 포함 is_title — 처음 15개
greet_titles = [r for r in titles if greet_re.search(r['text'])]
print(f"=== is_title=True인데 인사말 포함 ({len(greet_titles)}개) — 처음 15개 ===\n")
for i, r in enumerate(greet_titles[:15], 1):
    print(f"[{i}] [{len(r['text'])}자]")
    print(f"  {r['text']}")
    print()
