"""
is_todo_label.py
================
v3.1_dual_labeled.jsonl → v3.2_dual_labeled.jsonl
새 프롬프트 기준으로 is_todo 를 재라벨링. is_title 필드는 그대로 유지.

[판별 순서]
  1. is_title=True  → 제목 전용 규칙 (액션형/일정형 → True, 공지형 → False)
  2. FALSE 조건 체크 (노이즈 조기 제거)
  3. TRUE 조건 OR 체크 (7개 카테고리)
  4. 기본값 False

[TRUE 카테고리 (is_title=False 문장)]
  CAT1. 일정 : 일시·장소 헤더, 날짜+행사 키워드, 우천 변경, 주요 학사 일정
  CAT2. 준비물: 지참물 목록, 복장, 반입 금지
  CAT3. 제출  : 신청서/동의서 제출·작성, 서명/날인, 설문 응답
  CAT4. 비용  : 납부 금액, CMS·자동이체, 입금 계좌, 수익자 부담 경비
  CAT5. 건강·안전: 마스크 착용, 발열 체크, 등교 금지, 안전 지침
  CAT6. 기타  : 급식 여부, 도시락, 방과후/돌봄 신청, 봉사자 모집
  CAT7. 요청  : 요청형 종결 어미 (해주세요·바랍니다·하십시오 등)

[FALSE 조건]
  F1. 표 헤더 — 단독 단어 (항목/구분/성명 등)
  F2. 숫자·기호만 있는 줄, 세부 타임테이블 (HH:MM–HH:MM)
  F3. 발신일·발신자·연락처·주소
  F4. 의례적 인사말 (안녕하십니까, 기원합니다 등)
  F5. 행사 취지·교육 효과·배경 설명
  F6. 학교·교사 수행 행동 (본교·담임 주어 + 완결 서술)
  F7. 개인정보 수집·처리 방침 안내

[제목(is_title=True) 전용 규칙]
  True  : 액션형 (신청/납부/제출/조사/모집) · 일정형 (재량휴업/단축수업/조기하교)
  False : 공지형 (그 외 X 안내 — 체육대회 안내, 여름방학 안내 등)

[CLI 사용법]
  python file/is_todo_label.py
  python file/is_todo_label.py --input  model/extraction/data/train/v3.1_dual_labeled.jsonl \\
                                --output model/extraction/data/train/v3.2_dual_labeled.jsonl
  python file/is_todo_label.py --with_reason
"""

import argparse
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_DEFAULT_INPUT  = Path("model/extraction/data/train/v3.1_dual_labeled.jsonl")
_DEFAULT_OUTPUT = Path("model/extraction/data/train/v3.1.1_dual_labeled.jsonl")


# ─────────────────────────────────────────────────────────────────────────────
# 제목(is_title=True) 전용 패턴
# ─────────────────────────────────────────────────────────────────────────────

# 액션형·일정형 제목 → is_todo=True
# 액션형: 신청/납부/제출/모집/조사 등 직접 행동 명사 포함
# 일정형: 재량휴업·단축수업·조기하교 — 학부모가 스케줄 조정 필요
_TITLE_TRUE_RE = re.compile(
    r"(신청|납부|제출|모집|조사|접수|등록|희망|수납)\s*(서|안내|방법)?\s*$"
    r"|납부\s*안내|신청\s*안내|모집\s*안내|접수\s*안내|수납\s*안내"
    r"|방과후\s*(신청|안내|등록)|돌봄\s*(신청|안내|교실)"
    r"|재량\s*휴업(일)?"
    r"|단축\s*수업"
    r"|조기\s*하교"
    r"|임시\s*공휴일"
)


# ─────────────────────────────────────────────────────────────────────────────
# FALSE 조건 패턴
# ─────────────────────────────────────────────────────────────────────────────

# F1: 표 헤더 — 줄 전체가 단독 단어(카테고리 레이블)인 경우
_F1_TABLE_HEADER = re.compile(
    r"^(항목|구분|내용|기간|장소|대상|날짜|비용|금액|시간|방법|신청|담당|비고|"
    r"순번|번호|학년|반|번|성명|이름|연락처|주소|이메일|합계|소계|계|일정|"
    r"현황|결과|상태|여부|구성|세부|일자|기준|이유|사유|비율|운영|참가비|"
    r"내역|절차|기타|첨부|서식|붙임|총계|소요|지역|유의|참고|확인|대기)\s*$"
)

