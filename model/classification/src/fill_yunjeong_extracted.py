"""윤정님 모델 A 출력(extracted_results.json)에 모델 B의 카테고리/중요도를 채워서 저장.

운영 흐름과 동일한 처리이다:
    가정통신문 원문
        → 모델 A (윤정): todo 문장 추출 + 임시 라벨
        → 모델 B (경이): 카테고리 재예측 + 중요도 회귀 (← 이 스크립트)
        → 결과를 모델 C (세종)로 전달

윤정 jsonl 측의 category는 추출기 내부에서 자동 라벨링한 것이라 일부
부정확한 경우가 있으므로, 모델 B로 한 번 더 정제한다.
중요도는 모델 A 출력에는 추정값만 있어서 모델 B의 회귀 + 룰 점수가 더 정확.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

from .config import DATA_DIR, PRED_DIR
from .predict import predict_one


def fill_extracted_json(
    input_path: Path,
    output_path: Path,
    *,
    today: date | None = None,
    model: str = "simple",
) -> None:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    n = 0
    for entry in data:
        for todo in entry.get("todos", []):
            text = (todo.get("text_ko") or "").strip()
            if not text:
                continue
            out = predict_one(text, model=model, today=today, explain=True)
            todo["category"] = out["category"]
            todo["importance"] = out["importance"]
            todo["action_required"] = out["action_required"]
            todo["urgency_score"] = out["urgency_score"]
            todo["days_to_deadline"] = out["days_to_deadline"]
            n += 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[fill] {n}개 todo 채움 → {output_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path,
                    default=DATA_DIR / "extracted_results.json")
    ap.add_argument("--output", type=Path,
                    default=PRED_DIR / "extracted_results_filled.json")
    ap.add_argument("--today", help="YYYY-MM-DD")
    ap.add_argument("--model", default="simple")
    args = ap.parse_args()
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    fill_extracted_json(args.input, args.output, today=today, model=args.model)


if __name__ == "__main__":
    main()
