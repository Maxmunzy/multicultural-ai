"""경이님 6-class 분류 모델 wrapper.

문장 → Category (일정/준비물/제출/비용/건강·안전/기타).
파이프라인 [4] 단계 — 윤정님 todo 각각에 대해 호출되어 AnalyzeItem.category로 들어감.

기본 모델: simple (TF-IDF + LogReg). 시연 시 가벼움 + 정확도 0.85+ 목표.
"""
import sys
from datetime import date
from pathlib import Path

from app.models.schemas import Category

_CLF_DIR = Path("/app/external_model/classification")
if str(_CLF_DIR) not in sys.path:
    sys.path.insert(0, str(_CLF_DIR))

from src.predict import predict_one  # noqa: E402


def classify_category(text: str, today: date | None = None) -> Category:
    """문장 → 6-class 카테고리. 실패/미정 시 Category.other."""
    if not text or not text.strip():
        return Category.other

    try:
        result = predict_one(text, model="simple", today=today, explain=False)
    except Exception as error:
        print(f"[classifier] predict_one failed: {error}")
        return Category.other

    label = result.get("category", "")
    try:
        return Category(label)
    except ValueError:
        return Category.other
