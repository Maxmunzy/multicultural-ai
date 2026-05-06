"""윤정님 추출 모델 wrapper.

가정통신문 텍스트 → list[YunjeongTodo].
v2 모델 (model/extraction/file/predict.py): binary 분류(BINARY_THRESHOLD=0.5) +
정규식 due_date/amount/action_hint. 출력 스키마가 YunjeongTodo와 1:1.

v1 (구버전 model/extraction/predict.py)은 윤정님이 v2 머지하면서 삭제.
v1 adapter 경로는 호환성을 위해 남겨두지만 실제로는 v2 진입점이 사용됨.
"""
import re
import sys
from pathlib import Path

from app.models.schemas import YunjeongTodo

# v2 진입점은 model/extraction/file/predict.py.
# CI/테스트 환경에선 외부 마운트 부재 → 가드로 빈 결과 반환.
_EXTRACTION_DIR = Path("/app/external_model/extraction/file")
if str(_EXTRACTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTION_DIR))

try:
    import predict as _yunjeong  # noqa: E402
except ImportError as error:
    print(f"[extractor] predict module unavailable: {error}")
    _yunjeong = None

_AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")
# 제목 fallback — 윤정 heuristic이 reject한 케이스(연도 시작 + 공백 dash)도 잡기.
# 가통문 표준 제목 키워드 확장 — "디지털성범죄 예방 안내", "교육비 지원" 등
# "안내" 부족 케이스도 커버.
_TITLE_KEYWORDS = re.compile(
    r"(안내|공지|알림|통보|조사|신청|수납|모집"
    r"|예방|교육|행사|프로그램|캠페인|지원|보호"
    r"|연수|상담|평가|점검|운영)"
)


# 윤정 결과가 명백히 제목 아닌 패턴 (※ 표 주석, 괄호 시작, 콜론으로 시작 등)
# 이면 reject 후 fallback 사용. 가통문 제목은 보통 한글로 시작.
_INVALID_TITLE_PREFIX = re.compile(r"^[※◎●▶▷◆◇*\-•(\[「『:：]")


def extract_title(notice_text: str) -> str | None:
    """가정통신문 원문 → 제목 한 줄. 못 찾으면 None.

    윤정님 PR #90 (predict.py:extract_title) — split_sentences()의
    _HEADER_ONLY 필터가 제목을 차단하기 전에 원문 줄을 직접 스캔.
    predict()와 별도 호출.

    Fallback 사용 조건:
      - 윤정 결과 None
      - 또는 명백히 무효 (※ / 괄호 / 마커로 시작 — 표 주석/안내 fragment)
    """
    if not notice_text or not notice_text.strip():
        return None
    title: str | None = None
    if _yunjeong is not None and hasattr(_yunjeong, "extract_title"):
        try:
            title = _yunjeong.extract_title(notice_text)
        except Exception as error:
            print(f"[extractor] extract_title failed: {error}")
    if title and not _INVALID_TITLE_PREFIX.match(title.strip()):
        return title

    # Fallback: 본문 상단 5줄에서 제목 키워드 포함 + 길이 8~80자
    for line in notice_text.splitlines()[:5]:
        line = line.strip()
        if 8 <= len(line) <= 80 and _TITLE_KEYWORDS.search(line):
            return line
    return None


def extract_todos(notice_text: str, source: str | None = None) -> list[YunjeongTodo]:
    """가정통신문 원문 → list[YunjeongTodo]. 할일 없으면 []."""
    if not notice_text or not notice_text.strip():
        return []
    if _yunjeong is None:
        return []  # 모델 모듈 없음 (CI 등) — 빈 결과로 후속 단계 정상 동작

    # v2 진입점: predict(text, source) → list[dict]
    if hasattr(_yunjeong, "predict"):
        try:
            raw_items = _yunjeong.predict(notice_text, source=source)
        except TypeError:
            # source kwarg 미지원 버전 호환
            raw_items = _yunjeong.predict(notice_text)
        return [YunjeongTodo(**raw) for raw in raw_items]

    # v1 fallback (구버전 predict.py가 마운트되어 있을 경우)
    if hasattr(_yunjeong, "extract_todos_dict"):
        raw_items = _yunjeong.extract_todos_dict(notice_text)
        return [_adapt_v1(item) for item in raw_items]

    return []


def _adapt_v1(v1_item: dict) -> YunjeongTodo:
    text = v1_item.get("text_ko", "")
    return YunjeongTodo(
        text=text,
        source=None,
        due_date=v1_item.get("due_date"),
        amount=_extract_amount_value(text),
        confidence=float(v1_item.get("importance", 0.5)),
        action_hint=None,
    )


def _extract_amount_value(text: str) -> int | None:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None
