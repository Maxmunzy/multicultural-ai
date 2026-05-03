"""is_todo=False 전수조사 — 윤정님 정의에 해당하는 누락 todo 찾기.

윤정님 정의 (sample.jsonl 기반):
- 정보: 일시/시간/장소/대상/기간/비용/금액/준비물/복장/일정/방법/인출/납부/마감/연락처/문의/등록/모집/접수
- 폼 셀: (인), (서명), 학년/반/번호/이름, 빈 괄호, 체크 항목
- 액션: 제출/납부/회신/연락/확인/문의/협의/체크/기재/이체/입금/등록/제공/보내주시기/주시기 바랍니다 (단 closing 제외)
- 마감일/시점: "MM월 DD일까지", "YYYY-MM-DD"

전수 스캔 후 후보를 카테고리별로 dump.
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DUMP = Path('C:/Users/ashle/AppData/Local/Temp/missing_todos_scan.txt')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_todo = sum(1 for r in rows if r.get('is_todo'))
print(f"시작: 전체 {len(rows)} | is_todo=True {before_todo} | False {len(rows)-before_todo}\n")


# ============== 누락 후보 패턴 ==============

# 1. 정보 콜론형 (이미 일부 잡혔지만 더 넓은 키워드로)
INFO_COLON = re.compile(
    r'^\s*[\d가-힣]?\s*[\.\)]?\s*('
    r'일\s*시|시\s*간|장\s*소|대\s*상|기\s*간|비\s*용|금\s*액|연락처|주\s*소|전\s*화|문\s*의|운영\s*시간|모집\s*인원|복\s*장|준비물|일\s*정|인\s*출|납\s*부|수\s*납|참\s*가|행사|예상\s*경비|예상경비|소요\s*경비|행사명|운영\s*기간|모집\s*기간|접수\s*기간|신청\s*기간|체험\s*비용|행사\s*내용|마감일|마감\s*일|사용\s*기간|발송\s*일|제출\s*일|방법|시작\s*일|종료\s*일|운영\s*방식|진행\s*방식|운영\s*장소|진행\s*장소|진행\s*시간|회비|단체명|성명|학교명|학년|반|번|이름|생년월일|자녀\s*이름'
    r')\s*[:：]'
)

# 2. 정보 비콜론형 (자연어 + 핵심 정보)
INFO_NATURAL = re.compile(
    r'(까지\s*(제출|납부|회신|보내|작성|등록|이체|신청|접수)|'
    r'\d+월\s*\d+일.*?(까지|제출|납부)|'
    r'\d+\.\s*\d+\.?\s*\([월화수목금토일]\).*?(까지|제출|납부|등록|시행|운영|개최|진행)|'
    r'(스쿨뱅킹|계좌이체|통장|카드|자동이체|현금)\s*(납부|이체|입금|결제))'
)

# 3. 폼 셀 (다양한 형태)
FORM_PATTERNS = [
    re.compile(r'\(\s*\)\s*(반|번|학년|이름|성명|일|월)'),
    re.compile(r'(인|서명|성명|관계)\s*[:：]?\s*\(\s*인\s*\)'),
    re.compile(r'학부모\s*[:：]?\s*\(\s*(인|서명)'),
    re.compile(r'보호자\s*[:：]?\s*\(\s*(인|서명)'),
    re.compile(r'\(\s*\)\s*불참'),
    re.compile(r'참가\s*\(\s*\)\s*불참'),
    re.compile(r'참석\s*\(\s*\)'),
    re.compile(r'동의\s*\(\s*\)\s*(미\s*동의|아니|반대)'),
    re.compile(r'\d+\s*학년\s*\(\s*\)\s*반'),
    re.compile(r'반\s*\(\s*\)\s*번'),
    re.compile(r'^\d+학년\s*\(\s*\)반\s*\(\s*\)번\s*이름'),
    re.compile(r'^.{0,8}성명\s*[:：]?\s*\(.*\)'),
    re.compile(r'^불참\s*사유\s*[:：]?'),
    re.compile(r'^.{0,15}자녀\s*(이름|성명)\s*[:：]'),
    re.compile(r'생년월일.*\d|\d.*생년월일'),
    re.compile(r'(예|아니요|동의|미동의)\s*[:：]?\s*\(\s*\)'),
    re.compile(r'^○|^□|^☐|^■|^▣'),  # 체크박스
    re.compile(r'^희망\s*(여부|사항)\s*[:：]'),
    re.compile(r'^.{0,15}\(\s*\)\s*(희망|미희망|찬성|반대|예|아니)'),
]

# 4. 구체 액션 (closing 제외)
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
    r'동의서.*?(작성|제출)|'
    r'(연락|문의)\s*(처|망|드립니다|주시기\s*바랍니다)\s*[:：]?\s*\d'
    r')'
)

# 5. 마감 관련 (날짜 + 행동)
DEADLINE = re.compile(
    r'\d+\.?\s*\d+\.?\s*[\(（]?\s*[월화수목금토일]?\s*[\)）]?\s*까지'
)

# closing 제외 (이전 룰에서 false로 변환된 것들 — 다시 잡지 말 것)
CLOSING_EXCLUDE = re.compile(
    r'(부탁드립니다|기원합니다|감사드립니다|감사합니다|드립니다)\s*\.?\s*$'
)
GENERAL_CLOSING = re.compile(
    r'(많은|적극적인|지속적인|꾸준한|꾸준히|항상|늘|언제나)\s*'
    r'(관심|협조|참여|성원|격려|이해|동참|배려|응원).*?(부탁|바랍|드립)'
)

# 명백히 todo 아님 (학칙/평가/단원/슬로건 등)
EXCLUDE_PATTERNS = [
    re.compile(r'^제\d+조'),
    re.compile(r'^제\d+장'),
    re.compile(r'\d+[가-힣]\d+-\d+'),
    re.compile(r'(관찰평가|지필평가|서술평가|수행평가|자기평가|실기평가)'),
    re.compile(r'^https?://\S+\s*$'),  # URL 단독
    re.compile(r'^안녕하(십니까|세요)\??\s*$'),
    re.compile(r'^항상.*감사드립니다\.?\s*$'),
    re.compile(r'^.*기원합니다\.?\s*$'),
    re.compile(r'^모두가 행복한.{0,30}학교\s*$'),
    re.compile(r'^HAPPY\s*&\s*SAFE\s*SCHOOL\s*$'),
]


def is_excluded(text):
    for p in EXCLUDE_PATTERNS:
        if p.search(text):
            return True
    return False


def matches_form(text):
    for p in FORM_PATTERNS:
        if p.search(text):
            return True
    return False


# ============== 전수 스캔 ==============
candidates = defaultdict(list)

for i, r in enumerate(rows):
    if r.get('is_todo'):
        continue  # 이미 True
    if r.get('is_title'):
        continue  # title은 제외 (윤정님 룰: title=True면 todo=False 강제)

    text = r['text'].strip()
    if not text or is_excluded(text):
        continue

    # closing/general은 제외
    if CLOSING_EXCLUDE.search(text) and GENERAL_CLOSING.search(text):
        continue

    # 카테고리별 매칭
    matched = []
    if INFO_COLON.match(text) and len(text) < 200:
        matched.append('정보_콜론형')
    if INFO_NATURAL.search(text) and len(text) < 200:
        matched.append('정보_자연어')
    if matches_form(text):
        matched.append('폼셀')
    if ACTION_SPECIFIC.search(text) and len(text) < 250 and not GENERAL_CLOSING.search(text):
        matched.append('구체액션')
    if DEADLINE.search(text) and len(text) < 200:
        matched.append('마감일')

    if matched:
        # 우선순위: 폼 > 정보_콜론 > 마감 > 구체액션 > 정보_자연어
        cat = matched[0]
        for c in ['폼셀', '정보_콜론형', '마감일', '구체액션', '정보_자연어']:
            if c in matched:
                cat = c
                break
        candidates[cat].append((i, text))


# ============== dump ==============
with open(DUMP, 'w', encoding='utf-8') as f:
    f.write(f"is_todo=False 행 {len(rows) - before_todo}개 중 누락 todo 후보\n\n")
    total = 0
    for cat in sorted(candidates.keys()):
        items = candidates[cat]
        f.write(f"\n{'='*60}\n[{cat}] {len(items)}건\n{'='*60}\n")
        total += len(items)
        for i, t in items[:300]:
            f.write(f"  {i}: [{len(t)}자] {t[:140]}\n")
        if len(items) > 300:
            f.write(f"  ... +{len(items)-300}건 더\n")
    f.write(f"\n\n=== 총 후보: {total}건 ===\n")

# 콘솔 요약
print("=== 누락 todo 후보 (전수 스캔) ===")
total = 0
for cat in sorted(candidates.keys()):
    print(f"  {cat}: {len(candidates[cat])}건")
    total += len(candidates[cat])
print(f"\n총 {total}건 후보 발견")
print(f"dump: {DUMP}")
