"""윤정님 추출 모델 wrapper.

가정통신문 텍스트 → list[YunjeongTodo].
v2 모델은 binary 분류(BINARY_THRESHOLD=0.5) + 정규식(due_date/amount/action_hint).
빈 리스트 반환은 "할일 없음" — 호출부 별도 처리 불필요.

v2가 push되면 _yunjeong.predict_v2()로 직접 매핑. 그 전엔 v1 adapter로 동작.
"""
import re
import sys
from pathlib import Path

from app.models.schemas import YunjeongTodo

_EXTRACTION_DIR = Path("/app/external_model/extraction")
if str(_EXTRACTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTION_DIR))

# 모델 모듈은 도커 외부 마운트라 CI/테스트 환경에선 부재할 수 있음.
# 모듈 레벨 import 실패가 conftest 로드를 깨뜨리지 않게 가드.
try:
    import predict as _yunjeong  # noqa: E402
except ImportError as error:
    print(f"[extractor] predict module unavailable: {error}")
    _yunjeong = None

_AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")


def extract_todos(notice_text: str) -> list[YunjeongTodo]:
    """가정통신문 원문 → list[YunjeongTodo]. 할일 없으면 []."""
    if not notice_text or not notice_text.strip():
        return []
    if _yunjeong is None:
        return []  # 모델 모듈 없음 (CI 등) — 빈 결과로 후속 단계 정상 동작

    if hasattr(_yunjeong, "predict_v2"):
        return [YunjeongTodo(**raw) for raw in _yunjeong.predict_v2(notice_text)]

    raw_items = _yunjeong.extract_todos_dict(notice_text)
    return [_adapt_v1(item) for item in raw_items]


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
