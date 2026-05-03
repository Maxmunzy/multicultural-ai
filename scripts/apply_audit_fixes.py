"""full_audit 결과 명백 케이스만 라벨 보정.

학습 평가 기준/단원명/학칙은 제외하고, 진짜 정보/폼/액션만 True로.
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DUMP = Path('C:/Users/ashle/AppData/Local/Temp/audit_fix_diff.txt')

# 학습 단원/평가 — 제외 (todo 아님)
LEARNING_PATTERNS = [
    re.compile(r'^\d+까지의\s*수\s*$'),
    re.compile(r'(잘함|보통|노력요함)\s+\d+까지'),
    re.compile(r'\d+까지의\s*수\s*(의\s*순서|를\s*세고)'),
    re.compile(r'(개념\s*형성\s*수업|서답형\s*평가|관찰\s*평가|구두\s*평가)'),
    re.compile(r'^[\d가-힣]\.?\s*\d+까지의\s*수\s'),
    re.compile(r'(잘함|보통|노력요함)\s+\d+'),
    re.compile(r'^\d+\s*\d+까지의\s*수'),
]

# 학칙/규정 본문 — 제외
LAW_PATTERNS = [
    re.compile(r'^다만,?\s*제\d+'),
    re.compile(r'^제\d+(조|항)'),
    re.compile(r'학년도는\s*\d+월\s*\d+일부터.*?시작하여'),
    re.compile(r'제\d+학기는'),
]

# 일반 본문/뉴스 — 제외
GENERAL_PATTERNS = [
    re.compile(r'(선언하였다|제정되었는데|결의안.*?통과|개정법률안에\s*따라)'),
    re.compile(r'대내외적으로\s*\d{4}년까지'),
    re.compile(r'^코로나19?\s*예방접종\s*시행\s*동의서\s*\(?의료기관\s*제출\)?\s*$'),  # 헤더
]


def is_learning_or_law(text):
    for p in LEARNING_PATTERNS + LAW_PATTERNS + GENERAL_PATTERNS:
        if p.search(text):
            return True
    return False


# 정보/폼/액션 룰 (full_audit과 동일)
INFO_COLON = re.compile(
    r'^\s*[\d가-힣]?\s*[\.\)]?\s*('
    r'일\s*시|시\s*간|장\s*소|대\s*상|기\s*간|비\s*용|금\s*액|연락처|주\s*소|전\s*화|문\s*의|운영\s*시간|모집\s*인원|복\s*장|준비물|일\s*정|인\s*출|납\s*부|수\s*납|참\s*가|행사|예상\s*경비|예상경비|소요\s*경비|행사명|운영\s*기간|모집\s*기간|접수\s*기간|신청\s*기간|체험\s*비용|행사\s*내용|마감일|마감\s*일|사용\s*기간|발송\s*일|제출\s*일|방법|시작\s*일|종료\s*일|운영\s*방식|진행\s*방식|운영\s*장소|진행\s*장소|진행\s*시간|회비|체험장소|체험\s*장소|장 소|일 시|대 상|기 간|비 용'
    r')\s*[:：]'
)

INFO_NATURAL = re.compile(
    r'(까지\s*(제출|납부|회신|보내|작성|등록|이체|신청|접수)|'
    r'\d+월\s*\d+일.*?(까지|제출|납부)|'
    r'\d+\.\s*\d+\.?\s*\([월화수목금토일]\).*?(까지|제출|납부|등록|시행|운영|개최|진행|일과)|'
    r'(스쿨뱅킹|계좌이체|통장|카드|자동이체|현금)\s*(납부|이체|입금|결제))'
)

FORM_PATTERNS = [
    re.compile(r'\(\s*\)\s*(반|번|학년|이름|성명|일|월)'),
    re.compile(r'(인|서명|성명|관계)\s*[:：]?\s*\(\s*인\s*\)'),
    re.compile(r'학부모\s*[:：]?\s*\(\s*(인|서명)'),
    re.compile(r'보호자\s*[:：]?\s*\(\s*(인|서명)'),
    re.compile(r'\(\s*\)\s*불참'),
    re.compile(r'참가\s*\(\s*\)\s*불참'),
    re.compile(r'\d+\s*학년\s*\(\s*\)\s*반'),
    re.compile(r'반\s*\(\s*\)\s*번'),
    re.compile(r'(예|아니요|동의|미동의)\s*[:：]?\s*\(\s*\)'),
    re.compile(r'^불참\s*사유\s*[:：]?'),
    re.compile(r'생년월일\s*[:：]'),  # 생년월일: 같은 폼
    re.compile(r'^\s*수집\s*항목\s*[:：]'),
    re.compile(r'^\s*\d+\.\s*수집\s*항목'),
    re.compile(r'^\s*\d+\.\s*제공.*?(항목|받는)'),
]

ACTION_SPECIFIC = re.compile(
    r'('
    r'\d+월\s*\d+일.*?(까지|이내).*?(제출|납부|회신|보내|작성|등록)|'
    r'(까지|이내).*?(스쿨뱅킹|이체|입금|납부|결제|회신|제출)|'
    r'(담임|담당|선생님).*?(에게|께).*?(제출|회신|보내|작성|문의|연락|상담|협의)|'
    r'반드시.*?(제출|작성|확인|기재|체크)|'
    r'\d+(:|시)\d{1,2}(분)?\s*(까지|이전)|'
    r'(체크|기재|기입|작성)(하여|해)\s*(주|보내|제출|회신)|'
    r'문\s*의\s*[:：]\s*\d|'
    r'담\s*당\s*[:：]\s*\d|'
    r'관련\s*문의\s*[:：]?\s*\d|'
    r'첨부.*?(제출|작성|작성하여|회신)|'
    r'동의서.*?(작성|제출)'
    r')'
)

DEADLINE_DATE = re.compile(
    r'\d+\.?\s*\d+\.?\s*[\(（]?\s*[월화수목금토일]?\s*[\)）]?\s*까지'
)

GENERAL_CLOSING = re.compile(
    r'(많은|적극적인|지속적인|꾸준한|항상|늘|언제나)?\s*'
    r'(관심|협조|참여|성원|격려|이해|동참|배려|응원).*?(부탁|바랍|드립)\s*\.?$'
)


def matches_form(text):
    for p in FORM_PATTERNS:
        if p.search(text):
            return True
    return False


# ============== 적용 ==============
rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_todo = sum(1 for r in rows if r.get('is_todo'))
before_title = sum(1 for r in rows if r.get('is_title'))

changed = defaultdict(list)

# A. is_todo=False → True
for i, r in enumerate(rows):
    if r.get('is_todo') or r.get('is_title'):
        continue
    text = r['text'].strip()
    if not text:
        continue

    # 학습평가/학칙/일반본문 제외
    if is_learning_or_law(text):
        continue

    new_todo = False
    cat = None
    if INFO_COLON.match(text) and len(text) < 200:
        new_todo = True; cat = '정보_콜론'
    elif matches_form(text):
        new_todo = True; cat = '폼셀'
    elif DEADLINE_DATE.search(text) and len(text) < 200:
        new_todo = True; cat = '마감일'
    elif ACTION_SPECIFIC.search(text) and len(text) < 250 and not GENERAL_CLOSING.search(text):
        new_todo = True; cat = '구체액션'
    elif INFO_NATURAL.search(text) and len(text) < 200:
        new_todo = True; cat = '정보_자연어'

    if new_todo:
        rows[i]['is_todo'] = True
        changed['F→T_' + cat].append((i, text))

# B. is_todo=True → False (HAPPY & SAFE / 모두가 행복한 슬로건 머지)
SLOGAN_MERGE = re.compile(r'^(HAPPY\s*&\s*SAFE\s*SCHOOL|모두가\s*행복한)\s')
for i, r in enumerate(rows):
    if not r.get('is_todo') or r.get('is_title'):
        continue
    text = r['text'].strip()
    if SLOGAN_MERGE.match(text):
        rows[i]['is_todo'] = False
        changed['T→F_슬로건머지'].append((i, text))


# 저장
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

with open(DUMP, 'w', encoding='utf-8') as f:
    for cat, items in changed.items():
        f.write(f"\n[{cat}] {len(items)}건\n")
        for i, t in items[:200]:
            f.write(f"  {i}: [{len(t)}자] {t[:140]}\n")
        if len(items) > 200:
            f.write(f"  ... +{len(items)-200}건\n")

after_todo = sum(1 for r in rows if r.get('is_todo'))
after_title = sum(1 for r in rows if r.get('is_title'))

print("=== audit fix 적용 ===")
for cat, items in changed.items():
    print(f"  {cat}: {len(items)}건")
print(f"\nis_todo: {before_todo} → {after_todo}")
print(f"is_title: {before_title} → {after_title}")
print(f"\ndiff: {DUMP}")
