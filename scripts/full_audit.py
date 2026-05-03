"""v3_dual_labeled.jsonl 전수 audit — 4갈래 모두 검사.

A. is_todo=False → True여야 할 후보 (정보/폼/액션 패턴)
B. is_todo=True → False여야 할 후보 (closing/인사/학칙/단원 등)
C. is_title=False → True여야 할 후보 (윤정님 룰 통과하는데 안 잡힌 것)
D. is_title=True → False여야 할 후보 (윤정님 룰 위반)
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DUMP = Path('C:/Users/ashle/AppData/Local/Temp/full_audit.txt')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

cur_todo = sum(1 for r in rows if r.get('is_todo'))
cur_title = sum(1 for r in rows if r.get('is_title'))
print(f"현재: 전체 {len(rows)} | todo={cur_todo} | title={cur_title}\n")


# ============== 윤정님 룰 ==============
TITLE_ENDING_RE = re.compile(r"(안내|공지|알림|통보|조사|신청|수납|모집)\s*(제\s*\d{4,}-\d+호)?$")
SENTENCE_END_RE = re.compile(r"[.!?。？！]")
SECTION_PREFIX_RE = re.compile(r"^[\d가나다라마바사아자차카타파하][.)]\s")


def passes_yj_title(text):
    text = text.strip()
    if not (10 <= len(text) <= 80):
        return False
    if SENTENCE_END_RE.search(text):
        return False
    if SECTION_PREFIX_RE.match(text):
        return False
    return bool(TITLE_ENDING_RE.search(text))


# ============== is_todo 패턴 ==============

INFO_COLON = re.compile(
    r'^\s*[\d가-힣]?\s*[\.\)]?\s*('
    r'일\s*시|시\s*간|장\s*소|대\s*상|기\s*간|비\s*용|금\s*액|연락처|주\s*소|전\s*화|문\s*의|운영\s*시간|모집\s*인원|복\s*장|준비물|일\s*정|인\s*출|납\s*부|수\s*납|참\s*가|행사|예상\s*경비|예상경비|소요\s*경비|행사명|운영\s*기간|모집\s*기간|접수\s*기간|신청\s*기간|체험\s*비용|행사\s*내용|마감일|마감\s*일|사용\s*기간|발송\s*일|제출\s*일|방법|시작\s*일|종료\s*일|운영\s*방식|진행\s*방식|운영\s*장소|진행\s*장소|진행\s*시간|회비|성명|학년|반|번|이름|생년월일|자녀\s*이름|행사\s*일시|참여\s*대상|모집\s*기간|준비\s*사항|체험\s*장소|장 소|일 시|대 상|기 간|비 용'
    r')\s*[:：]'
)

INFO_NATURAL = re.compile(
    r'(까지\s*(제출|납부|회신|보내|작성|등록|이체|신청|접수)|'
    r'\d+월\s*\d+일.*?(까지|제출|납부)|'
    r'\d+\.\s*\d+\.?\s*\([월화수목금토일]\).*?(까지|제출|납부|등록|시행|운영|개최|진행)|'
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
    re.compile(r'^○|^□|^☐|^■|^▣'),
    re.compile(r'^불참\s*사유\s*[:：]?'),
    re.compile(r'생년월일.*\d|\d.*생년월일'),
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
    r'첨부.*?(제출|작성|작성하여|회신)|'
    r'동의서.*?(작성|제출)'
    r')'
)

DEADLINE = re.compile(
    r'\d+\.?\s*\d+\.?\s*[\(（]?\s*[월화수목금토일]?\s*[\)）]?\s*까지'
)

# B. is_todo=True인데 false여야 할 패턴
GENERAL_CLOSING = re.compile(
    r'(많은|적극적인|지속적인|꾸준한|항상|늘|언제나|진심으로)?\s*'
    r'(관심|협조|참여|성원|격려|이해|동참|배려|응원|배려).*?(부탁|바랍|드립)\s*\.?$'
)

CLOSING_VERBS = re.compile(
    r'(감사드립니다|기원합니다|기원드립니다|드립니다|부탁드립니다)\s*\.?\s*$'
)

EXCLUDE_TODO_PATTERNS = [
    re.compile(r'^제\d+조'),  # 학칙
    re.compile(r'^제\d+장'),
    re.compile(r'\d+[가-힣]\d+-\d+'),  # 성취기준
    re.compile(r'(관찰평가|지필평가|서술평가|수행평가|자기평가|실기평가)'),
    re.compile(r'^https?://\S+\s*$'),
    re.compile(r'^안녕하(십니까|세요)\??\s*$'),
    re.compile(r'^모두가 행복한'),  # 슬로건만
    re.compile(r'^HAPPY\s*&\s*SAFE'),
]


def is_excluded_for_todo(text):
    for p in EXCLUDE_TODO_PATTERNS:
        if p.search(text):
            return True
    return False


def matches_form(text):
    for p in FORM_PATTERNS:
        if p.search(text):
            return True
    return False


# ============== 4갈래 audit ==============
A_false_to_true = defaultdict(list)
B_true_to_false = defaultdict(list)
C_title_false_to_true = []
D_title_true_to_false = []

for i, r in enumerate(rows):
    text = r['text'].strip()
    if not text:
        continue
    is_todo = r.get('is_todo', False)
    is_title = r.get('is_title', False)

    # ===== A: is_todo=False → True 후보 =====
    if not is_todo and not is_title:
        if not is_excluded_for_todo(text):
            if INFO_COLON.match(text) and len(text) < 200:
                A_false_to_true['정보_콜론형'].append((i, text))
            elif matches_form(text):
                A_false_to_true['폼셀'].append((i, text))
            elif DEADLINE.search(text) and len(text) < 200:
                A_false_to_true['마감일'].append((i, text))
            elif ACTION_SPECIFIC.search(text) and len(text) < 250 and not GENERAL_CLOSING.search(text):
                A_false_to_true['구체액션'].append((i, text))
            elif INFO_NATURAL.search(text) and len(text) < 200:
                A_false_to_true['정보_자연어'].append((i, text))

    # ===== B: is_todo=True → False 후보 =====
    if is_todo:
        # 일반 closing — 우리가 이미 잡았어야 하는데 누락된 것
        if GENERAL_CLOSING.search(text) and not (INFO_COLON.match(text) or matches_form(text) or DEADLINE.search(text)):
            B_true_to_false['일반_closing'].append((i, text))
        elif is_excluded_for_todo(text):
            B_true_to_false['명백제외'].append((i, text))
        # 인사말/맺음말 단독
        elif re.match(r'^(학부모님|학생|보호자)?[\s,]*(안녕|반갑|감사|고맙).{0,40}(니까\??|세요\??|드립니다\.?)\s*$', text):
            B_true_to_false['인사말'].append((i, text))

    # ===== C: is_title=False인데 윤정님 룰 통과 =====
    if not is_title and passes_yj_title(text):
        C_title_false_to_true.append((i, text))

    # ===== D: is_title=True인데 윤정님 룰 위반 =====
    if is_title and not passes_yj_title(text):
        D_title_true_to_false.append((i, text))


# ============== dump ==============
with open(DUMP, 'w', encoding='utf-8') as f:
    f.write(f"=== v3_dual_labeled.jsonl 전수 audit ===\n")
    f.write(f"전체 {len(rows)} | todo={cur_todo} | title={cur_title}\n\n")

    f.write("\n" + "="*70 + "\n")
    f.write("[A] is_todo=False → True 후보 (누락된 todo)\n")
    f.write("="*70 + "\n")
    total_a = 0
    for cat in sorted(A_false_to_true.keys()):
        items = A_false_to_true[cat]
        total_a += len(items)
        f.write(f"\n--- {cat}: {len(items)}건 ---\n")
        for i, t in items[:200]:
            f.write(f"  {i}: [{len(t)}자] {t[:140]}\n")
        if len(items) > 200:
            f.write(f"  ... +{len(items)-200}건 더\n")
    f.write(f"\nA 합계: {total_a}건\n")

    f.write("\n\n" + "="*70 + "\n")
    f.write("[B] is_todo=True → False 후보 (잘못 잡힌 todo)\n")
    f.write("="*70 + "\n")
    total_b = 0
    for cat in sorted(B_true_to_false.keys()):
        items = B_true_to_false[cat]
        total_b += len(items)
        f.write(f"\n--- {cat}: {len(items)}건 ---\n")
        for i, t in items[:200]:
            f.write(f"  {i}: [{len(t)}자] {t[:140]}\n")
        if len(items) > 200:
            f.write(f"  ... +{len(items)-200}건 더\n")
    f.write(f"\nB 합계: {total_b}건\n")

    f.write("\n\n" + "="*70 + "\n")
    f.write(f"[C] is_title=False인데 윤정님 룰 통과: {len(C_title_false_to_true)}건\n")
    f.write("="*70 + "\n")
    for i, t in C_title_false_to_true[:300]:
        f.write(f"  {i}: [{len(t)}자] {t[:140]}\n")
    if len(C_title_false_to_true) > 300:
        f.write(f"  ... +{len(C_title_false_to_true)-300}건 더\n")

    f.write("\n\n" + "="*70 + "\n")
    f.write(f"[D] is_title=True인데 윤정님 룰 위반: {len(D_title_true_to_false)}건\n")
    f.write("="*70 + "\n")
    for i, t in D_title_true_to_false[:200]:
        f.write(f"  {i}: [{len(t)}자] {t[:140]}\n")


# 콘솔 요약
print("=== A. is_todo=False → True 후보 (누락) ===")
total_a = sum(len(v) for v in A_false_to_true.values())
for cat in sorted(A_false_to_true.keys()):
    print(f"  {cat}: {len(A_false_to_true[cat])}건")
print(f"  합계: {total_a}\n")

print("=== B. is_todo=True → False 후보 (잘못 잡힘) ===")
total_b = sum(len(v) for v in B_true_to_false.values())
for cat in sorted(B_true_to_false.keys()):
    print(f"  {cat}: {len(B_true_to_false[cat])}건")
print(f"  합계: {total_b}\n")

print(f"=== C. is_title=False → True 후보 (룰 통과인데 누락): {len(C_title_false_to_true)}건")
print(f"=== D. is_title=True → False 후보 (룰 위반): {len(D_title_true_to_false)}건")

print(f"\ndump: {DUMP}")