# F2-a: 숫자·기호만 있는 줄, 소제목 단독 줄
_F2_NOISE_LINE = re.compile(
    r"^[\d①②③④⑤⑥⑦⑧⑨⑩]+[.)]\s*$"
    r"|^[가나다라마바사아자차카타파하][.)]\s*$"
    r"|^[A-Za-z][.)]\s*$"
    r"|^[-─━=*○●◎]{3,}\s*$"
)

# F2-b: 세부 타임테이블 — HH:MM - HH:MM 범위로 시작하는 프로그램 세부 일정
_F2_TIMETABLE = re.compile(
    r"^\d{1,2}:\d{2}\s*[-~–]\s*\d{1,2}:\d{2}"
)

# F3: 발신일·발신자명·연락처·주소
_F3_SENDER_INFO = re.compile(
    r"^\d{4}\s*[.년]\s*\d{1,2}\s*[.월]\s*\d{1,2}\s*[.일]?\s*$"
    r"|(초등학교|중학교|고등학교|특수학교)\s*장\s*$"
    r"|교육감\s*$|교육장\s*$|교육지원청\s*$"
    r"|^Tel\s*[.:：]|^FAX\s*[.:：]|^전화\s*[.:：]|^팩스\s*[.:：]"
    r"|^\(?\d{2,3}\)?\s*\d{3,4}-\d{4}\s*$"
    r"|(서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|"
    r"전북|전남|경북|경남|제주).{0,20}(로|길)\s*\d+"
)

# F4: 의례적 인사말·결어 (안녕하십니까, 기원합니다, 감사드립니다 등)
_F4_GREETING = re.compile(
    r"^학부모님\s*안녕하(십니까|세요)"
    r"|^안녕하(십니까|세요)"
    r"|기원합니다\s*\.?\s*$"
    r"|건강하시길\s*(바랍니다|기원합니다)"
    r"|행복하시길\s*(바랍니다|기원합니다)"
    r"|^학부모님께\s*(안내드립니다|드립니다|말씀드립니다)"
    r"|안내드립니다\s*\.?\s*$"
    r"|말씀드립니다\s*\.?\s*$"
    r"|드리겠습니다\s*\.?\s*$"
    r"|(초등학교|중학교|고등학교)\s*장\s*$"
    r"|공익제보센터|자살예방상담|청소년상담"
    r"|(좋은|건강한|즐거운).{0,20}(되시길|되길|되기를)\s*(바랍니다|기원합니다)"
    # 감사·결어
    r"|감사드립니다\s*\.?\s*$"
    r"|감사합니다\s*\.?\s*$"
    r"|(평안|편안).{0,20}(바랍니다|기원합니다)\s*\.?\s*$"
    r"|댁내.{0,20}(바랍니다|기원합니다)\s*\.?\s*$"
    # 추상적 참여·협조 요청 (구체적 액션 없음)
    r"|많은\s*(관심|협조|성원|참여|응원).{0,20}(부탁드립니다|감사드립니다|바랍니다)\s*\.?\s*$"
    r"|(관심|협조|성원).{0,10}(부탁드립니다|감사드립니다)\s*\.?\s*$"
)

# F5: 행사 취지·교육 효과·배경 설명 (학교가 왜 하는지 서술)
_F5_BACKGROUND = re.compile(
    r"취지\s*(는|로|를|에서)"
    r"|기대\s*효과|교육적\s*효과|운영\s*방침"
    r"|지원하기\s*위해|도모하(고자|기\s*위해|여)"
    r"|증진하(고자|기\s*위해)|향상시키(고자|기\s*위해)"
    r"|강화하기\s*위해|이번에\s*마련"
    r"|목적\s*(은|는|으로|에서)\s*.{0,30}(합니다|입니다)"
)

