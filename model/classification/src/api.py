"""FastAPI 인퍼런스 서버. 태수님 백엔드(`services/classifier.py`)에서 사용.

엔드포인트
----------
- POST /classify
    request:
        {"text": "...", "today": "2026-04-27" (optional)}
    response:
        {"category": "...", "importance": 0.95, "action_required": "Y",
         "urgency_score": 0.93, "explain": {...}}

- POST /classify/batch
    request: {"texts": ["...", ...], "today": "..."}
    response: {"items": [...]}

- GET /health → {"status": "ok"}

실행:
    uvicorn src.api:app --host 0.0.0.0 --port 8001

태수님 통합 안내:
    backend/services/classifier.py 안에서 httpx.post("http://classifier:8001/classify")로
    호출하거나, 같은 프로세스에서 import 하려면 predict_one을 직접 호출하면 된다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
    FASTAPI_OK = True
except ImportError:
    FASTAPI_OK = False

from .config import LABELS
from .predict import predict_one


if FASTAPI_OK:

    class ClassifyRequest(BaseModel):
        text: str = Field(..., description="추출된 가정통신문 한 문장")
        today: str | None = Field(
            None, description="기준일 YYYY-MM-DD. 없으면 서버 시각."
        )
        model: str = Field("simple", description="simple | sklearn | sbert | kobert")

    class ClassifyBatchRequest(BaseModel):
        texts: list[str]
        today: str | None = None
        model: str = "simple"

    class ClassifyResponse(BaseModel):
        category: str
        importance: float
        action_required: str
        urgency_score: float
        days_to_deadline: int | None
        has_deadline: bool
        has_submit_verb: bool

    app = FastAPI(
        title="모델 B — 가정통신문 분류 + 중요도",
        description="추출 문장 → 6개 카테고리 + 0~1 중요도",
        version="0.1.0",
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "labels": list(LABELS)}

    @app.post("/classify", response_model=ClassifyResponse)
    def classify(req: ClassifyRequest) -> ClassifyResponse:
        if not req.text.strip():
            raise HTTPException(400, "text가 비어 있습니다.")
        today = (
            datetime.strptime(req.today, "%Y-%m-%d").date() if req.today else None
        )
        out = predict_one(req.text, model=req.model, today=today, explain=True)
        return ClassifyResponse(
            category=out["category"],
            importance=out["importance"],
            action_required=out["action_required"],
            urgency_score=out["urgency_score"],
            days_to_deadline=out["days_to_deadline"],
            has_deadline=out["has_deadline"],
            has_submit_verb=out["has_submit_verb"],
        )

    @app.post("/classify/batch")
    def classify_batch(req: ClassifyBatchRequest) -> dict[str, Any]:
        today = (
            datetime.strptime(req.today, "%Y-%m-%d").date() if req.today else None
        )
        items = [
            predict_one(t, model=req.model, today=today, explain=True)
            for t in req.texts
        ]
        return {"items": items}

else:
    app = None
