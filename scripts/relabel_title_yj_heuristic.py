"""윤정님 PR #88 is_title_heuristic 함수 그대로 28,890행에 재적용.

strict_verify로 망가진 is_title을 복구.
is_todo는 유지 (이미 윤정님 정의로 정제됨).
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')

# 윤정님 PR #88 정의 그대로
TITLE_ENDING_RE = re.compile(r"(안내|공지|알림|통보|조사|신청|수납|모집)\s*(제\s*\d{4,}-\d+호)?$")
TITLE_MAX_LEN = 80
SENTENCE_END_RE = re.compile(r"[.!?。？！]")
SECTION_PREFIX_RE = re.compile(r"^[\d가나다라마바사아자차카타파하][.)]\s")


def is_title_heuristic(text):
    """윤정님 PR #88 함수 그대로"""
    text = text.strip()
    if not (10 <= len(text) <= TITLE_MAX_LEN):
        return False
    if SENTENCE_END_RE.search(text):
        return False
    if SECTION_PREFIX_RE.match(text):
        return False
    return bool(TITLE_ENDING_RE.search(text))


rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_title = sum(1 for r in rows if r.get('is_title'))
before_todo = sum(1 for r in rows if r.get('is_todo'))
print(f"시작: title={before_title}, todo={before_todo}")

# 모든 행에 윤정님 heuristic 적용
new_titles = 0
removed_titles = 0
todo_to_false = 0  # is_title=True면 is_todo=False 강제

for i, r in enumerate(rows):
    text = r['text'].strip()
    new_is_title = is_title_heuristic(text)
    old_is_title = r.get('is_title', False)

    rows[i]['is_title'] = new_is_title

    if new_is_title and not old_is_title:
        new_titles += 1
    elif not new_is_title and old_is_title:
        removed_titles += 1

    # 윤정님 룰: is_title=True면 is_todo=False 강제
    if new_is_title and r.get('is_todo'):
        rows[i]['is_todo'] = False
        todo_to_false += 1

# 저장
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

after_title = sum(1 for r in rows if r.get('is_title'))
after_todo = sum(1 for r in rows if r.get('is_todo'))

print(f"\n=== 윤정님 heuristic 재적용 ===")
print(f"  새로 True 된 행: +{new_titles}")
print(f"  False로 변경된 행: -{removed_titles}")
print(f"  is_title=True이라 is_todo False로 강제: {todo_to_false}")
print(f"\nis_title: {before_title} → {after_title}")
print(f"is_todo: {before_todo} → {after_todo}")
