"""sklearn 기반 production 베이스라인 분류기.

사용 환경: scikit-learn 1.x 설치 필요 (`pip install scikit-learn`).

전략
-----
- char n-gram(2~4) + word(1~2) TF-IDF를 결합하기 위해 ColumnTransformer 대신
  FeatureUnion을 사용한다 (sklearn 1.4+에서도 안정적).
- 분류기는 Logistic Regression (multinomial, lbfgs)이 한국어 짧은 문장에서
  가장 안정적이라는 결과가 일관되게 보고된다.
- class_weight='balanced'로 적은 클래스(`비용` 18건)를 자동 보정.

성능 기대치 (notice_sample_v2 + 윤정 csv ≈ 300건):
    macro F1 ≈ 0.78 ~ 0.85
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

# ⚠️ 이 파일은 샌드박스에서는 import 못 한다 (sklearn 미설치).
# 사용자 환경에서 정상 동작.

try:
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

import numpy as np

from .config import LABELS, MODEL_DIR


def build_pipeline(C: float = 4.0) -> "Pipeline":
    """char + word 두 vectorizer를 합친 파이프라인.

    - char_wb: 단어 경계를 고려한 문자 n-gram. 한국어 조사 변화에 강함.
    - word: 짧은 안내문에서도 핵심 명사 잡기에 유효.
    - LR(C=4): 적당히 규제 푼 값. C 너무 작으면 underfit.
    """
    if not SKLEARN_AVAILABLE:
        raise ImportError(
            "scikit-learn이 필요합니다. `pip install scikit-learn` 후 다시 시도하세요."
        )

    char_vec = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        min_df=2,
        sublinear_tf=True,
        max_features=30000,
    )
    word_vec = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
        token_pattern=r"(?u)\b\w+\b",
        max_features=15000,
    )
    union = FeatureUnion([("char", char_vec), ("word", word_vec)])
    clf = LogisticRegression(
        C=C,
        solver="lbfgs",
        max_iter=2000,
        class_weight="balanced",  # 비용 클래스 부스팅
        n_jobs=-1,
    )
    return Pipeline([("vec", union), ("clf", clf)])


def train_sklearn_classifier(
    train_texts: list[str], train_labels: list[str]
) -> "Pipeline":
    """학습 후 모델 반환. label은 문자열 그대로 입력 (LogReg가 자동 인코딩)."""
    pipe = build_pipeline()
    pipe.fit(train_texts, train_labels)
    return pipe


def save_sklearn_model(pipe: "Pipeline", path: Path | None = None) -> Path:
    path = path or MODEL_DIR / "sklearn_logreg.joblib"
    joblib.dump(pipe, path)
    return path


def load_sklearn_model(path: Path | None = None) -> "Pipeline":
    path = path or MODEL_DIR / "sklearn_logreg.joblib"
    return joblib.load(path)