# F6: 학교·교사 수행 행동 (본교·담임 주어 + 완결 서술)
_F6_SCHOOL_ACTION = re.compile(
    r"(본교|학교|담임|교사|선생님|교장|교감|행정실|교육청|교육부).*?"
    r"(실시합니다|운영합니다|진행합니다|제공합니다|지원합니다|"
    r"예정입니다|계획합니다|마련합니다|추진합니다|안내합니다|지도합니다)"
    r"|(실시할\s*예정|운영할\s*예정|진행할\s*예정|제공할\s*예정)\s*입니다"
)

# F7: 개인정보 수집·처리 방침 안내
_F7_PRIVACY = re.compile(
    r"수집\s*(목적|항목|근거)|보유\s*(기간|이용\s*기간)"
    r"|개인정보\s*(처리|수집|보호|열람|이용)|처리\s*방침"
    r"|제3자\s*제공|정보\s*주체|위탁\s*처리|수집\s*이용\s*동의"
)

_FALSE_CHECKS: list[tuple[re.Pattern, str]] = [
    (_F1_TABLE_HEADER,  "F1_table_header"),
    (_F2_NOISE_LINE,    "F2_noise_line"),
    (_F2_TIMETABLE,     "F2_timetable"),
    (_F3_SENDER_INFO,   "F3_sender_info"),
    (_F4_GREETING,      "F4_greeting"),
    (_F5_BACKGROUND,    "F5_background"),
    (_F6_SCHOOL_ACTION, "F6_school_action"),
    (_F7_PRIVACY,       "F7_privacy"),
]


# ─────────────────────────────────────────────────────────────────────────────
# TRUE 조건 패턴 (7개 카테고리)
# ─────────────────────────────────────────────────────────────────────────────

# CAT1: 일정 — 일시·장소 헤더, 날짜+행사, 우천 변경, 주요 학사 일정
_CAT1_SCHEDULE = re.compile(
    # 일시·장소 등 일정 관련 헤더 (^ 앵커 제거 → "3. 장소: ..." 형태도 허용)
    r"(일시|날짜|장소|집합\s*장소|집합\s*시각|집합\s*시간|"
    r"출발\s*시각|귀교\s*시각|귀가\s*시각|행사\s*일시|행사\s*장소|"
    r"설문\s*기간|신청\s*기간|접수\s*기간|참여\s*기간|대회\s*일시)\s*[:：]"
    # 우천 시 변경·취소 안내
    r"|우천\s*시\s*(변경|취소|대체|장소|일정)"
    # 날짜 + 주요 행사 키워드 (앞에 날짜)
    r"|(\d+\s*월\s*\d+\s*일|\d+\.\s*\d+\.?)\s*.{0,40}"
    r"(휴업일|재량\s*휴업|개교기념일|수련|소풍|운동회|체험학습|"
    r"수학여행|방학|개학|입학식|졸업식|공휴일|임시\s*공휴일|단축수업|조기하교|"
    r"행사일|발표회|음악회|연수|캠프|체육대회)"
    # 날짜 + 주요 행사 키워드 (뒤에 날짜)
    r"|(휴업일|재량\s*휴업|개교기념일|수련|소풍|운동회|체험학습|"
    r"수학여행|방학|개학|입학식|졸업식|공휴일|임시\s*공휴일|단축수업|조기하교|"
    r"발표회|음악회|캠프|체육대회)"
    r".{0,40}(\d+\s*월\s*\d+\s*일|\d+\.\s*\d+\.?)"
    # 학부모가 직접 참여하는 행사 (수업공개·총회·설명회 등) — F2 예외와 연계
    r"|학부모\s*(수업\s*공개|공개\s*수업|총회|설명회|간담회|연수|참여|상담|줄다리기)"
    r"|\d{1,2}:\d{2}\s*[-~–]\s*\d{1,2}:\d{2}.{0,30}학부모"
    # 일자: 헤더, 운영시간: 헤더
    r"|일자\s*[:：]"
    r"|운영\s*시간\s*[:：]"
)

