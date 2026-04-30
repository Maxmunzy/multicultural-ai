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
    # 일정/장소
    "일시", "기간", "장소", "위치", "주소",
    # 대상/자격
    "대상", "자격", "참가대상",
    # 준비물/비용
    "준비물", "지참물", "준비사항",
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

# 줄 시작 + 헤더 키워드 + (선택적 `|`/`:`/`：` 구분자) + 값
# `|`는 윤정님이 정제하기 전엔 살아있을 수 있어 옵셔널 처리.
_HEADER_RE = re.compile(
    r"^\s*(?P<header>" + "|".join(re.escape(k) for k in _HEADER_KEYWORDS_SORTED) + r")"
    r"\s*[|:：]?\s*"
    r"(?P<value>.+)$",
    re.DOTALL,
)


def split_header_value(text: str) -> tuple[str | None, str]:
    """todo.text → (헤더, 값) 페어.

    매칭 실패 시 (None, text.strip()) 반환 — 호출부에서 "기타" 같은 fallback 헤더 처리.
    """
    if not text or not text.strip():
        return None, ""
    m = _HEADER_RE.match(text.strip())
    if m:
        return m.group("header"), m.group("value").strip()
    return None, text.strip()
