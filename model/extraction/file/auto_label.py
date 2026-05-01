"""
auto_label.py
=============
가정통신문 문장에 is_todo 초안 라벨을 규칙 기반으로 부여.

[판정 순서]
  1. FALSE 조건 먼저 체크 — 확실한 노이즈를 조기 제거
  2. TRUE 조건 OR 체크   — 하나라도 해당하면 True
  3. 기본값 False

[TRUE 조건 (OR)]
  T1. 명확한 마감일 + 액션 동사 (제출/납부/작성/회신 등)
  T2. 양식의 작성 칸 (보호자 성명, 불참 사유, 체크박스 등)
  T3. 구체적 준비물 목록
  T4. 안전·건강 지침 (행동 권고)
  T5. 일정 인지 (날짜 동반 필수 — 표 헤더 제외)
  T6. 학부모 직접 액션 (잔액 확인, 동의 체크, CMS 등)
  T7. 요청형 종결 어미 (해주세요·바랍니다·하십시오 등)

[FALSE 조건]
  F1. 표 헤더/구분자 (단독 단어 형태)
  F2. 소제목/번호만 있는 라인
  F3. 발신일/발신자명/연락처/주소
  F4. 양식 안내문 (개인정보 수집 목적, 보유 기간 등)
  F5. 인사말/서명 (안내드립니다, 말씀드립니다 등)
  F6. 정보 안내 (총액·지원금 구성·환불 규정)
  F7. 운영 방침/취지/기대 효과 설명
  F8. 학교 측 수행 행동 (학교·교사 주어 + 설명 동사)

[사용법 — 모듈]
  from auto_label import label_sentence, label_with_reason
  label_sentence("5월 31일까지 동의서를 제출해주세요.")   # True
  label_with_reason("운동회는 5월 10일입니다.")           # (True, "T5_schedule")

[사용법 — CLI]
  python file/auto_label.py --input data/v3_school.jsonl --output data/v3_labeled.jsonl
  python file/auto_label.py --input data/v3_school.jsonl --output data/v3_labeled.jsonl --with_reason
"""

import argparse
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# FALSE 조건 패턴
# ─────────────────────────────────────────────────────────────────────────────

# F1: 표 헤더/구분자 — 단독 단어 형태 (줄 전체가 카테고리 레이블인 경우)
_F1_TABLE_HEADER = re.compile(
    r"^(항목|구분|내용|기간|장소|대상|날짜|비용|금액|시간|방법|신청|담당|비고|"
    r"순번|번호|학년|반|번|성명|이름|연락처|주소|이메일|합계|소계|계|일정|"
    r"현황|결과|상태|여부|구성|세부|일자|기준|이유|사유|비율|운영|참가비|"
    r"내역|항목|절차|기타|첨부|서식|붙임)\s*$"
)

# F2: 소제목/번호만 있는 라인 (내용 없이 번호·기호만 존재)
_F2_SUBTITLE_ONLY = re.compile(
    r"^[\d①②③④⑤⑥⑦⑧⑨⑩]+[.)]\s*$"        # 숫자/원형숫자만
    r"|^[가나다라마바사아자차카타파하][.)]\s*$"   # 가나다... 단독
    r"|^[A-Za-z][.)]\s*$"                     # 알파벳 단독
)

# F3: 발신일/발신자명/연락처/주소
_F3_SENDER_INFO = re.compile(
    r"^\d{4}\s*[.년]\s*\d{1,2}\s*[.월]\s*\d{1,2}\s*[.일]?\s*$"   # 날짜만
    r"|(초등학교|중학교|고등학교|특수학교)\s*장\s*$"                # 교장 서명
    r"|교육감\s*$|교육장\s*$|교육지원청\s*$"
    r"|^Tel\s*[.:：]|^FAX\s*[.:：]|^전화\s*[.:：]|^팩스\s*[.:：]"  # 연락처 전용
    r"|^\(?\d{2,3}\)?\s*\d{3,4}-\d{4}\s*$"                       # 전화번호만
    r"|(서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|"
    r"전북|전남|경북|경남|제주).{0,20}(로|길)\s*\d+"               # 도로명 주소
)

# F4: 양식 안내문 (개인정보 수집·보유 기간 등)
_F4_FORM_GUIDANCE = re.compile(
    r"수집\s*(목적|항목|근거|동의\s*여부)|보유\s*(기간|이용\s*기간)"
    r"|개인정보\s*(처리|수집|보호|열람|이용)|처리\s*방침"
    r"|제3자\s*제공|정보\s*주체|위탁\s*처리|수집\s*이용\s*동의"
)

# F5: 인사말·안내 결어·서명 (predict.py _NON_TODO_PATTERNS 와 동기화)
_F5_GREETING_SIGN = re.compile(
    r"^학부모님\s*안녕하(십니까|세요)"
    r"|^안녕하(십니까|세요)"
    r"|^.*님\s*안녕하(세요|십니까)"
    r"|^학부모님께\s*(안내드립니다|드립니다)"
    r"|안내드립니다\s*\.?\s*$"
    r"|말씀드립니다\s*\.?\s*$"
    r"|드리겠습니다\s*\.?\s*$"
    r"|공익제보센터|자살예방상담|청소년상담"
    r"|(초등학교|중학교|고등학교)\s*장\s*$"   # 서명란
)

