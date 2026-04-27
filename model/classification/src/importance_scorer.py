"""중요도(0~1) 산출기. 룰과 학습 회귀를 가중 평균해 최종 점수를 만든다.

설계 포인트
-----------
1. **룰 점수**(rule_importance): 카테고리 베이스 + 시급도 + 행동 신호.
   해석 가능하고 작은 데이터에서도 견고.
2. **학습 회귀**(numpy KernelRidge 대안 = ridge regression on TF-IDF + features):
   사람 라벨에서 패턴을 학습. 룰이 못 잡는 미세 신호를 잡는다.
3. **가중 평균**(`config.IMPORTANCE_RULE_WEIGHT`): 데이터가 적을수록 룰 비중을
   높이고, 데이터가 많아지면 모델 비중을 키워 가는 방식.

이 환경(샌드박스, sklearn 미설치)에서는 numpy로 ridge regression을 직접
구현해 동일한 인터페이스로 동작하게 한다. production에서는 sklearn/LightGBM
회귀로 그대로 갈아끼울 수 있다.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from .config import (
    CATEGORY_BASE_IMPORTANCE,
    IMPORTANCE_MODEL_WEIGHT,
    IMPORTANCE_RULE_WEIGHT,
    LABELS,
    MODEL_DIR,
)
from .feature_engineering import extract_features, rule_importance
from .text_features import TfidfVectorizer


# ------------------------------------------------------------------------------
# 1. Ridge Regression (numpy)
# ------------------------------------------------------------------------------
@dataclass
class RidgeRegressor:
    """Closed-form ridge regression: w = (X^T X + αI)^-1 X^T y.

    왜 ridge?
    - 작은 데이터(300건)에서 OLS는 발산하기 쉽다. α(L2 패널티)로 안정화.
    - SGD가 필요없고 closed-form이라 1초 내 학습.
    - 같은 인터페이스로 LightGBM Regressor로 교체 가능.
    """

    alpha: float = 1.0
    w: np.ndarray = field(default_factory=lambda: np.zeros(0))
    b: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RidgeRegressor":
        # bias trick: append 1 column
        X1 = np.hstack([X, np.ones((len(X), 1), dtype=X.dtype)])
        n, d = X1.shape
        # (X^T X + alpha * I) w = X^T y, identity excludes bias dim
        I = np.eye(d, dtype=X1.dtype)
        I[-1, -1] = 0  # bias 항은 패널티 안 받음
        A = X1.T @ X1 + self.alpha * I
        b_vec = X1.T @ y
        # solve
        try:
            theta = np.linalg.solve(A, b_vec)
        except np.linalg.LinAlgError:
            theta = np.linalg.lstsq(A, b_vec, rcond=None)[0]
        self.w = theta[:-1].astype(np.float32)
        self.b = float(theta[-1])
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return X @ self.w + self.b


# ------------------------------------------------------------------------------
# 2. ImportanceScorer (룰 + 회귀 결합)
# ------------------------------------------------------------------------------
class ImportanceScorer:
    """입력: 텍스트 + 카테고리(예측값 또는 정답) → importance(0~1).

    학습은 데이터프레임 단위로 한 번 호출. 추론은 (text, category) 쌍 단위.
    """

    def __init__(
        self,
        *,
        rule_weight: float = IMPORTANCE_RULE_WEIGHT,
        model_weight: float = IMPORTANCE_MODEL_WEIGHT,
        ridge_alpha: float = 1.0,
    ):
        self.rule_weight = rule_weight
        self.model_weight = model_weight
        # tfidf 줄여서 회귀 입력 크기 안정화
        self.vectorizer = TfidfVectorizer(min_df=2, max_features=8000)
        self.regressor = RidgeRegressor(alpha=ridge_alpha)
        self._cat_index: dict[str, int] = {l: i for i, l in enumerate(LABELS)}

    # --- 피처 ---------------------------------------------------------------
    def _build_X(self, texts: list[str], categories: list[str], *, fit: bool) -> np.ndarray:
        tfidf = (
            self.vectorizer.fit_transform(texts)
            if fit
            else self.vectorizer.transform(texts)
        )
        extras = []
        cat_oh = np.zeros((len(texts), len(LABELS)), dtype=np.float32)
        for i, (t, c) in enumerate(zip(texts, categories)):
            f = extract_features(t)
            d = f.as_dict()
            days = d.get("days_to_deadline", float("nan"))
            if np.isnan(days):
                days = 14.0
            extras.append(
                [
                    d["urgency_score"],
                    d["has_deadline"],
                    d["has_today_tomorrow"],
                    d["has_this_week"],
                    d["has_next_week"],
                    np.log1p(days),
                    d["has_submit_verb"],
                    d["has_money"],
                    d["has_no_action"],
                    d["has_health_urgent"],
                    min(d["text_length"], 200) / 200.0,
                    rule_importance(t, c),  # 룰 점수도 입력 피처로 (boosting)
                ]
            )
            if c in self._cat_index:
                cat_oh[i, self._cat_index[c]] = 1.0
        extras_arr = np.asarray(extras, dtype=np.float32)
        return np.hstack([tfidf, extras_arr, cat_oh]).astype(np.float32)

    # --- 학습 ---------------------------------------------------------------
    def fit(
        self, texts: list[str], categories: list[str], importance: list[float]
    ) -> "ImportanceScorer":
        # importance 결측 행은 제거
        keep = [i for i, v in enumerate(importance) if v is not None and not np.isnan(v)]
        texts = [texts[i] for i in keep]
        categories = [categories[i] for i in keep]
        y = np.array([importance[i] for i in keep], dtype=np.float32)
        X = self._build_X(texts, categories, fit=True)
        self.regressor.fit(X, y)
        return self

    # --- 추론 ---------------------------------------------------------------
    def predict(
        self,
        texts: list[str],
        categories: list[str],
        *,
        today: date | None = None,
    ) -> np.ndarray:
        # 1) 학습된 회귀 점수
        X = self._build_X(texts, categories, fit=False)
        model_score = self.regressor.predict(X)
        # 2) 룰 점수 (학습 안 한 안전망)
        rule_score = np.array(
            [rule_importance(t, c, today=today) for t, c in zip(texts, categories)],
            dtype=np.float32,
        )
        # 3) 가중 평균
        score = self.rule_weight * rule_score + self.model_weight * model_score
        return np.clip(score, 0.30, 1.0)

    def predict_one(self, text: str, category: str, *, today: date | None = None) -> float:
        return float(self.predict([text], [category], today=today)[0])

    # --- 영속화 -------------------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        path = path or MODEL_DIR / "importance_scorer.pkl"
        with path.open("wb") as f:
            pickle.dump(self, f)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "ImportanceScorer":
        path = path or MODEL_DIR / "importance_scorer.pkl"
        with path.open("rb") as f:
            return pickle.load(f)


if __name__ == "__main__":
    from .data_loader import build_dataset

    split = build_dataset()
    scorer = ImportanceScorer()
    scorer.fit(
        split.train["original_text"].tolist(),
        split.train["category"].tolist(),
        split.train["importance"].tolist(),
    )
    preds = scorer.predict(
        split.val["original_text"].tolist(),
        split.val["category"].tolist(),
    )
    y = split.val["importance"].values
    mae = float(np.mean(np.abs(preds - y)))
    print(f"validation MAE = {mae:.4f}")
    # 몇 개 샘플 출력
    for t, c, p, gt in list(zip(
        split.val["original_text"], split.val["category"], preds, y
    ))[:6]:
        print(f"  pred={p:.2f}  gt={gt:.2f}  [{c}] {t[:60]}")
