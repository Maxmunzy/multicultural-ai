"""윤정님 PR #88 룰 엄격 적용 — 위반 is_title을 False로."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DIFF = Path('C:/Users/ashle/AppData/Local/Temp/title_yj_fix_diff.txt')

# 윤정님 정의
TITLE_ENDING_RE = re.compile(r"(안내|공지|알림|통보|조사|신청|수납|모집)\s*(제\s*\d{4,}-\d+호)?$")
TITLE_MAX_LEN = 80
SENTENCE_END_RE = re.compile(r"[.!?。？！]")
SECTION_PREFIX_RE = re.compile(r"^[\d가나다라마바사아자차카타파하][.)]\s")


def passes_yj_title_rule(text):
    """윤정님 4가지 룰 모두 통과해야 True"""
    L = len(text)
    if L > TITLE_MAX_LEN:
        return False
    if SENTENCE_END_RE.search(text):
        return False
    if SECTION_PREFIX_RE.match(text):
        return False
    if not TITLE_ENDING_RE.search(text):
        return False
    return True


rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_title = sum(1 for r in rows if r.get('is_title'))
before_todo = sum(1 for r in rows if r.get('is_todo'))

changed = defaultdict(list)

for i, r in enumerate(rows):
    if not r.get('is_title'):
        continue
    text = r['text'].strip()

    if not passes_yj_title_rule(text):
        rows[i]['is_title'] = False
        # 위반 카테고리 기록
        L = len(text)
        if L > TITLE_MAX_LEN:
            changed['길이_80자초과'].append((i, text))
        elif SENTENCE_END_RE.search(text):
            changed['문장부호_끝'].append((i, text))
        elif SECTION_PREFIX_RE.match(text):
            changed['항목번호_시작'].append((i, text))
        elif not TITLE_ENDING_RE.search(text):
            changed['ending_키워드없음'].append((i, text))
    else:
        # 통과했지만 is_todo도 True면 윤정님 룰: is_title=True → is_todo=False 강제
        if r.get('is_todo'):
            rows[i]['is_todo'] = False
            changed['todo충돌_todo를False로'].append((i, text))


# 저장
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

with open(DIFF, 'w', encoding='utf-8') as f:
    for cat, items in changed.items():
        f.write(f"\n[{cat}] {len(items)}건\n")
        for i, t in items[:60]:
            f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
        if len(items) > 60:
            f.write(f"  ... +{len(items)-60}건 더\n")

after_title = sum(1 for r in rows if r.get('is_title'))
after_todo = sum(1 for r in rows if r.get('is_todo'))

print("=== 윤정님 룰 엄격 적용 ===")
for cat, items in changed.items():
    print(f"  {cat}: {len(items)}건")

print(f"\nis_title: {before_title} → {after_title}")
print(f"is_todo: {before_todo} → {after_todo}")
print(f"\ndiff: {DIFF}")