# F6: 정보 안내 (총액·지원금 구성·환불 규정)
_F6_INFO_ONLY = re.compile(
    r"환불\s*(규정|정책|기준|불가)|총액\s*[:：]|총\s*비용\s*[:：]"
    r"|지원금\s*(구성|항목|내역|산출)|예산\s*(항목|내역|산출|내역)"
    r"|산출\s*근거|교부\s*기준|지원\s*내역|재정\s*현황"
    r"|구성\s*내역|수익자\s*부담금"
)

# F7: 운영 방침·취지·기대 효과 설명 (목적 서술)
_F7_POLICY_DESC = re.compile(
    r"취지\s*(는|로|를)|기대\s*효과|교육적\s*효과|운영\s*방침"
    r"|지원하기\s*위해|도모하(고자|기\s*위해|여)"
    r"|증진하(고자|기\s*위해)|향상시키(고자|기\s*위해)"
    r"|강화하기\s*위해|배경\s*(및|과)|이번에\s*마련"
    r"|목적\s*(은|는|으로|에서)\s*.{0,30}(합니다|입니다)"
)

# F8: 학교 측 수행 행동 (학교·교사 주어 + 완결 서술 동사)
_F8_SCHOOL_ACTION = re.compile(
    r"(본교|학교|담임|교사|선생님|교장|교감|행정실|교육청).*?"
    r"(실시합니다|운영합니다|진행합니다|제공합니다|지원합니다|"
    r"예정입니다|계획합니다|마련합니다|추진합니다|안내합니다)"
    r"|(실시할\s*예정|운영할\s*예정|진행할\s*예정|제공할\s*예정)"
    r"\s*입니다"
)


_FALSE_CHECKS: list[tuple[re.Pattern, str]] = [
    (_F1_TABLE_HEADER,   "F1_table_header"),
    (_F2_SUBTITLE_ONLY,  "F2_subtitle_only"),
    (_F3_SENDER_INFO,    "F3_sender_info"),
    (_F4_FORM_GUIDANCE,  "F4_form_guidance"),
    (_F5_GREETING_SIGN,  "F5_greeting_sign"),
    (_F6_INFO_ONLY,      "F6_info_only"),
    (_F7_POLICY_DESC,    "F7_policy_desc"),
    (_F8_SCHOOL_ACTION,  "F8_school_action"),
]


# ─────────────────────────────────────────────────────────────────────────────
# TRUE 조건 패턴
# ─────────────────────────────────────────────────────────────────────────────

# T1: 마감일 + 액션 동사
_T1_DEADLINE_ACTION = re.compile(
    r"(까지|기한\s*내|마감일?).*?(제출|납부|작성|회신|신청|등록|입금|반납|보내)"
    r"|(제출|납부|작성|회신|신청|등록|입금).{0,30}(까지|기한\s*내|마감)"
    r"|\d+\s*[.월]\s*\d+\s*일?.{0,20}(제출|납부|신청|등록|입금|회신)"
    r"|(제출|납부|신청|등록|입금|회신).{0,20}\d+\s*[.월]\s*\d+\s*일?"
)

# T2: 양식의 작성 칸 (보호자 서명, 체크박스 등)
_T2_FORM_FIELD = re.compile(
    r"보호자\s*(성명|이름|서명|확인|날인|도장)"
    r"|학부모\s*(성명|이름|서명|확인)"
    r"|불참\s*(사유|이유)|동의\s*(여부|서명|확인\s*란)"
    r"|서명\s*란|날인\s*란|확인\s*란"
    r"|\(\s*(예|아니오|동의|미동의|해당|미해당|참|불참)\s*\)"  # ( 예 / 아니오 )
    r"|□\s*(예|아니오|동의|참|불참|해당|미해당|확인)"           # □ 체크박스
)

# T3: 구체적 준비물 목록
_T3_SUPPLIES = re.compile(
    r"준비물\s*[:：]|지참물\s*[:：]|준비\s*사항\s*[:：]"
    r"|챙길\s*(것|물품|준비물)|지참\s*(해주세요|바랍니다|하세요|하시기)"
    r"|가져(와야|올)\s*(할|것|주세요)"
    r"|(실내화|도시락|물병|우산|운동복|체육복|필기구|모자|선크림)"
    r"\s*(을|를)?\s*(준비|지참|챙겨)"
)

# T4: 안전·건강 지침 (행동 권고)
_T4_SAFETY_HEALTH = re.compile(
    r"마스크\s*(착용|필착|꼭\s*착용|써\s*주세요)"
    r"|발열\s*(체크|확인|시\s*등교\s*금지)"
    r"|손\s*(씻기|소독|위생)|체온\s*측정"
    r"|등교\s*금지|격리\s*(해주세요|바랍니다)"
    r"|(안전|주의)\s*(해\s*주세요|바랍니다|지켜\s*주세요)"
    r"|식중독\s*예방|보호대\s*(착용|필착)"
)

