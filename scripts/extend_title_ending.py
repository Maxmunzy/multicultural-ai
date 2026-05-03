"""title ending 보수적 확장 — 명사형 7개 추가.

기존 윤정님 룰 (8개): 안내|공지|알림|통보|조사|신청|수납|모집
추가 (7개, 명사형만): 동의서|신청서|확인서|공고|요강|보고|결과

이유: 동사형(실시/운영/계획/제출)은 본문에도 자주 등장하여 false positive 위험.
명사형 ending만 추가해 보수적으로 학습 데이터 확보.

is_title=True면 is_todo=False 강제 (윤정님 PR #88 룰 동일).
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')

# 확장 룰
EXTENDED_ENDING = re.compile(
    r"(안내|공지|알림|통보|조사|신청|수납|모집|"
    r"동의서|신청서|확인서|공고|요강|보고|결과)"
    r"\s*(제\s*\d{4,}-\d+호)?$"
)
TITLE_MAX_LEN = 80
SENTENCE_END_RE = re.compile(r"[.!?。？！]")
SECTION_PREFIX_RE = re.compile(r"^[\d가나다라마바사아자차카타파하][.)]\s")


def passes_extended_title(text):
    text = text.strip()
    if not (10 <= len(text) <= TITLE_MAX_LEN):
        return False
    if SENTENCE_END_RE.search(text):
        return False
    if SECTION_PREFIX_RE.match(text):
        return False
    return bool(EXTENDED_ENDING.search(text))


rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_title = sum(1 for r in rows if r.get('is_title'))
before_todo = sum(1 for r in rows if r.get('is_todo'))

new_titles = []
todo_to_false = 0

for i, r in enumerate(rows):
    text = r['text'].strip()
    new_is_title = passes_extended_title(text)
    old_is_title = r.get('is_title', False)

    if new_is_title and not old_is_title:
        rows[i]['is_title'] = True
        new_titles.append((i, text))
        # title=True면 todo=False 강제
        if r.get('is_todo'):
            rows[i]['is_todo'] = False
            todo_to_false += 1

# 저장
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

after_title = sum(1 for r in rows if r.get('is_title'))
after_todo = sum(1 for r in rows if r.get('is_todo'))

# ending별 집계
from collections import Counter
ending_count = Counter()
for _, text in new_titles:
    m = EXTENDED_ENDING.search(text)
    if m:
        ending_count[m.group(1)] += 1

print(f"=== title ending 보수적 확장 ===")
print(f"새로 True 된 title: {len(new_titles)}건")
print(f"  ending별 분포:")
for kw, n in ending_count.most_common():
    print(f"    {kw}: {n}건")
print(f"  is_title=True라 is_todo False 강제: {todo_to_false}건")
print(f"\nis_title: {before_title} → {after_title}")
print(f"is_todo: {before_todo} → {after_todo}")
print(f"\n샘플 (앞 20개):")
for i, t in new_titles[:20]:
    print(f"  {i}: [{len(t)}자] {t[:100]}")
