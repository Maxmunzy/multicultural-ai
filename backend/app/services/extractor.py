"""윤정님 KoELECTRA 추출 모델 wrapper.

가정통신문 텍스트 → TodoItem 리스트.
모델은 첫 호출 시 HF Hub(yunjeong116/koelectra-extractor)에서 자동 다운로드된다.
"""
import sys
from pathlib import Path

from app.models.schemas import Category, TodoItem

_EXTRACTION_DIR = Path("/app/external_model/extraction")
if str(_EXTRACTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTION_DIR))

import predict as _yunjeong  # noqa: E402


def extract_todos(notice_text: str) -> list[TodoItem]:
    """가정통신문 원문 → TodoItem 리스트."""
    if not notice_text or not notice_text.strip():
        return []

    raw_items = _yunjeong.extract_todos_dict(notice_text)
    todos: list[TodoItem] = []
    for item in raw_items:
        try:
            cat = Category(item["category"])
        except ValueError:
            cat = Category.other
        todos.append(TodoItem(
            category=cat,
            text_ko=item["text_ko"],
            text_vi=item.get("text_vi", ""),
            importance=float(item["importance"]),
            due_date=item.get("due_date"),
        ))
    return todos