# T5: 일정 인지 — 날짜 패턴과 행사 키워드가 한 문장에 함께 있어야 함
_T5_SCHEDULE = re.compile(
    r"(\d+\s*월\s*\d+\s*일|\d+\.\s*\d+\.?|\d+\s*일\s*\()"
    r".{0,40}"
    r"(휴업일|재량\s*휴업|개교기념일|수련|소풍|운동회|체험학습|"
    r"수학여행|방학|개학|입학식|졸업식|행사일|공휴일|임시\s*공휴일)"
    r"|"
    r"(휴업일|재량\s*휴업|개교기념일|수련|소풍|운동회|체험학습|"
    r"수학여행|방학|개학|입학식|졸업식|공휴일|임시\s*공휴일)"
    r".{0,40}"
    r"(\d+\s*월\s*\d+\s*일|\d+\.\s*\d+\.?|\d+\s*일\s*\()"
)

# T6: 학부모 직접 액션 키워드
_T6_PARENT_ACTION = re.compile(
    r"잔액\s*확인|CMS\s*(자동이체|납부)|통장\s*(이체|잔액|확인)"
    r"|자녀.*?(함께\s*(읽어|확인|서명)|지도|연습)"
    r"|가정에서.*?(지도|확인|연습|시행)"
    r"|회신\s*(해주세요|바랍니다|부탁|드립니다)"
    r"|동의\s*(해주시기|하시면|체크|서명|란에|란을)"
    r"|확인\s*후\s*(서명|날인|제출|반환)"
)

# T7: 요청형 종결 어미 — 학부모 대상 직접 요청
_T7_REQUEST_ENDING = re.compile(
    r"(해주세요|해\s*주세요|하세요)\s*\.?\s*$"
    r"|(주시기\s*바랍니다|바랍니다)\s*\.?\s*$"
    r"|(해주시기\s*바랍니다|하시기\s*바랍니다)\s*\.?\s*$"
    r"|(부탁드립니다|부탁\s*드립니다)\s*\.?\s*$"
    r"|(해주십시오|하십시오)\s*\.?\s*$"
    r"|(해주시길\s*바랍니다|하여\s*주시기\s*바랍니다)\s*\.?\s*$"
)


_TRUE_CHECKS: list[tuple[re.Pattern, str]] = [
    (_T1_DEADLINE_ACTION, "T1_deadline_action"),
    (_T2_FORM_FIELD,      "T2_form_field"),
    (_T3_SUPPLIES,        "T3_supplies"),
    (_T4_SAFETY_HEALTH,   "T4_safety_health"),
    (_T5_SCHEDULE,        "T5_schedule"),
    (_T6_PARENT_ACTION,   "T6_parent_action"),
    (_T7_REQUEST_ENDING,  "T7_request_ending"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

def label_with_reason(text: str) -> tuple[bool, str]:
    """(is_todo, reason) 반환. reason 은 매칭된 패턴 코드 또는 'no_match'."""
    text = text.strip()
    if len(text) < 4:
        return False, "too_short"

    for pat, reason in _FALSE_CHECKS:
        if pat.search(text):
            return False, reason

    for pat, reason in _TRUE_CHECKS:
        if pat.search(text):
            return True, reason

    return False, "no_match"


def label_sentence(text: str) -> bool:
    """is_todo 라벨만 반환. True=할 일·중요 일정, False=노이즈."""
    return label_with_reason(text)[0]


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _run_cli() -> None:
    parser = argparse.ArgumentParser(
        description="JSONL 파일에 is_todo 초안 라벨 부여"
    )
    parser.add_argument("--input",  type=Path, required=True,  help="입력 JSONL 파일")
    parser.add_argument("--output", type=Path, required=True,  help="출력 JSONL 파일")
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
    reason_counter: dict[str, int] = {}

    with args.input.open(encoding="utf-8") as fin, \
         args.output.open("w", encoding="utf-8") as fout:

        for raw in fin:
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            text = obj.get("text", "")

            is_todo, reason = label_with_reason(text)
            obj["is_todo"] = is_todo
            if args.with_reason:
                obj["label_reason"] = reason

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")

            total += 1
            if is_todo:
                true_cnt += 1
            else:
                false_cnt += 1
            reason_counter[reason] = reason_counter.get(reason, 0) + 1

    print(f"\n처리 완료: {total}개 문장")
    print(f"  is_todo=True  (할 일) : {true_cnt}  ({true_cnt/total*100:.1f}%)")
    print(f"  is_todo=False (노이즈): {false_cnt}  ({false_cnt/total*100:.1f}%)")
    print(f"\n매칭 이유 분포 (상위 10):")
    for reason, cnt in sorted(reason_counter.items(), key=lambda x: -x[1])[:10]:
        print(f"  {reason:<25} {cnt:>6}회")
    print(f"\n저장: {args.output}")


if __name__ == "__main__":
    _run_cli()