# CAT2: 준비물 — 지참물 목록, 복장 지침, 반입 금지 안내
_CAT2_SUPPLIES = re.compile(
    # 준비물·지참물 헤더 (^ 제거 → "6. 준비물:" 같은 숫자 prefix 허용)
    r"(준비물|지참물|준비\s*사항|지참\s*사항)\s*[:：]"
    # 지참 요청 표현
    r"|지참\s*(해주세요|바랍니다|하세요|하시기|하십시오)"
    r"|챙겨\s*(주세요|오세요|오시기|주시기)"
    r"|가져(와야|올)\s*(할|것|주세요)"
    # 구체적 지참 물품 + 행동 동사
    r"|(실내화|도시락|물병|우산|운동복|체육복|필기구|모자|선크림|보호대|"
    r"돗자리|구명조끼|여벌\s*옷)\s*(을|를)?\s*(준비|지참|챙겨)"
    # 반입 금지·복장 안내
    r"|반입\s*(금지|제한|불가)"
    r"|복장\s*[:：]|복장\s*(안내|기준|규정)"
    r"|체육복\s*(착용|입고|준비)"
    r"|개인\s*(물품|용품)\s*(준비|지참)"
)

# CAT3: 제출 — 신청서/동의서 제출, 서명/날인, 설문 응답
_CAT3_SUBMISSION = re.compile(
    # 신청·참여·제출·귀가·검진 방법 헤더 (번호 prefix 있어도 허용)
    r"(신청|참여|제출|접수|응시|설문|귀가|검진|확인)\s*방법\s*[:：]"
    r"|(신청|참여|접수)\s*링크\s*[:：]"
    # 참석·불참 체크 형식
    r"|참석\s*(또는|혹은)\s*불참"
    # 서류 + 제출 동사
    r"|(신청서|동의서|참가서|확인서|설문지|조사지|동의란)\s*(을|를)?\s*(제출|작성|반환|회신|보내|완료|내주)"
    # 마감 기한 + 액션
    r"|(제출|납부|작성|회신|신청|등록|입금|보내)\s*.{0,30}(까지|기한\s*내|마감)"
    r"|(까지|기한\s*내|마감일?)\s*.{0,30}(제출|납부|작성|회신|신청|등록|입금)"
    # 날짜 + 제출 액션
    r"|\d+\s*[.월]\s*\d+\s*일?.{0,20}(제출|납부|신청|등록|입금|회신)"
    r"|(제출|납부|신청|등록|입금|회신).{0,20}\d+\s*[.월]\s*\d+\s*일?"
    # 서명·날인·체크박스
    r"|보호자\s*(성명|이름|서명|확인|날인|도장)"
    r"|학부모\s*(성명|이름|서명|확인|날인)"
    r"|서명\s*란|날인\s*란|확인\s*란"
    r"|□\s*(예|아니오|동의|참|불참|해당|미해당|확인)"
    r"|\(\s*(예|아니오|동의|미동의|해당|미해당|참|불참)\s*\)"
    # 온라인 신청·설문
    r"|설문\s*(조사|응답|참여|링크)"
    r"|QR\s*(코드)?\s*(스캔|접속|참여)"
    r"|온라인\s*(신청|접수|동의|제출)"
)

# CAT4: 비용 — 납부 금액, CMS·자동이체, 입금 계좌, 수익자 부담 경비
_CAT4_COST = re.compile(
    # 비용 헤더 (번호 prefix 있어도 허용)
    r"(소요|참가|교육|체험|현장)\s*경비\s*[:：]"
    r"|(비용|금액|경비|수납액|참가비|교육비)\s*[:：]"
    # 납부 기간·이체 예정일 헤더
    r"|(납부|이체|출금|결제)\s*(기간|예정일)\s*[:：]"
    # 수강료·교재비·재료비 + 금액 (방과후 비용 안내)
    r"|(수강료|교재비|재료비).{0,40}\d+[,\d]*\s*원"
    # 납부 관련
    r"|납부\s*(금액|방법|기한|일|해주|하시|바랍니다)"
    r"|(현장|현금|카드)\s*(납부|결제|수납)"
    # CMS·자동이체
    r"|CMS\s*(자동이체|납부|출금|신청|확인)"
    r"|자동이체\s*(신청|확인|등록|동의|잔액)"
    # 입금·계좌
    r"|입금\s*(계좌|방법|기한|해주|하시)"
    r"|계좌\s*(번호|이체|이름|입금)"
    # 금액 명시
    r"|\d+\s*(원|만원)\s*(납부|입금|결제|이체)"
    r"|참가비\s*[:：]"
    # 수익자 부담 — True 카테고리 (F6_INFO_ONLY와 달리 명시적 True)
    r"|수익자\s*부담\s*(경비|금액|비용)"
    # 잔액 확인 요청
    r"|통장\s*(잔액|이체|확인)\s*(바랍니다|해주세요|부탁드립니다|확인)?"
    r"|잔액\s*(확인|부족)"
)

