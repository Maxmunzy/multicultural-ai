"""실제 데이터 무작위 샘플로 라벨 정확도 수동 검증 가능하게."""
import json, sys, random
sys.stdout.reconfigure(encoding='utf-8')

with open('model/extraction/data/v3_dual_labeled.jsonl', encoding='utf-8') as f:
    rows = [json.loads(l) for l in f if l.strip()]

random.seed(123)

# 1. is_todo=True 무작위 30개
todos = [r for r in rows if r.get('is_todo')]
print(f"=== is_todo=True 무작위 30개 (총 {len(todos)}개 중) ===\n")
for i, r in enumerate(random.sample(todos, 30), 1):
    title_mark = " [+title]" if r.get('is_title') else ""
    print(f"{i:2d}. [{len(r['text']):>3}자]{title_mark} {r['text'][:90]}")

print("\n\n")

# 2. is_title=True 무작위 30개
titles = [r for r in rows if r.get('is_title')]
print(f"=== is_title=True 무작위 30개 (총 {len(titles)}개 중) ===\n")
for i, r in enumerate(random.sample(titles, 30), 1):
    todo_mark = " [+todo]" if r.get('is_todo') else ""
    print(f"{i:2d}. [{len(r['text']):>3}자]{todo_mark} {r['text'][:90]}")

print("\n\n")

# 3. 둘 다 False 무작위 30개 (본문이라야 정상)
both_f = [r for r in rows if not r.get('is_todo') and not r.get('is_title')]
print(f"=== 둘 다 False 무작위 30개 (총 {len(both_f)}개 중) ===\n")
for i, r in enumerate(random.sample(both_f, 30), 1):
    print(f"{i:2d}. [{len(r['text']):>3}자] {r['text'][:90]}")

print("\n\n")

# 4. 둘 다 True 전부 (드물어야 함)
both_t = [r for r in rows if r.get('is_todo') and r.get('is_title')]
print(f"=== 둘 다 True 전체 ({len(both_t)}개) ===\n")
for i, r in enumerate(both_t, 1):
    print(f"{i:2d}. [{len(r['text']):>3}자] {r['text'][:90]}")
