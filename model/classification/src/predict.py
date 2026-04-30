"""
경이님 6-class 카테고리 분류 — 백엔드 진입점
==============================================
담당: 경이
파이프라인: [4] 카테고리 분류 단계

백엔드(backend/app/services/classifier.py)가 이 파일의 predict_one()을 호출함:
    from src.predict import predict_one
    result = predict_one(text, model="simple", today=today, explain=False)

지원 모델:
    "simple"    → TF-IDF + LogReg (베이스라인, 빠름, CPU)
    "kcelectra" → KcELECTRA 파인튜닝 (파인튜닝 완료 후 사용 가능)
    "auto"      → kcelectra 체크포인트 있으면 사용, 없으면 simple fallback

출력 형식:
    {
        "text":       str,
        "category":   str,   # "일정" | "준비물" | "제출" | "비용" | "건강·안전" | "기타"
        "confidence": float, # 0.0 ~ 1.0
        "model_used": str,   # 실제 사용된 모델명
        "probs":      dict   # explain=True일 때만 채워짐
    }
"""

from __future__ import annotations

import datetime
from typing import Optional

from .classifier_simple import predict_simple
from .classifier_kcelectra import predict_kcelectra, is_ready as kcelectra_ready

VALID_CATEGORIES = {"일정", "준비물", "제출", "비용", "건강·안전", "기타"}


def predict_one(
    text: str,
    model: str = "simple",
    today: Optional[datetime.date] = None,
    explain: bool = False,
) -> dict:
    """문장 1개 → 6-class 카테고리 예측.

    Args:
        text:    분류할 문장 (윤정님 모델 출력의 "text" 필드)
        model:   "simple" | "kcelectra" | "auto"
        today:   사용 안 함 (날짜 의존 분류 대비 인터페이스 호환)
        explain: True → probs 딕셔너리 포함

    Returns:
        {
            "text":       str,
            "category":   str,
            "confidence": float,
            "model_used": str,
            "probs":      dict (explain=True 시),
        }
    """
    if not text or not text.strip():
        return _empty_result(text, model)

    model = model.lower()
    result: dict
    used: str

    if model == "kcelectra":
        result = predict_kcelectra(text)
        used = "kcelectra"
    elif model == "auto":
        if kcelectra_ready():
            result = predict_kcelectra(text)
            used = "kcelectra"
        else:
            result = predict_simple(text)
            used = "simple"
    else:
        result = predict_simple(text)
        used = "simple"

    category = result.get("category", "기타")
    if category not in VALID_CATEGORIES:
        category = "기타"

    out = {
        "text":       text,
        "category":   category,
        "confidence": result.get("confidence", 0.0),
        "model_used": used,
    }
    if explain:
        out["probs"] = result.get("probs", {})
    return out


def predict_batch(
    texts: list[str],
    model: str = "simple",
    today: Optional[datetime.date] = None,
    explain: bool = False,
) -> list[dict]:
    """여러 문장 일괄 예측. 윤정님 결과 전체를 한 번에 처리할 때 사용."""
    return [predict_one(t, model=model, today=today, explain=explain) for t in texts]


def _empty_result(text: str, model: str) -> dict:
    return {
        "text":       text,
        "category":   "기타",
        "confidence": 0.0,
        "model_used": model,
    }


# ─────────────────────────────────────────
# 직접 실행 테스트
# ─────────────────────────────────────────
if __name__ == "__main__":
    samples = [
        "현장체험학습 비용 20,000원을 3월 20일까지 납부해 주세요.",
        "체험학습 당일 도시락과 물을 준비해 주세요.",
        "동의서를 작성하여 담임선생님께 제출해 주세요.",
        "운동회는 10월 5일 오전 9시 30분에 열립니다.",
        "발열·기침 증상이 있는 경우 등교를 자제해 주세요.",
        "궁금한 사항은 담임선생님께 문의해 주세요.",
    ]
    print("=" * 60)
    print("predict_one 테스트 (model=simple)")
    print("=" * 60)
    for s in samples:
        r = predict_one(s, model="simple", explain=True)
        print(f"\n문장: {r['text']}")
        print(f"  → 카테고리: {r['category']}  (신뢰도: {r['confidence']:.3f})")
        probs = r.get("probs", {})
        top3 = sorted(probs.items(), key=lambda x: -x[1])[:3]
        print(f"  → Top3: {top3}")
