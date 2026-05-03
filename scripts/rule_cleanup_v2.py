"""rule_cleanup 후 deep_audit 결과 기반 추가 정리.

명백한 오류만 처리, 애매한 케이스는 보수적으로 유지.
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DIFF = Path('C:/Users/ashle/AppData/Local/Temp/rule_cleanup_v2_diff.txt')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_todo = sum(1 for r in rows if r.get('is_todo'))
before_title = sum(1 for r in rows if r.get('is_title'))


# ============== is_todo=True → False ==============
todo_changed = defaultdict(list)

# 명백 폼 셀 텍스트 (정확 매칭)
EXACT_FORM_CELLS = {
    '학년 반 이름:', '카드 등록 필요', '이용약관 동의하기', '부보호자 추가하기',
    '선발 아이콘 클릭', '- 약관 동의하기', '학부모: (서명)', '학부모: (인)',
    '학부모 : (인)', '보호자 : (인)', '보호자 (인)', '성명: (서명)',
    '주민등록번 호', '사 진(3x4)', '주 소등 록기준지', '경기도교육청 선택',
    '보호자 전화번호', '상담 요청 일시', '나의지원보기 클릭',
    '휴대폰 인증 실시', '곳을 떠나세요.', '많이 힘들었구나.',
    '4월 학부모총회', '다. 임원의 선출', '1,2학년: 9시',
    '자녀의 학교생활', '자녀의 진로문제', '자녀의 교우관계', '자녀의 학습문제',
    '(문자) 0117', '사용 설명서 필독',
}

for i, r in enumerate(rows):
    if not r.get('is_todo'):
        continue
    text = r['text'].strip()

    # E. 학습 평가 표현 (관찰평가/지필평가/서술평가/실기평가/수행평가)
    if re.search(r'(관찰평가|지필평가|서술평가|수행평가|실기\s*평가|자기평가)', text):
        rows[i]['is_todo'] = False
        todo_changed['E_평가표현'].append((i, text))
        continue

    # G. 명백 인사말/맺음말
    if re.match(r'^건강하고\s*안전한\s*학교\s*생활을\s*위하여', text):
        rows[i]['is_todo'] = False
        todo_changed['G_인사말'].append((i, text))
        continue

    # F. 명백 폼 셀 (정확 매칭)
    if text in EXACT_FORM_CELLS:
        rows[i]['is_todo'] = False
        todo_changed['F_폼셀'].append((i, text))
        continue

    # H. 날짜 + 서명 폼
    if re.match(r'^\d{4}년\s*월\s*일', text) and re.search(r'(성\s*명|서명|인|보호자|신청자|학생)', text):
        rows[i]['is_todo'] = False
        todo_changed['H_날짜서명'].append((i, text))
        continue

    # B. "제목:" 접두사로 시작하면서 짧음
    if re.match(r'^제\s*목\s*[:：]\s*학교,', text) and len(text) < 20:
        rows[i]['is_todo'] = False
        todo_changed['B_제목접두사'].append((i, text))
        continue


# ============== is_title=True → False ==============
title_changed = defaultdict(list)

for i, r in enumerate(rows):
    if not r.get('is_title'):
        continue
    text = r['text'].strip()
    L = len(text)

    # A. 슬로건 시작 (HAPPY & SAFE SCHOOL, 모두가 행복한, 공동체 모두가 행복한, 꿈을 키우며)
    if re.match(r'^(HAPPY\s*&\s*SAFE\s*SCHOOL|모두가 행복한|공동체 모두가 행복한|꿈을 키우며)', text):
        rows[i]['is_title'] = False
        title_changed['A_슬로건시작'].append((i, text))
        continue

    # C. 본문 머지 (150자 이상이면서 학교장/인사말/내용 포함)
    if L > 150:
        rows[i]['is_title'] = False
        title_changed['C_본문머지150+'].append((i, text))
        continue

    # D. 학교장 명시 시작 ("2026. 3. 18. 서울신월초등학교장 ...")
    if re.match(r'^\d{4}[\.\s년]', text) and re.search(r'학\s*교\s*장', text):
        rows[i]['is_title'] = False
        title_changed['D_학교장명시'].append((i, text))
        continue

    # G. 명백 중복 번호 ("35. 17. 4학년 현장체험학습 참가신청 안내 제2022-188호")
    if re.match(r'^\d+\.\s*\d+\.\s+', text):
        rows[i]['is_title'] = False
        title_changed['G_중복번호'].append((i, text))
        continue


# ============== 저장 ==============
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

with open(DIFF, 'w', encoding='utf-8') as f:
    f.write("=== is_todo True→False ===\n")
    for cat, items in todo_changed.items():
        f.write(f"\n[{cat}] {len(items)}건\n")
        for i, t in items:
            f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
    f.write("\n\n=== is_title True→False ===\n")
    for cat, items in title_changed.items():
        f.write(f"\n[{cat}] {len(items)}건\n")
        for i, t in items:
            f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")


# 보고
after_todo = sum(1 for r in rows if r.get('is_todo'))
after_title = sum(1 for r in rows if r.get('is_title'))

print("=== is_todo True→False ===")
total_todo = 0
for cat, items in todo_changed.items():
    print(f"  {cat}: {len(items)}건")
    total_todo += len(items)
print(f"  합계: {total_todo}건  ({before_todo} → {after_todo})")

print("\n=== is_title True→False ===")
total_title = 0
for cat, items in title_changed.items():
    print(f"  {cat}: {len(items)}건")
    total_title += len(items)
print(f"  합계: {total_title}건  ({before_title} → {after_title})")

print(f"\n최종: 전체 {len(rows)}행 | is_todo={after_todo} | is_title={after_title}")
print(f"diff: {DIFF}")
