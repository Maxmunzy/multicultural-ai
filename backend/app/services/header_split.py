"""슬롯 카드 헤더 분해 — todo.text → (헤더, 값) 페어.

강사님 처방 "슬롯 위주 가공" 대응:
  슬롯 카드 = 헤더(라벨) 굵게 + 값 행. 본 모듈이 헤더 추출 책임.

윤정님 split_sentences가 이미 헤더 단위로 todo를 분리해서 반환하므로
보통 todo.text 시작에 헤더 키워드가 옴. 또한 윤정님이 한글 프로 기호 +
표 구분자(`|`)를 정제하기로 합의됨 — 매칭 시 구분자는 옵셔널 처리.

매칭 실패 시 (None, 원문)을 반환해 호출부가 fallback("기타") 헤더로 처리.
"""
from __future__ import annotations

import re

# 가정통신문 표준 헤더 키워드.
# 윤정님 split_sentences 분리 룰의 키워드 + 갈산초/서대구초 케이스 보강.
# 긴 표현이 짧은 것에 흡수되지 않게 정렬은 길이 내림차순 (예: "기타 안내사항" 우선, "기타" 후순위).
HEADER_KEYWORDS: list[str] = [
    # 운영 계열
    "운영시간", "운영방법", "운영날짜", "운영기간", "운영장소",
    # 신청 계열
    "신청방법", "신청기간", "신청경로", "신청대상", "신청자격",
    # 접수/제출
    "접수기간", "접수방법", "접수처",
    "제출방법", "제출기한", "제출처",
    # 일정/장소 — HWP 표 셀에 공백 들어간 변형 ("일 시"/"장 소") 도 정규식에서 \s* 로 커버
    "일시", "기간", "장소", "위치", "주소", "교통",
    # 대상/자격
    "대상", "자격", "참가대상",
    # 준비물/비용 — "학습준비물" 도 추가 (Gemini sentence_list가 만드는 정제 헤더)
    "학습준비물",
    "준비물", "준비", "지참물", "준비사항",
    "비용", "회비", "참가비", "수강료", "급식비",
    # 안내/유의
    "기타 안내사항", "기타안내사항", "안내사항",
    "유의사항", "참고사항", "주의사항",
    # 문의
    "문의", "연락처", "문의처",
    # 기타 (가장 짧음, 마지막)
    "기타",
]

_HEADER_KEYWORDS_SORTED = sorted(HEADER_KEYWORDS, key=len, reverse=True)

# 학년 prefix ("1학년" / "1 학년" 등) — Gemini sentence_list가 학년별 행을
# "{N}학년 ... 학습준비물:" 형식으로 만드는 케이스 보강.
# 자체 휴리스틱 시점엔 원본 통신문에 "1학년 준비물" 형태로 들어와 매칭 안 깨졌지만,
# Gemini 정제 후엔 prefix 명시 인식 필요.
_GRADE_PREFIX_RE = r"(?:[1-6]\s*학년)"
# Sub-modifier (공용/개인/가정/학교) — 학년과 헤더 사이 끼어드는 분류어.
_SUB_MODIFIER_RE = r"(?:공용|개인|가정|학교|학교\s*지원|가정\s*구매)"

# 줄 시작 + (선택적 학년 prefix) + (선택적 sub modifier) + 헤더 키워드 +
# (선택적 `|`/`:`/`：` 구분자) + 값.
# 키워드 글자 사이 \s* 허용 — HWP 표 셀의 공백 변형 ("일 시", "장 소", "대 상")
# + Gemini sentence ("학 습 준 비 물") 매치.
_HEADER_RE = re.compile(
    r"^\s*"
    r"(?P<grade>" + _GRADE_PREFIX_RE + r")?"
    r"\s*"
    r"(?P<sub>" + _SUB_MODIFIER_RE + r")?"
    r"\s*"
    r"(?P<header>" + "|".join(
        r"\s*".join(re.escape(c) for c in k) for k in _HEADER_KEYWORDS_SORTED
    ) + r")"
    r"\s*[|:：]?\s*"
    r"(?P<value>.+)$",
    re.DOTALL,
)


def split_header_value(text: str) -> tuple[str | None, str]:
    """todo.text → (헤더, 값) 페어.

    학년/공용·개인 prefix 인식 — "1학년 공용 학습준비물: ..." → 헤더 "1학년 공용 학습준비물".
    매칭 실패 시 (None, text.strip()) 반환 — 호출부에서 "기타" 같은 fallback 헤더 처리.
    """
    if not text or not text.strip():
        return None, ""
    m = _HEADER_RE.match(text.strip())
    if m:
        parts: list[str] = []
        grade = m.group("grade")
        sub = m.group("sub")
        keyword = m.group("header")
        if grade:
            # "1 학년" → "1학년" 공백 제거 (시각적 통일)
            parts.append(re.sub(r"\s+", "", grade))
        if sub:
            parts.append(re.sub(r"\s+", " ", sub).strip())
        parts.append(keyword)
        header = " ".join(parts)
        return header, m.group("value").strip()
    return None, text.strip()
