"""분류 결과(category, importance)를 덮어쓴 6열 CSV 내보내기.

출력 컬럼: id, source_type, original_text, category, keywords, importance

사용법
------
기본 (notice_sample_v2.csv 입력):
    python -m src.export_classified

입력 파일 지정:
    python -m src.export_classified --input data/notice_sample_v2.csv

출력 경로 지정:
    python -m src.export_classified --output outputs/predictions/result.csv

모델 선택 (기본 simple):
    python -m src.export_classified --model sbert

기준일 지정 (시급도 절대 날짜 계산용):
    python -m src.export_classified --today 2026-04-27
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import PRED_DIR
from .importance_scorer import ImportanceScorer
from .predict import _load_classifier

OUTPUT_COLS = ["id", "source_type", "original_text", "category", "keywords", "importance"]


def export_classified_csv(
    input_path: Path,
    output_path: Path,
    *,
    model: str = "simple",
    today: date | None = None,
) -> pd.DataFrame:
    """입력 CSV를 읽어 모든 행의 category / importance를 모델 예측으로 덮어쓰고
    6개 컬럼(id, source_type, original_text, category, keywords, importance)만
    남긴 CSV를 저장한다.
    """
    df = pd.read_csv(input_path)
    if "original_text" not in df.columns:
        raise ValueError("입력 CSV에 'original_text' 컬럼이 필요합니다.")

    clf = _load_classifier(model)
    scorer = ImportanceScorer.load()
    texts = df["original_text"].astype(str).tolist()

    cats = clf.predict(texts)
    imps = scorer.predict(texts, cats, today=today)

    # category / importance 전체 덮어쓰기
    df["category"] = cats
    df["importance"] = [round(float(v), 2) for v in imps]

    # 출력 컬럼 중 없는 것은 빈 문자열로 보충
    for col in OUTPUT_COLS:
        if col not in df.columns:
            df[col] = ""

    out_df = df[OUTPUT_COLS].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[export] {len(texts)}개 행 처리 완료 → {output_path}")
    return out_df


def main() -> None:
    ap = argparse.ArgumentParser(description="분류 결과 6열 CSV 내보내기")
    ap.add_argument(
        "--input",
        type=Path,
        default=Path("data/notice_sample_v2.csv"),
        help="입력 CSV 경로 (기본: data/notice_sample_v2.csv)",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="출력 CSV 경로 (기본: outputs/predictions/<입력파일명>_classified.csv)",
    )
    ap.add_argument(
        "--model",
        default="simple",
        choices=["simple", "sklearn", "sbert", "kobert"],
        help="사용할 분류 모델 (기본: simple)",
    )
    ap.add_argument(
        "--today",
        default=None,
        help="기준일 YYYY-MM-DD (시급도 절대 날짜 계산용)",
    )
    args = ap.parse_args()

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    out_path = args.output or (PRED_DIR / f"{args.input.stem}_classified.csv")

    export_classified_csv(args.input, out_path, model=args.model, today=today)


if __name__ == "__main__":
    main()
