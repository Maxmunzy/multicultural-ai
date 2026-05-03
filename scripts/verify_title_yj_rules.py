"""윤정님 PR #88 is_title 규칙으로 우리 668개 검증."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

# 윤정님 정의
TITLE_ENDING_RE = re.compile(r"(안내|공지|알림|통보|조사|신청|수납|모집)\s*(제\s*\d{4,}-\d+호)?$")
TITLE_MAX_LEN = 80
SENTENCE_END_RE = re.compile(r"[.!?。？！]")
SECTION_PREFIX_RE = re.compile(r"^[\d가나다라마바사아자차카타파하][.)]\s")

with open('model/extraction/data/v3_dual_labeled.jsonl', encoding='utf-8') as f:
    rows = [json.loads(l) for l in f if l.strip()]

titles = [(i, r) for i, r in enumerate(rows) if r.get('is_title')]
print(f"is_title=True 총 {len(titles)}개\n")

# 위반 카테고리
v_too_long = []         # 80자 초과
v_sentence_end = []     # 문장 부호 끝
v_section_prefix = []   # 항목 번호 시작
v_no_ending = []        # ending 키워드 없음
v_dual_true = []        # is_todo도 True (충돌)

for i, r in titles:
    text = r['text'].strip()
    L = len(text)

    if L > TITLE_MAX_LEN:
        v_too_long.append((i, text))
    if SENTENCE_END_RE.search(text):
        v_sentence_end.append((i, text))
    if SECTION_PREFIX_RE.match(text):
        v_section_prefix.append((i, text))
    if not TITLE_ENDING_RE.search(text):
        v_no_ending.append((i, text))
    if r.get('is_todo'):
        v_dual_true.append((i, text))

print(f"[1] 80자 초과 (윤정님 룰 위반): {len(v_too_long)}개")
print(f"[2] 문장 부호로 끝남 (위반): {len(v_sentence_end)}개")
print(f"[3] 항목 번호로 시작 (위반): {len(v_section_prefix)}개")
print(f"[4] ending 키워드 없음 (위반): {len(v_no_ending)}개")
print(f"[5] is_todo도 True (충돌, 윤정님 룰 위반): {len(v_dual_true)}개")

# 합집합 (위반 행 unique 카운트)
violation_idx = set()
for items in [v_too_long, v_sentence_end, v_section_prefix, v_no_ending, v_dual_true]:
    for i, _ in items:
        violation_idx.add(i)

valid = len(titles) - len(violation_idx)
print(f"\n→ 윤정님 룰 통과: {valid}개")
print(f"→ 위반: {len(violation_idx)}개")
print(f"→ 통과율: {valid/len(titles)*100:.1f}%")
