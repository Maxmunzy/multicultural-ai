"""저장된 분류기 + 중요도 모델로 빈 칸을 채우는 추론 스크립트.

이미지 시나리오 그대로:
    notice_sample_vN.csv (category, importance가 비어있는 행 포함)
            ↓
    predict.py 실행
            ↓
    notice_sample_vN_filled.csv (모델이 채운 결과)

사용법
------
1) 단일 문장:
    python -m src.predict --text "내일까지 동의서를 제출해 주세요"

2) CSV 일괄 채우기:
    python -m src.predict --input data/new_notices.csv --output outputs/predictions/filled.csv

3) 모델 선택 (기본 simple):
    python -m src.predict --model sbert --input ...

4) 추론 시 오늘 날짜 지정 (시급도 룰의 절대 일자 계산용):
    python -m src.predict --today 2026-04-27 --text "5월 1일까지 신청해 주세요"
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import EMPTY_SENTINELS, LABELS, MODEL_DIR, PRED_DIR
from .feature_engineering import extract_features
from .importance_scorer import ImportanceScorer


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    return str(v).strip() in EMPTY_SENTINELS


def _load_classifier(model: str):
    if model == "simple":
        from .classifier_simple import SimpleNoticeClassifier
        return SimpleNoticeClassifier.load()
    if model == "sklearn":
        from .classifier_sklearn import load_sklearn_model
        pipe = load_sklearn_model()

        class _Wrap:
            def predict(self, texts):
                return list(pipe.predict(texts))

        return _Wrap()
    if model == "sbert":
        from .classifier_sbert import SbertLgbmClassifier
        return SbertLgbmClassifier.load()
    if model == "kobert":
        from .classifier_kobert import predict_kobert
        d = MODEL_DIR / "kobert_classifier"

        class _Wrap:
            def predict(self, texts):
                return predict_kobert(d, texts)

        return _Wrap()
    raise ValueError(model)


def predict_one(
    text: str,
    *,
    model: str = "simple",
    today: date | None = None,
    explain: bool = True,
) -> dict:
    """문장 하나 → category / importance / 설명."""
    clf = _load_classifier(model)
    scorer = ImportanceScorer.load()
    cat = clf.predict([text])[0]
    imp = float(scorer.predict([text], [cat], today=today)[0])
    out = {"text": text, "category": cat, "importance": round(imp, 3)}
    if explain:
        f = extract_features(text, today=today).as_dict()
        out["urgency_score"] = round(f["urgency_score"], 3)
        out["days_to_deadline"] = (
            None if np.isnan(f["days_to_deadline"]) else int(f["days_to_deadline"])
        )
        out["has_deadline"] = bool(f["has_deadline"])
        out["has_submit_verb"] = bool(f["has_submit_verb"])
        out["action_required"] = "Y" if imp >= 0.7 and not bool(f["has_no_action"]) else "N"
    return out


def fill_csv(
    input_path: Path,
    output_path: Path,
    *,
    model: str = "simple",
    today: date | None = None,
    overwrite: bool = False,
) -> pd.DataFrame:
    """CSV의 빈 category/importance를 채워 새 CSV 저장.

    overwrite=True면 이미 라벨이 있는 행도 모델 예측으로 덮어쓴다.
    기본은 빈 칸만 채움 (사람 라벨 보호).
    """
    df = pd.read_csv(input_path)
    if "original_text" not in df.columns:
        raise ValueError("입력 CSV에 'original_text' 컬럼이 필요합니다.")
    if "category" not in df.columns:
        df["category"] = pd.Series([pd.NA] * len(df), dtype="object")
    else:
        df["category"] = df["category"].astype("object")
    if "importance" not in df.columns:
        df["importance"] = pd.Series([pd.NA] * len(df), dtype="float64")

    # 채울 행 식별
    if overwrite:
        mask = pd.Series([True] * len(df))
    else:
        mask = df["category"].apply(_is_empty) | df["importance"].apply(_is_empty)

    if not mask.any():
        print("[predict] 채울 빈 칸이 없습니다.")
        df.to_csv(output_path, index=False)
        return df

    clf = _load_classifier(model)
    scorer = ImportanceScorer.load()
    target_texts = df.loc[mask, "original_text"].astype(str).tolist()

    cats = clf.predict(target_texts)
    imps = scorer.predict(target_texts, cats, today=today)

    # 빈 칸인 컬럼만 쓰기
    cat_mask = mask & df["category"].apply(_is_empty)
    imp_mask = mask & df["importance"].apply(_is_empty)
    pred_idx = df.index[mask].tolist()
    cat_map = dict(zip(pred_idx, cats))
    imp_map = dict(zip(pred_idx, imps))
    for i in pred_idx:
        if cat_mask.loc[i] or overwrite:
            df.at[i, "category"] = cat_map[i]
        if imp_mask.loc[i] or overwrite:
            df.at[i, "importance"] = round(float(imp_map[i]), 2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"[predict] {len(target_texts)}개 행 채움 → {output_path}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="simple",
                    choices=["simple", "sklearn", "sbert", "kobert"])
    ap.add_argument("--text", help="단일 문장 추론")
    ap.add_argument("--input", type=Path, help="입력 CSV")
    ap.add_argument("--output", type=Path, help="출력 CSV")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (시급도 절대 날짜 계산용)")
    ap.add_argument("--overwrite", action="store_true",
                    help="이미 라벨이 있어도 예측으로 덮어쓰기")
    args = ap.parse_args()

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None

    if args.text:
        out = predict_one(args.text, model=args.model, today=today)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if args.input:
        out_path = args.output or (PRED_DIR / f"{args.input.stem}_filled.csv")
        fill_csv(args.input, out_path, model=args.model, today=today, overwrite=args.overwrite)
        return

    ap.print_help()


if __name__ == "__main__":
    main()