# CAT5: 건강·안전 — 마스크, 발열, 등교 금지, 안전 지침
_CAT5_SAFETY_HEALTH = re.compile(
    r"마스크\s*(착용|필착|꼭\s*착용|써\s*주세요)"
    r"|발열\s*(체크|확인|시\s*등교\s*금지|있을\s*경우)"
    r"|손\s*(씻기|소독|위생)|체온\s*측정"
    r"|등교\s*(금지|중지)|격리\s*(해주세요|바랍니다|기간)"
    r"|(안전|주의)\s*(해\s*주세요|바랍니다|지켜\s*주세요|사항)"
    r"|식중독\s*(예방|증상)|보호대\s*(착용|필착)"
    r"|응급\s*(처치|연락|상황)|긴급\s*연락처"
    r"|안전\s*(교육|수칙|지도|사고\s*예방|점검)"
    r"|건강\s*(이상|확인|상태)\s*(시|있을\s*경우)"
    # 건강검진 보호자 관련
    r"|보호자\s*(동반|동행)"
    r"|이상\s*(소견|자).{0,30}(병원|검진|치료|진료|방문)"
    r"|정밀\s*(검사|검진)"
    r"|(검사|검진).{0,30}금식"
    r"|치료비.{0,15}(본인|부모|가정)\s*부담"
    # 학부모가 자녀에게 지도해야 할 안전 금지 규칙
    r"|(킥보드|자전거|오토바이).{0,30}(등교\s*금지|탑승\s*금지|이용\s*금지|하지\s*않기)"
    r"|(혼자\s*)?(수영|물놀이)\s*(금지|하지\s*마|않기)"
    r"|불장난\s*(하지|않기|금지)"
    r"|금품.{0,20}(제공하지|전달하지|주지)\s*(않기|마십시오|않겠습니다)"
)

# CAT6: 기타 — 급식 여부, 도시락, 방과후/돌봄 신청, 봉사자 모집
_CAT6_MISC = re.compile(
    # 급식 "운영" 제거 — "급식 운영에 대한 관심 감사드립니다" 같은 결어 오탐 방지
    r"급식\s*(여부|없음|있음|신청|미제공|없이|중단|기간|미실시|제공\s*(여부|없음|있음))"
    r"|도시락\s*(준비|지참|필요|지참해|싸주|지참하)"
    r"|방과후\s*(신청|등록|수업|프로그램|학교)"
    r"|돌봄\s*(신청|교실|서비스|운영|이용)"
    r"|봉사자?\s*(모집|신청|참여|필요)"
    r"|결석\s*(확인서|신고서)\s*(제출|필요)"
)

# CAT7: 요청형 종결 어미 — 학부모 대상 직접 요청
_CAT7_REQUEST = re.compile(
    r"(해주세요|해\s*주세요|하세요)\s*\.?\s*$"
    r"|(주시기\s*바랍니다|바랍니다)\s*\.?\s*$"
    r"|(해주시기\s*바랍니다|하시기\s*바랍니다)\s*\.?\s*$"
    r"|(부탁드립니다|부탁\s*드립니다)\s*\.?\s*$"
    r"|(해주십시오|하십시오)\s*\.?\s*$"
    r"|(해주시길\s*바랍니다|하여\s*주시기\s*바랍니다)\s*\.?\s*$"
    r"|확인\s*(후\s*)?(서명|날인|제출|반환|부탁)\s*\.?\s*$"
    r"|회신\s*(해주세요|바랍니다|부탁드립니다)\s*\.?\s*$"
    r"|동의\s*(해주시기|하시면|체크|서명|란에|란을)"
)

