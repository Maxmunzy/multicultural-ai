"""윤정님 label_sample.jsonl 기준으로 is_todo 재라벨링.

윤정님 is_todo=True 패턴 (sample 30건 분석):
1. 정보 안내 (일시/장소/대상/금액/복장/준비물/인출/납부 등) — 콜론형
2. 폼 셀 (서명/인/빈괄호/학년반번호이름)
3. 체크 폼 (참가( )/불참( ), 참석 불참)
4. 액션 동사 (제출/납부/확인/협조/연락/문의/회신)

is_todo=False 유지:
- 인사말 (학부모님 안녕하세요/감사합니다/기원합니다)
- 본문 설명 (이는 ~위함입니다, ~ 운영하고자 합니다)
- 표 헤더만, 학교명/주소/전화 단독
- 통신문 메타 (제2026-XX호, 발행처)
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DIFF = Path('C:/Users/ashle/AppData/Local/Temp/relabel_yj_diff.txt')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_todo = sum(1 for r in rows if r.get('is_todo'))
before_title = sum(1 for r in rows if r.get('is_title'))
print(f"시작: {len(rows)}행 | is_todo={before_todo} | is_title={before_title}\n")


# ============== 윤정님 기준 정보/폼 패턴 ==============

# 정보 안내 키워드 (콜론형)
INFO_KEYWORDS = r'(일시|시간|장소|대상|기간|비용|금액|연락처|주소|전화|문의|운영시간|모집인원|복장|준비물|일정|인출|납부|수납|참가|행사\s*일시|행사\s*장소|참여\s*대상|행사\s*개요|예상\s*경비|예상경비|소요경비|행사\s*명|행사명|행사\s*기간|운영\s*기간|모집\s*기간|접수\s*기간|신청\s*기간|모집\s*인원|모집인원|체험\s*비용|행사\s*내용|장 소|일 시|대 상|기 간|비 용|일자|월일|시작\s*일|종료\s*일|마감일|마감\s*일|운영방식|운영\s*방식|진행\s*방식|운영장소|진행\s*장소|진행시간)'

# 폼/서식 패턴 (빈 괄호, 인, 서명, 학년 반 번호 등)
FORM_PATTERNS = [
    re.compile(r'\(\s*\)\s*(반|번|학년|이름|성명|일|반\s*\(\s*\))'),  # ()반 ()번 ()이름
    re.compile(r'(인|서명|성명)\s*[:：]?\s*\(.*?인.*?\)'),  # (인), (서명)
    re.compile(r'학부모\s*[:：]?\s*\(\s*(인|서명)'),
    re.compile(r'보호자\s*[:：]?\s*\(\s*(인|서명)'),
    re.compile(r'\(\s*\)\s*불참'),  # 참가( ) 불참( )
    re.compile(r'참가\s*\(\s*\)'),
    re.compile(r'참석\s*불참'),
    re.compile(r'\d+\s*학년\s*\(\s*\)\s*반'),  # 1학년 ( )반
    re.compile(r'반\s*\(\s*\)\s*번'),
    re.compile(r'^불참\s*사유\s*[:：]?'),
    re.compile(r'성명\s*[:：]?\s*\(\s*(서명|인)'),
    re.compile(r'(보호자|법정대리인)\s*\(?관계\)?\s*[:：]?'),
    re.compile(r'^.{0,10}(반|번|이름|성명)\s*[:：]?\s*$'),  # 짧은 폼 헤더
    re.compile(r'\(\s*\)\s*$'),  # 빈 괄호로 끝
]

# 액션 동사 (이미 잡혀있을 수도, 보강용)
ACTION_PATTERNS = [
    re.compile(r'(제출|납부|회신|보내주시기|보내\s*주시기|보내주세요|기재해|작성해|동의해|등록해|문의|연락|확인\s*바랍|점검\s*바랍|준비\s*바랍|참여\s*바랍|참가\s*바랍|신청\s*바랍|이체|입금|결제|체크|기입)\s*(해|하)?(\s*주시기?)?\s*바랍니다')
]

# 단순 액션 표현
ACTION_SIMPLE = re.compile(r'(주시기\s*바랍니다|드립니다\s*$|부탁드립니다|협조\s*바랍|협조해\s*주|참고하시어|첨부해|회신해\s*주)')

# 폼/정보가 아닌 명백 false 패턴
EXCLUDE_PATTERNS = [
    re.compile(r'^안녕하(십니까|세요)\??$'),
    re.compile(r'^항상.*감사드립니다\.?$'),
    re.compile(r'^.*기원합니다\.?$'),
    re.compile(r'^.*양해\s*(부탁|바랍)'),
    re.compile(r'^제\d+조'),  # 학칙
    re.compile(r'^제\d+장'),
    re.compile(r'\d+[가-힣]\d+-\d+'),  # 성취기준 코드
    re.compile(r'(관찰평가|지필평가|서술평가|수행평가|자기평가|실기평가)'),
    re.compile(r'^https?://\S+$'),  # URL 단독
]


def matches_info(text):
    """윤정님 정보 안내 패턴"""
    # 콜론형 ("1. 일시: ...", "장소:", "대상 : ...")
    if re.match(rf'^\s*[\d가-힣]?[\.\)]?\s*{INFO_KEYWORDS}\s*[:：]', text):
        return True
    # 키워드 + 짧은 정보 (콜론 없이)
    if re.match(rf'^\s*{INFO_KEYWORDS}\s+\S', text) and len(text) < 80:
        return True
    return False


def matches_form(text):
    """윤정님 폼 셀 패턴"""
    for p in FORM_PATTERNS:
        if p.search(text):
            return True
    return False


def matches_action(text):
    """액션 동사"""
    for p in ACTION_PATTERNS:
        if p.search(text):
            return True
    if ACTION_SIMPLE.search(text):
        return True
    return False


def is_excluded(text):
    """명백히 todo 아님"""
    for p in EXCLUDE_PATTERNS:
        if p.search(text):
            return True
    return False


# ============== 적용 ==============
changed = defaultdict(list)

for i, r in enumerate(rows):
    text = r['text'].strip()
    cur_todo = r.get('is_todo', False)

    # 새로운 라벨 결정 (윤정님 기준)
    new_todo = cur_todo

    if not is_excluded(text):
        # 정보/폼/액션 중 하나라도 해당하면 True
        if matches_info(text) or matches_form(text) or matches_action(text):
            new_todo = True

    # 변경 기록
    if cur_todo != new_todo:
        if new_todo:
            # False → True
            if matches_form(text):
                changed['F→T_폼셀'].append((i, text))
            elif matches_info(text):
                changed['F→T_정보'].append((i, text))
            elif matches_action(text):
                changed['F→T_액션'].append((i, text))
        else:
            changed['T→F'].append((i, text))
        rows[i]['is_todo'] = new_todo


# ============== 저장 + diff ==============
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

with open(DIFF, 'w', encoding='utf-8') as f:
    for cat in sorted(changed.keys()):
        items = changed[cat]
        f.write(f"\n[{cat}] {len(items)}건\n")
        for i, t in items[:80]:
            f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
        if len(items) > 80:
            f.write(f"  ... +{len(items)-80}건 더\n")

# 보고
after_todo = sum(1 for r in rows if r.get('is_todo'))
after_title = sum(1 for r in rows if r.get('is_title'))

print("=== 변경 ===")
total = 0
for cat, items in changed.items():
    print(f"  {cat}: {len(items)}건")
    total += len(items)
print(f"\n  is_todo: {before_todo} → {after_todo} ({after_todo - before_todo:+d})")
print(f"  is_title: {before_title} → {after_title} (변동 없음 — 정의 일치)")
print(f"\ndiff: {DIFF}")
