"""학습 진입점. 환경/옵션에 따라 사용 가능한 모델을 학습한다.

사용법
------
1) 가벼운 모델만 (numpy + pandas만 있으면 됨):
       python -m src.train --model simple

2) sklearn 베이스라인:
       pip install scikit-learn joblib
       python -m src.train --model sklearn

3) SBERT + LightGBM (메인 권장):
       pip install sentence-transformers lightgbm joblib
       python -m src.train --model sbert

4) KoBERT/KoELECTRA fine-tune:
       pip install torch transformers
       python -m src.train --model kobert --epochs 5

학습된 모델은 outputs/models/ 아래에 저장된다.
중요도 모델(`ImportanceScorer`)은 분류기와 별개로 항상 함께 학습.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import LABELS, MODEL_DIR, REPORT_DIR
from .data_loader import build_dataset
from .evaluate import evaluate_pipeline
from .importance_scorer import ImportanceScorer


def _train_simple(split):
    from .classifier_simple import SimpleNoticeClassifier
    clf = SimpleNoticeClassifier(epochs=300)
    clf.fit(split.train["original_text"].tolist(), split.train["category"].tolist())
    clf.save()
    return clf


def _train_sklearn(split):
    from .classifier_sklearn import save_sklearn_model, train_sklearn_classifier
    pipe = train_sklearn_classifier(
        split.train["original_text"].tolist(), split.train["category"].tolist()
    )
    save_sklearn_model(pipe)

    class _Wrap:
        """평가 함수의 인터페이스(predict)에 맞추기 위한 얇은 래퍼."""

        def __init__(self, pipe):
            self.pipe = pipe

        def predict(self, texts):
            return list(self.pipe.predict(texts))

    return _Wrap(pipe)


def _train_sbert(split):
    from .classifier_sbert import SbertLgbmClassifier
    clf = SbertLgbmClassifier()
    clf.fit(split.train["original_text"].tolist(), split.train["category"].tolist())
    clf.save()
    return clf


def _train_kobert(split, epochs: int):
    from .classifier_kobert import predict_kobert, train_kobert
    out_dir = train_kobert(
        split.train["original_text"].tolist(),
        split.train["category"].tolist(),
        val_texts=split.val["original_text"].tolist(),
        val_labels=split.val["category"].tolist(),
        epochs=epochs,
    )

    class _Wrap:
        def __init__(self, d): self.d = d
        def predict(self, texts): return predict_kobert(self.d, texts)

    return _Wrap(out_dir)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["simple", "sklearn", "sbert", "kobert"],
                    default="simple")
    ap.add_argument("--epochs", type=int, default=5, help="kobert fine-tune epoch")
    ap.add_argument("--no-yunjeong", action="store_true",
                    help="윤정 csv 제외하고 notice_sample_v2만으로 학습")
    args = ap.parse_args()

    print(f"[train] model={args.model}")
    split = build_dataset(include_yunjeong_csv=not args.no_yunjeong)
    from .data_loader import summarize
    print(summarize(split))
    print()

    t0 = time.time()
    if args.model == "simple":
        clf = _train_simple(split)
    elif args.model == "sklearn":
        clf = _train_sklearn(split)
    elif args.model == "sbert":
        clf = _train_sbert(split)
    else:
        clf = _train_kobert(split, epochs=args.epochs)
    print(f"[train] classifier 완료 ({time.time() - t0:.1f}s)")

    # 중요도 모델
    t1 = time.time()
    scorer = ImportanceScorer()
    scorer.fit(
        split.train["original_text"].tolist(),
        split.train["category"].tolist(),
        split.train["importance"].tolist(),
    )
    scorer.save()
    print(f"[train] importance scorer 완료 ({time.time() - t1:.1f}s)")

    # 평가
    out = evaluate_pipeline(clf, scorer, split.test, name=args.model)
    print()
    print(out["markdown"])


if __name__ == "__main__":
    main()
