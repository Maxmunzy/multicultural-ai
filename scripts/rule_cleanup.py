"""룰 기반 라벨 정리: 학칙/학습활동/슬로건/안건/강좌명 등 명백 오류 수정.

전수 검토 결과 발견된 패턴별로 정규식 적용하여 잘못된 라벨을 일괄 수정.
변경된 케이스는 별도 파일로 dump하여 검증 가능하게.
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DIFF = Path('C:/Users/ashle/AppData/Local/Temp/rule_cleanup_diff.txt')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_todo = sum(1 for r in rows if r.get('is_todo'))
before_title = sum(1 for r in rows if r.get('is_title'))
print(f"시작: {len(rows)}행 | is_todo={before_todo} | is_title={before_title}\n")


# ============== is_todo=True → False 룰 ==============
TODO_RULES = [
    # 학칙 조항
    ('TODO_학칙', re.compile(r'^제\d+조'), 'todo'),
    ('TODO_학칙장', re.compile(r'^제\d+장'), 'todo'),
    # 학습 활동 (~하기로 끝나는 활동)
    ('TODO_학습활동', re.compile(r'(만들기|찾아보기|발표하기|이해하기|학습하기|평가하기|조사하기|연주한다|체험학습하기)$'), 'todo'),
    # 성취기준 코드 (예: 6실01-02, 4음01-01, 6사01-04)
    ('TODO_성취코드', re.compile(r'\d+[가-힣]\d+-\d+'), 'todo'),
    # 단원 헤더 (1. 집 ( ), ( ))
    ('TODO_빈괄호셀', re.compile(r'^\d+\.\s*[가-힣A-Za-z\s]+\(\s*\)(?:\s*,?\s*\(\s*\))+$'), 'todo'),
    # URL 단독 시작 + 짧은 안내
    ('TODO_URL시작', re.compile(r'^https?://'), 'todo'),
    # 짧은 폼 셀
    ('TODO_폼셀', None, 'todo'),  # 길이 + 패턴 기반
]

# is_todo False로 변경
todo_changed = defaultdict(list)
for i, r in enumerate(rows):
    if not r.get('is_todo'):
        continue
    text = r['text'].strip()
    matched_rule = None

    # 학칙 조항
    if re.match(r'^제\d+조', text):
        matched_rule = 'TODO_학칙'
    # 학칙 장
    elif re.match(r'^제\d+장', text):
        matched_rule = 'TODO_학칙장'
    # 성취기준 코드 포함 (단원/평가)
    elif re.search(r'\d+[가-힣]\d+-\d+', text):
        matched_rule = 'TODO_성취코드'
    # 학습 활동 (~하기로 끝나고 단원/평가 맥락)
    elif re.search(r'(발표하기|조사하기|이해하기|학습하기|체험학습하기|연주한다)$', text):
        matched_rule = 'TODO_학습활동'
    # 빈 괄호 폼 ("1. 집 ( ), ( )")
    elif re.match(r'^\d+\.\s*[^()]+\(\s*\).*\(\s*\)\s*$', text) and len(text) < 40:
        matched_rule = 'TODO_빈괄호셀'
    # URL 단독 또는 URL+짧은 안내 (50자 미만)
    elif re.match(r'^https?://', text) and len(text) < 60:
        matched_rule = 'TODO_URL시작'
    # 짧은 토막 (8자 미만, 형식적 폼/버튼)
    elif len(text) < 8:
        # 명령형 한 단어 동사("제출하세요" 같은건 살림) — 형용사/명사 위주만 False
        if re.search(r'(필수|준비|입장|클릭|확인|선택|동의|미동의|소속|간편|복장|매일|여벌|희망|학교|학년|학생|반|이름|보호자|연락처|주소|전화|날짜|시간|장소|학생\(인\)|보호자\s*\(인\))', text):
            matched_rule = 'TODO_폼셀'

    if matched_rule:
        rows[i]['is_todo'] = False
        todo_changed[matched_rule].append((i, text))


# ============== is_title=True → False 룰 ==============
title_changed = defaultdict(list)
for i, r in enumerate(rows):
    if not r.get('is_title'):
        continue
    text = r['text'].strip()
    matched_rule = None

    # 회의 안건 (...(안)$)
    if re.search(r'\(안\)\s*$', text):
        matched_rule = 'TITLE_회의안건'
    # 본문이 길게 머지된 케이스 (200자 초과)
    elif len(text) > 200:
        matched_rule = 'TITLE_본문머지'
    # 짧은 건강 팁/캠페인 슬로건 (느낌표 끝, 짧은 호소문)
    elif len(text) < 25 and re.search(r'(예방$|예방법$|예방하세요|범죄행위입니다|예방\s*\d+단계|날$|예방 안내$)', text):
        matched_rule = 'TITLE_건강팁'
    elif len(text) < 25 and re.search(r'!\s*$', text) and not re.search(r'(안내|모집|공고|개최)', text):
        # 강좌명 류 ("일상툰을 그려보자!", "보드게임 속에 담긴 수학!")
        matched_rule = 'TITLE_강좌명'

    if matched_rule:
        rows[i]['is_title'] = False
        title_changed[matched_rule].append((i, text))


# ============== 저장 + diff dump ==============
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

with open(DIFF, 'w', encoding='utf-8') as f:
    f.write("=== is_todo True→False 변경 ===\n\n")
    for rule, items in todo_changed.items():
        f.write(f"\n[{rule}] {len(items)}건\n")
        for i, t in items:
            f.write(f"  {i}: [{len(t)}자] {t[:100]}\n")
    f.write("\n\n=== is_title True→False 변경 ===\n\n")
    for rule, items in title_changed.items():
        f.write(f"\n[{rule}] {len(items)}건\n")
        for i, t in items:
            f.write(f"  {i}: [{len(t)}자] {t[:100]}\n")


# ============== 보고 ==============
after_todo = sum(1 for r in rows if r.get('is_todo'))
after_title = sum(1 for r in rows if r.get('is_title'))

print("=== is_todo True→False ===")
total_todo = 0
for rule, items in todo_changed.items():
    print(f"  {rule}: {len(items)}건")
    total_todo += len(items)
print(f"  합계: {total_todo}건  ({before_todo} → {after_todo})")

print("\n=== is_title True→False ===")
total_title = 0
for rule, items in title_changed.items():
    print(f"  {rule}: {len(items)}건")
    total_title += len(items)
print(f"  합계: {total_title}건  ({before_title} → {after_title})")

print(f"\ndiff 저장: {DIFF}")
