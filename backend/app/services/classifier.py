"""경이님 분류 모델 wrapper (검수자 역할).

윤정 추출 결과(TodoItem 리스트)를 받아 경이 모델로 카테고리/중요도를 다시 평가.
두 모델의 결과가 다르면 review_needed 메시지로 표시한다.
"""
import sys
from datetime import date
from pathlib import Path

from app.models.schemas import TodoItem

_CLF_DIR = Path("/app/external_model/classification")
if str(_CLF_DIR) not in sys.path:
    sys.path.insert(0, str(_CLF_DIR))

from src.predict import predict_one  # noqa: E402

IMPORTANCE_DIFF_THRESHOLD = 0.15  # 0.15 이상 차이나면 검수 표시


def review_todos(todos: list[TodoItem], today: date | None = None) -> str:
    """윤정 todos를 경이 모델로 검수. 불일치 시 사람 검수용 메시지 반환."""
    if not todos:
        return ""

    diffs: list[str] = []
    for i, todo in enumerate(todos, start=1):
        try:
            result = predict_one(
                todo.text_ko, model="simple", today=today, explain=True
            )
        except Exception as error:
            print(f"[classifier] predict_one failed for [{i}]: {error}")
            continue

        kyeongyi_cat = result.get("category", "")
        kyeongyi_imp = float(result.get("importance", 0.0))

        cat_mismatch = kyeongyi_cat and kyeongyi_cat != todo.category.value
        imp_mismatch = abs(kyeongyi_imp - todo.importance) >= IMPORTANCE_DIFF_THRESHOLD

        if cat_mismatch or imp_mismatch:
            preview = todo.text_ko if len(todo.text_ko) <= 30 else todo.text_ko[:30] + "..."
            parts = [f"[{i}] '{preview}'"]
            if cat_mismatch:
                parts.append(f"카테고리: 윤정={todo.category.value} vs 경이={kyeongyi_cat}")
            if imp_mismatch:
                parts.append(f"중요도: 윤정={todo.importance:.2f} vs 경이={kyeongyi_imp:.2f}")
            diffs.append(" / ".join(parts))

    return "\n".join(diffs)