_TRUE_CHECKS: list[tuple[re.Pattern, str]] = [
    (_CAT1_SCHEDULE,      "CAT1_schedule"),
    (_CAT2_SUPPLIES,      "CAT2_supplies"),
    (_CAT3_SUBMISSION,    "CAT3_submission"),
    (_CAT4_COST,          "CAT4_cost"),
    (_CAT5_SAFETY_HEALTH, "CAT5_safety_health"),
    (_CAT6_MISC,          "CAT6_misc"),
    (_CAT7_REQUEST,       "CAT7_request"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

def label_with_reason(text: str, is_title: bool = False) -> tuple[bool, str]:
    """(is_todo, reason) 반환. reason 은 매칭된 패턴 코드 또는 'no_match'."""
    text = text.strip()
    if len(text) < 4:
        return False, "too_short"

    if is_title:
        if _TITLE_TRUE_RE.search(text):
            return True, "TITLE_action_schedule"
        return False, "TITLE_announcement"

    for pat, reason in _FALSE_CHECKS:
        if pat.search(text):
            # F2_timetable 예외: 학부모가 직접 참여하는 행사 시간표는 True
            if reason == "F2_timetable" and "학부모" in text:
                continue
            # F3_sender_info 예외: 장소 헤더에 주소가 포함된 경우는 True
            if reason == "F3_sender_info" and re.search(
                r"(장소|체험\s*장소|집합\s*장소|오디션\s*장소|시험\s*장소)\s*[:：]", text
            ):
                continue
            # F7_privacy 예외: 제출 기한이 함께 있으면 학부모 행동 필요 → True
            if reason == "F7_privacy" and _CAT3_SUBMISSION.search(text):
                return True, "CAT3_submission_override_F7"
            return False, reason

    for pat, reason in _TRUE_CHECKS:
        if pat.search(text):
            return True, reason

    return False, "no_match"


def label_sentence(text: str, is_title: bool = False) -> bool:
    """is_todo 라벨만 반환. True=할 일·핵심 정보, False=노이즈."""
    return label_with_reason(text, is_title)[0]


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _run_cli() -> None:
    parser = argparse.ArgumentParser(
        description="JSONL 파일의 is_todo 를 새 기준(v3.2)으로 재라벨링 — is_title 필드 유지"
    )
    parser.add_argument("--input",  type=Path, default=_DEFAULT_INPUT,  help="입력 JSONL 파일")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT, help="출력 JSONL 파일")
    parser.add_argument(
        "--with_reason", action="store_true",
        help="label_reason 필드를 출력에 포함 (검수용)"
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[오류] 파일 없음: {args.input}", file=sys.stderr)
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    total = true_cnt = false_cnt = 0
    title_true = title_false = 0
    reason_counter: dict[str, int] = {}

    with args.input.open(encoding="utf-8") as fin, \
         args.output.open("w", encoding="utf-8") as fout:

        for raw in fin:
            raw = raw.strip()
            if not raw:
                continue
            obj      = json.loads(raw)
            text     = obj.get("text", "")
            is_title = bool(obj.get("is_title", False))

            is_todo, reason = label_with_reason(text, is_title)
            obj["is_todo"]  = is_todo
            if args.with_reason:
                obj["label_reason"] = reason

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")

            total += 1
            if is_todo:
                true_cnt += 1
            else:
                false_cnt += 1
            if is_title:
                if is_todo: title_true  += 1
                else:       title_false += 1
            reason_counter[reason] = reason_counter.get(reason, 0) + 1

    print(f"\n처리 완료: {total}개 문장")
    print(f"  is_todo=True  (할 일) : {true_cnt:>6}  ({true_cnt/total*100:.1f}%)")
    print(f"  is_todo=False (노이즈): {false_cnt:>6}  ({false_cnt/total*100:.1f}%)")
    title_total = title_true + title_false
    if title_total:
        print(f"\n제목 문장 ({title_total}개):")
        print(f"  액션형·일정형 (True) : {title_true:>5}  ({title_true/title_total*100:.1f}%)")
        print(f"  공지형       (False): {title_false:>5}  ({title_false/title_total*100:.1f}%)")
    print(f"\n매칭 이유 분포 (상위 12):")
    for reason, cnt in sorted(reason_counter.items(), key=lambda x: -x[1])[:12]:
        print(f"  {reason:<30} {cnt:>6}회")
    print(f"\n저장: {args.output}")


if __name__ == "__main__":
    _run_cli()
