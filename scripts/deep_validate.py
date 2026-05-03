"""v3_dual_labeled.jsonl 심층 검증."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from collections import Counter

with open('model/extraction/data/v3_dual_labeled.jsonl', encoding='utf-8') as f:
    rows = [json.loads(l) for l in f if l.strip()]

n = len(rows)
print(f"=== 전체 {n}행 심층 검증 ===\n")

# [1] 스키마
print("[1] 스키마 검증")
missing_fields = sum(1 for r in rows if 'text' not in r or 'is_todo' not in r or 'is_title' not in r)
empty_text = sum(1 for r in rows if not r.get('text', '').strip())
non_bool_todo = sum(1 for r in rows if not isinstance(r.get('is_todo'), bool))
non_bool_title = sum(1 for r in rows if not isinstance(r.get('is_title'), bool))
print(f"  필수 필드 누락: {missing_fields}")
print(f"  text 빈값/공백: {empty_text}")
print(f"  is_todo 비-bool: {non_bool_todo}")
print(f"  is_title 비-bool: {non_bool_title}")

# [2] 인코딩 — replacement char(�), 제어문자
print("\n[2] 인코딩/문자 오염")
def has_garbled(t):
    for c in t:
        cp = ord(c)
        if cp == 0xFFFD or (0x00 <= cp < 0x20 and cp not in (0x09, 0x0A, 0x0D)):
            return True
    return False
garbled_rows = [r for r in rows if has_garbled(r['text'])]
print(f"  깨진/제어 문자 포함: {len(garbled_rows)}")
for r in garbled_rows[:3]:
    print(f"    {repr(r['text'][:60])}")

def hangul_ratio(t):
    if not t: return 0
    return sum(1 for c in t if '가' <= c <= '힣') / len(t)
low_hangul = [r for r in rows if hangul_ratio(r['text']) < 0.15 and len(r['text']) > 20]
print(f"  한글 비율 15% 미만 (외국어/노이즈): {len(low_hangul)}")
for r in low_hangul[:3]:
    print(f"    {r['text'][:80]}")

# [3] 중복
print("\n[3] 중복 검증")
text_counts = Counter(r['text'] for r in rows)
dup_kinds = sum(1 for c in text_counts.values() if c > 1)
dup_total = sum(c for c in text_counts.values() if c > 1)
print(f"  완전 중복 종류: {dup_kinds}, 인스턴스: {dup_total}")
for text, cnt in sorted([(t,c) for t,c in text_counts.items() if c > 1], key=lambda x: -x[1])[:5]:
    print(f"    {cnt}회: {text[:70]}")

# [4] 길이
print("\n[4] 길이 분포")
lens = sorted([len(r['text']) for r in rows])
print(f"  min={lens[0]}, max={lens[-1]}, 중앙={lens[n//2]}, 평균={sum(lens)//n}")
buckets = [(0,5,'<5'),(5,10,'5-10'),(10,30,'10-30'),(30,80,'30-80'),(80,200,'80-200'),(200,1000,'200-1000'),(1000,99999999,'1000+')]
for lo,hi,name in buckets:
    cnt = sum(1 for l in lens if lo<=l<hi)
    if cnt > 0:
        print(f"    {name:10s}: {cnt:6d} ({cnt/n*100:5.2f}%)")

# [5] is_title
print("\n[5] is_title 분석")
titles = [r for r in rows if r.get('is_title')]
print(f"  total: {len(titles)} ({len(titles)/n*100:.1f}%)")
t_lens = sorted([len(r['text']) for r in titles])
print(f"  길이 min={t_lens[0]}, max={t_lens[-1]}, 중앙={t_lens[len(t_lens)//2]}")

short_t = [r for r in titles if len(r['text']) < 10]
print(f"  10자 미만 is_title: {len(short_t)}")
for r in short_t[:5]:
    print(f"    [{len(r['text'])}자] {r['text']}")

greet_end_re = re.compile(r'안녕하(십니까|세요)\??$')
greet_end = [r for r in titles if greet_end_re.search(r['text'])]
print(f"  '안녕하십니까?'로 끝나는 is_title: {len(greet_end)}")
for r in greet_end[:3]:
    print(f"    {r['text'][:80]}")

# [6] is_todo
print("\n[6] is_todo 분석")
todos = [r for r in rows if r.get('is_todo')]
print(f"  total: {len(todos)} ({len(todos)/n*100:.1f}%)")
to_lens = sorted([len(r['text']) for r in todos])
print(f"  길이 min={to_lens[0]}, max={to_lens[-1]}, 중앙={to_lens[len(to_lens)//2]}")

short_to = [r for r in todos if len(r['text']) < 10]
print(f"  10자 미만 is_todo: {len(short_to)}")
for r in short_to[:5]:
    print(f"    [{len(r['text'])}자] {r['text']}")

# [7] False Negative
print("\n[7] is_todo False Negative (강한 행동 패턴인데 todo=False)")
both_f = [r for r in rows if not r.get('is_todo') and not r.get('is_title')]
strong = re.compile(r'(제출|납부|작성|확인|준비|신청).{0,10}(해\s*주(시|세요)|바랍|부탁드)')
fn_todo = [r for r in both_f if strong.search(r['text'])]
print(f"  발견: {len(fn_todo)}")
for r in fn_todo[:8]:
    print(f"    {r['text'][:80]}")

# [8] is_title False Negative — 짧고 '안내/모집/공고'로 끝나는 것들 중 title=False
print("\n[8] is_title False Negative (제목 패턴인데 title=False)")
title_re = re.compile(r'(안내|모집|공고|개최|실시\s*안내)$')
fn_title = [r for r in rows if not r.get('is_title') and 10 <= len(r['text']) <= 50 and title_re.search(r['text'])]
print(f"  발견: {len(fn_title)}")
for r in fn_title[:8]:
    print(f"    [{len(r['text'])}자] {r['text']}")

# [9] 라벨 분포
print("\n[9] 라벨 분포")
todo_t = sum(1 for r in rows if r.get('is_todo'))
title_t = sum(1 for r in rows if r.get('is_title'))
both_t = sum(1 for r in rows if r.get('is_todo') and r.get('is_title'))
both_f_n = sum(1 for r in rows if not r.get('is_todo') and not r.get('is_title'))
print(f"  is_todo=T:    {todo_t} ({todo_t/n*100:5.1f}%)  목표 20-30%")
print(f"  is_title=T:   {title_t} ({title_t/n*100:5.1f}%)  목표 5-10%")
print(f"  둘 다 T:      {both_t} ({both_t/n*100:5.2f}%)  드물어야")
print(f"  둘 다 F:      {both_f_n} ({both_f_n/n*100:5.1f}%)  본문/표")

# [10] 종합
print("\n[10] 종합 잠재 이슈")
issues = {
    "스키마 누락": missing_fields,
    "빈 텍스트": empty_text,
    "비-bool 라벨": non_bool_todo + non_bool_title,
    "깨진 문자": len(garbled_rows),
    "한글 비율 낮음": len(low_hangul),
    "중복 인스턴스": dup_total,
    "is_title 토막(<10자)": len(short_t),
    "is_title 인사말로 끝": len(greet_end),
    "is_todo 토막(<10자)": len(short_to),
    "is_todo False Negative": len(fn_todo),
    "is_title False Negative": len(fn_title),
}
total = sum(issues.values())
print(f"  총 잠재 이슈: {total} / {n} ({total/n*100:.2f}%)")
for k, v in sorted(issues.items(), key=lambda x: -x[1]):
    if v > 0:
        print(f"    {k}: {v}")
