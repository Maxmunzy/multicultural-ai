"""v3_dual_labeled.jsonl 라벨 품질 심층 검증."""
import json, sys, random, re
sys.stdout.reconfigure(encoding='utf-8')

with open('model/extraction/data/v3_dual_labeled.jsonl', encoding='utf-8') as f:
    rows = [json.loads(l) for l in f if l.strip()]

n = len(rows)
print(f"전체 {n}행\n")

# ===== 1. 길이 분포 검증 =====
print("=== 길이 분포 ===")
lens = [len(r['text']) for r in rows]
print(f"  min={min(lens)}, max={max(lens)}, 평균={sum(lens)//n}자")
buckets = [(0,10,'<10'),(10,30,'10-30'),(30,80,'30-80'),(80,200,'80-200'),(200,99999,'200+')]
for lo,hi,name in buckets:
    cnt = sum(1 for l in lens if lo<=l<hi)
    print(f"  {name:6s}: {cnt:6d} ({cnt/n*100:.1f}%)")

# ===== 2. is_title 라벨 검증 =====
print("\n=== is_title 분석 ===")
titles = [r for r in rows if r.get('is_title')]
print(f"  total: {len(titles)}")

# 의심: is_title인데 너무 길거나 너무 짧음
suspicious_title = [r for r in titles if len(r['text'])<5 or len(r['text'])>80]
print(f"  의심 (5자 미만 또는 80자 초과): {len(suspicious_title)}")
for r in suspicious_title[:5]:
    print(f"    [{len(r['text'])}자] {r['text'][:100]}")

# 의심: is_title인데 인사말/표 행/단순 정보
greet_re = re.compile(r'안녕하|학부모님께|보호자님|존경하는')
suspicious_title_greet = [r for r in titles if greet_re.search(r['text'])]
print(f"  의심 (인사말 패턴): {len(suspicious_title_greet)}")
for r in suspicious_title_greet[:3]:
    print(f"    {r['text'][:80]}")

# is_title 정상 샘플
print(f"\n  정상 샘플 (랜덤 5개):")
random.seed(1)
for r in random.sample(titles, 5):
    print(f"    [{len(r['text'])}자] {r['text'][:80]}")

# ===== 3. is_todo 라벨 검증 =====
print("\n=== is_todo 분석 ===")
todos = [r for r in rows if r.get('is_todo')]
print(f"  total: {len(todos)}")

# 의심: is_todo인데 너무 짧음 (의미 없는 토막)
suspicious_todo_short = [r for r in todos if len(r['text']) < 10]
print(f"  의심 (10자 미만): {len(suspicious_todo_short)}")
for r in suspicious_todo_short[:5]:
    print(f"    [{len(r['text'])}자] {r['text']}")

# 의심: is_todo인데 인사말/배경
suspicious_todo_greet = [r for r in todos if greet_re.search(r['text'])]
print(f"  의심 (인사말이 todo로): {len(suspicious_todo_greet)}")
for r in suspicious_todo_greet[:3]:
    print(f"    {r['text'][:80]}")

# is_todo 정상 샘플
print(f"\n  정상 샘플 (랜덤 5개):")
for r in random.sample(todos, 5):
    print(f"    [{len(r['text'])}자] {r['text'][:80]}")

# ===== 4. 둘 다 False — 이게 진짜 본문/표인지 =====
print("\n=== 둘 다 False (본문/표/안내 — 정상 비율 70%대) ===")
both_f = [r for r in rows if not r.get('is_todo') and not r.get('is_title')]
print(f"  total: {len(both_f)}")

# 의심: 명백히 행동인데 False (False Negative)
action_words = re.compile(r'제출.{0,5}(주세요|해주|바랍|부탁|요)|준비.{0,5}(주세요|해주|바랍)|납부.{0,5}(주세요|바랍)|작성.{0,5}(주세요|바랍)|확인.{0,5}(주세요|바랍|해주)|신청.{0,5}(주세요|바랍|해주)')
should_be_todo = [r for r in both_f if action_words.search(r['text'])]
print(f"  의심 (행동 동사인데 todo로 안 잡힘): {len(should_be_todo)}")
for r in should_be_todo[:5]:
    print(f"    {r['text'][:80]}")

# ===== 5. 둘 다 True =====
both_t = [r for r in rows if r.get('is_todo') and r.get('is_title')]
print(f"\n=== 둘 다 True (제목+행동 동시) — {len(both_t)}건 ===")
for r in both_t[:8]:
    print(f"    {r['text'][:80]}")

# ===== 6. 잠재적 잘못된 라벨 비율 추정 =====
print("\n=== 라벨 품질 추정 ===")
suspicious_total = (len(suspicious_title) + len(suspicious_title_greet) +
                    len(suspicious_todo_short) + len(suspicious_todo_greet) +
                    len(should_be_todo))
print(f"  잠재 의심 라벨: {suspicious_total} ({suspicious_total/n*100:.2f}%)")
print(f"  정상 추정: {n - suspicious_total} ({(n-suspicious_total)/n*100:.2f}%)")
