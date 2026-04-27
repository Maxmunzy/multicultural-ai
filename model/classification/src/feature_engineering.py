"""문장 단위 피처 추출. 중요도 모델의 핵심.

설계 철학
---------
임베딩만으로는 "내일까지 내세요" 같은 시급도 단서를 충분히 못 잡는다.
ko-SBERT는 문장 의미는 잘 잡지만 "내일"과 "다음 달"의 *시급도 차이* 같은
세밀한 신호는 학습 데이터가 200건일 때 회귀가 잡아주기 어렵기 때문에,
명시적인 룰 기반 피처를 추가로 주입해 모델이 학습하기 쉽게 만들어 준다.

추출하는 피처
-------------
1. urgency_score (0~1): 시급도 룰 점수 (가장 중요)
2. has_deadline (0/1): 마감일 표현 존재 여부
3. has_today_tomorrow (0/1): 오늘/내일/당일 등 즉시성
4. has_this_week (0/1): 이번 주
5. days_to_deadline (float, NaN 허용): 마감까지 남은 일수 추정
6. has_submit_verb (0/1): 제출/납부/작성 동사
7. has_money (0/1): 금액 표현
8. has_action_required_neg (0/1): 자동이체/배부 등 학부모 행동 불필요 신호
9. has_health_keyword (0/1): 감염병/발열 등 건강 위급 키워드
10. text_length (int): 문장 길이 (긴 안내문일수록 정보량 많음 경향)

룰 점수 → 학습된 회귀와 가중 평균(`config.IMPORTANCE_RULE_WEIGHT`)으로 결합.

`extract_urgency_for_text`만 알면 단일 문장 추론이 가능하고,
`extract_features_df`는 학습 시 데이터프레임 전체에 일괄 적용한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

import numpy as np
import pandas as pd


# ------------------------------------------------------------------------------
# 정규식 패턴 사전: 한 곳에서 관리
# ------------------------------------------------------------------------------
RE_TODAY = re.compile(r"(?:오늘|당일|금일)")
RE_TOMORROW = re.compile(r"(?:내일|익일)")
RE_THIS_WEEK = re.compile(r"(?:이번\s*주|금주)")
RE_NEXT_WEEK = re.compile(r"(?:다음\s*주|차주)")
# "4월 30일까지", "5월 1일까지", "8월 30일까지", "이번 주 금요일까지"
RE_DEADLINE_DATE = re.compile(
    r"(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*까지"
)
# "금요일까지", "월요일까지"
RE_DEADLINE_DOW = re.compile(
    r"((?:이번|다음|돌아오는)?\s*주?\s*[월화수목금토일]요일)\s*까지"
)
# 일반 "...까지"
RE_DEADLINE_GENERIC = re.compile(r"까지(?:만)?\s*(?:제출|납부|신청|회신|보내|작성|등록)")
# 자동이체 / 배부 등 행동 불필요 신호
RE_NO_ACTION = re.compile(
    r"(자동\s*이체|스쿨뱅킹.*인출|배부됩니다|배부되었|발송됩니다|"
    r"진행됩니다|실시됩니다|예정입니다|게시됩니다|쉽니다|진행되며)"
)
RE_SUBMIT_VERB = re.compile(
    r"(제출|납부|작성|회신|발급|기입|등록|기재|승인|동의|신청|회수|반납|확인\s*버튼|응답)"
)
RE_MONEY = re.compile(r"\d{1,3}(?:[,]?\d{3})+\s*원|\d+\s*만\s*원|\d+\s*원")
RE_HEALTH_URGENT = re.compile(
    r"(감염병\s*확진|확진|발열|구토|응급|즉시\s*연락|즉시\s*알려|"
    r"즉각|기침\s*증상|알레르기\s*조사|아동학대|폭행|학교폭력)"
)
RE_DEADLINE_DAYS = re.compile(r"(\d+)\s*일\s*(?:이내|안)")
RE_HOUR = re.compile(r"(\d{1,2})\s*시\s*(\d{1,2})?\s*분?\s*(?:전|까지)")

# 카테고리 추정에 도움되는 키워드 (룰 보조용 — 분류기 보조 피처로 추가)
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "제출": (
        "동의서", "신청서", "조사서", "확인서", "활동지", "서약서", "원고",
        "제출", "회신", "응답", "기록", "수정", "변경 신청", "발급", "인적",
        "회수", "반납", "신고서", "결석계",
    ),
    "준비물": (
        "준비", "도시락", "실내화", "체육복", "수영복", "여벌옷", "물병",
        "필기도구", "리코더", "이어폰", "장갑", "목도리", "우산", "마스크",
        "운동화", "수건", "수경", "수모", "도화지", "색종이", "풀", "가위",
        "텀블러", "색연필", "앞치마", "머릿수건",
    ),
    "비용": (
        "비용", "참가비", "급식비", "수강료", "앨범비", "활동비", "교육비",
        "원입니다", "납부", "이체", "구입비", "지원", "환불",
    ),
    "건강·안전": (
        "안전", "감염", "확진", "발열", "건강", "예방", "검진", "백신", "예방접종",
        "마스크", "미세먼지", "폭염", "재난", "대피", "민방위", "헬멧",
        "안전벨트", "교통안전", "위생", "손씻기", "구강", "시력",
        "아동학대", "학교폭력", "사이버폭력", "스마트폰", "양성평등",
    ),
    "일정": (
        "월", "일", "운동회", "소풍", "체험학습", "현장학습", "졸업식",
        "입학식", "방학식", "종업식", "공개수업", "발표회", "오디션",
        "총회", "상담", "행사", "오전", "오후", "교시", "수업",
    ),
    "기타": (
        "안내장", "공지", "참고", "권장", "권고", "확인해 주세요", "홈페이지",
        "약속", "원칙", "규칙", "캠페인", "추천",
    ),
}


# ------------------------------------------------------------------------------
# 상대일자 → 일수
# ------------------------------------------------------------------------------
KOR_DOW = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


def _days_until_date(month: int, day: int, today: date) -> int | None:
    """올해 또는 내년의 같은 월일까지 며칠 남았는지.

    "8월 30일까지"는 같은 해 안에서 미래라면 그 날짜, 과거라면 내년의 그 날짜로
    해석한다. 학교 안내문 특성상 미래 일자가 정상.
    """
    try:
        target = date(today.year, month, day)
        if target < today:
            target = date(today.year + 1, month, day)
        return (target - today).days
    except ValueError:
        return None


def _days_until_dow(text_dow: str, today: date) -> int | None:
    """'금요일까지' → 다가오는 금요일까지의 일수.

    '다음 주 금요일'이면 7일 더해 본다. '이번 주 금요일'은 동일 주 내.
    이미 지났으면 다음 주.
    """
    if "다음" in text_dow or "차주" in text_dow:
        offset_week = 1
    else:
        offset_week = 0
    m = re.search(r"([월화수목금토일])요일", text_dow)
    if not m:
        return None
    target_dow = KOR_DOW[m.group(1)]
    today_dow = today.weekday()
    delta = (target_dow - today_dow) % 7
    if delta == 0 and offset_week == 0:
        delta = 0  # 오늘이 금요일이고 "이번 주 금요일까지"면 오늘
    return delta + offset_week * 7


# ------------------------------------------------------------------------------
# 핵심 함수: 단일 문장 시급도 추출
# ------------------------------------------------------------------------------
@dataclass
class FeatureRow:
    urgency_score: float
    has_deadline: int
    has_today_tomorrow: int
    has_this_week: int
    has_next_week: int
    days_to_deadline: float  # NaN 허용 → np.nan
    has_submit_verb: int
    has_money: int
    has_no_action: int
    has_health_urgent: int
    text_length: int
    keyword_score_per_label: tuple[float, ...]  # LABELS 순서대로

    def as_dict(self) -> dict:
        d = {
            "urgency_score": self.urgency_score,
            "has_deadline": self.has_deadline,
            "has_today_tomorrow": self.has_today_tomorrow,
            "has_this_week": self.has_this_week,
            "has_next_week": self.has_next_week,
            "days_to_deadline": self.days_to_deadline,
            "has_submit_verb": self.has_submit_verb,
            "has_money": self.has_money,
            "has_no_action": self.has_no_action,
            "has_health_urgent": self.has_health_urgent,
            "text_length": self.text_length,
        }
        from .config import LABELS

        for label, score in zip(LABELS, self.keyword_score_per_label):
            d[f"kw_{label}"] = score
        return d


def _urgency_from_days(days: float | None) -> float:
    """남은 일수 → 0~1 시급도. 가까울수록 1에 수렴.

    의도: '내일'(1일) ≈ 0.95, '이번 주'(평균 3.5일) ≈ 0.85,
    '다음 주'(7~10) ≈ 0.7, '한 달 뒤'(30일) ≈ 0.5.
    학부모 행동 압박감 곡선과 맞도록 지수 감쇠를 사용.
    """
    if days is None or (isinstance(days, float) and np.isnan(days)):
        return 0.0
    if days <= 0:
        return 1.0
    # τ=10 정도가 학교 안내문 기준 적절 (1주 안쪽이면 강하게 가산)
    return float(np.exp(-days / 10.0))


def extract_features(text: str, *, today: date | None = None) -> FeatureRow:
    """문장 하나에서 모든 피처를 한 번에 뽑는다.

    today: 시급도 계산 기준일. 추론 시 호출 측이 현재 날짜를 넘기면
    "4월 26일까지" 같은 절대 날짜 표현을 정확히 일수로 변환한다.
    학습 시에는 라벨링 시점의 현재 날짜를 알 수 없으므로 None을 두면
    절대 날짜는 평균값(7일)으로 처리한다.
    """
    from .config import LABELS

    today = today or date.today()
    has_today = bool(RE_TODAY.search(text))
    has_tomorrow = bool(RE_TOMORROW.search(text))
    has_this_week = bool(RE_THIS_WEEK.search(text))
    has_next_week = bool(RE_NEXT_WEEK.search(text))

    days: float | None = None

    # 1) 절대 일자 "M월 D일까지"
    m = RE_DEADLINE_DATE.search(text)
    if m:
        d = _days_until_date(int(m.group(1)), int(m.group(2)), today)
        if d is not None:
            days = float(d)

    # 2) 요일 "이번 주 금요일까지"
    if days is None:
        m2 = RE_DEADLINE_DOW.search(text)
        if m2:
            d = _days_until_dow(m2.group(1), today)
            if d is not None:
                days = float(d)

    # 3) "5일 이내" 같은 상대 일수
    if days is None:
        m3 = RE_DEADLINE_DAYS.search(text)
        if m3:
            days = float(m3.group(1))

    # 4) 일반 마감 표현은 있는데 일자 추출 실패 → 가까운 미래로 가정 (5일)
    has_deadline_generic = bool(RE_DEADLINE_GENERIC.search(text))
    if days is None and (has_deadline_generic or has_this_week):
        days = 5.0
    if days is None and has_tomorrow:
        days = 1.0
    if days is None and has_today:
        days = 0.0

    has_deadline = int(
        bool(m) or bool(RE_DEADLINE_DOW.search(text))
        or bool(RE_DEADLINE_DAYS.search(text)) or has_deadline_generic
    )

    # 시급도 점수: 일수 기반 + 즉시성 키워드 부스팅
    urgency = _urgency_from_days(days)
    if has_today:
        urgency = max(urgency, 0.98)
    elif has_tomorrow:
        urgency = max(urgency, 0.93)
    elif has_this_week:
        urgency = max(urgency, 0.85)
    elif has_next_week:
        urgency = max(urgency, 0.7)

    # 자동이체/배부 등은 행동 불필요 → 시급도 약간 감점
    has_no_action = int(bool(RE_NO_ACTION.search(text)))
    if has_no_action and not has_deadline:
        urgency *= 0.6

    has_submit_verb = int(bool(RE_SUBMIT_VERB.search(text)))
    has_money = int(bool(RE_MONEY.search(text)))
    has_health_urgent = int(bool(RE_HEALTH_URGENT.search(text)))

    # 카테고리별 키워드 매칭 점수 (분류 보조 피처)
    kw_scores = []
    for label in LABELS:
        kws = CATEGORY_KEYWORDS.get(label, ())
        hit = sum(1 for kw in kws if kw in text)
        kw_scores.append(float(hit))

    return FeatureRow(
        urgency_score=float(np.clip(urgency, 0.0, 1.0)),
        has_deadline=has_deadline,
        has_today_tomorrow=int(has_today or has_tomorrow),
        has_this_week=int(has_this_week),
        has_next_week=int(has_next_week),
        days_to_deadline=float(days) if days is not None else float("nan"),
        has_submit_verb=has_submit_verb,
        has_money=has_money,
        has_no_action=has_no_action,
        has_health_urgent=has_health_urgent,
        text_length=len(text),
        keyword_score_per_label=tuple(kw_scores),
    )


# ------------------------------------------------------------------------------
# 룰 기반 importance (학습이 부족한 환경의 안전망)
# ------------------------------------------------------------------------------
def rule_importance(text: str, category: str | None, *, today: date | None = None) -> float:
    """룰 기반 importance 점수 (0~1).

    공식:
        base = CATEGORY_BASE_IMPORTANCE[category]
        rule_score = base + 0.20 * urgency_score
                          + 0.05 * has_submit_verb
                          + 0.05 * has_health_urgent
                          - 0.10 * has_no_action (deadline 없을 때만)
        clip(rule_score, 0.30, 1.00)

    이 단순 가산이 의외로 강력한 이유:
    - 학교 안내문은 시급도가 매우 강한 1차 신호.
    - 카테고리별 베이스가 README의 사람 직관과 정확히 맞다.
    - 작은 데이터(200~300개)에서 회귀가 학습 못 잡는 패턴을 확실히 잡아 준다.

    호출 측은 학습된 회귀 점수와 가중 평균해 최종 점수를 만든다.
    """
    from .config import CATEGORY_BASE_IMPORTANCE

    feat = extract_features(text, today=today)
    base = CATEGORY_BASE_IMPORTANCE.get(category or "기타", 0.5)
    score = base + 0.20 * feat.urgency_score
    score += 0.05 * feat.has_submit_verb
    score += 0.05 * feat.has_health_urgent
    if feat.has_no_action and not feat.has_deadline:
        score -= 0.10
    return float(np.clip(score, 0.30, 1.00))


# ------------------------------------------------------------------------------
# 데이터프레임 일괄 처리
# ------------------------------------------------------------------------------
def extract_features_df(df: pd.DataFrame, *, today: date | None = None) -> pd.DataFrame:
    """`original_text` 컬럼을 가진 df → 피처 컬럼 추가된 df 반환."""
    rows = [extract_features(t, today=today).as_dict() for t in df["original_text"]]
    feat_df = pd.DataFrame(rows)
    return pd.concat([df.reset_index(drop=True), feat_df.reset_index(drop=True)], axis=1)


if __name__ == "__main__":
    # 시급도 룰의 동작을 사람 눈으로 확인하기 위한 간단 데모
    samples = [
        "학생 기초조사서를 내일까지 담임선생님께 제출해 주세요",
        "다음 주 월요일 현장체험학습 참가 신청서를 담임선생님께 제출해 주세요",
        "방과후학교 수강료 25000원은 다음 달 5일 자동이체됩니다",
        "여름방학 과제 안내장은 방학식 당일 배부됩니다",
        "감염병 확진 시 등교하지 말고 학교로 즉시 연락해 주세요",
        "4월 30일까지 개인정보 수집 이용 동의서를 제출해 주세요",
        "환경보호 캠페인을 위해 개인 텀블러 사용을 권장합니다",
    ]
    for s in samples:
        f = extract_features(s)
        rule_imp = rule_importance(s, "제출")
        print(
            f"[urg={f.urgency_score:.2f}, days={f.days_to_deadline}, "
            f"submit={f.has_submit_verb}, no_act={f.has_no_action}] "
            f"rule(제출)={rule_imp:.2f}  | {s}"
        )
