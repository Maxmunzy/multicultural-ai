"""numpy로 직접 구현한 다항 Logistic Regression + TF-IDF 분류기.

왜 이런 가벼운 구현이 필요한가?
- 샌드박스(scikit-learn 미설치)에서도 학습/평가/추론을 즉시 보여 주기 위함.
- 사용자가 자기 환경에 transformers/sklearn을 깔지 못하는 즉시 운영
  상황에서도 의존성 없이 동작하는 안전망 백업.
- 같은 데이터로 SBERT 모델과 성능을 직접 비교할 수 있다.

알고리즘
--------
- 다항 로지스틱 회귀 (softmax cross-entropy)
- L2 정규화 (`weight_decay`)
- 미니배치 SGD (배치 32, lr=0.5, 200 epoch이면 200~300건에서 수렴)
- bias 항 포함

성능 가이드
-----------
char n-gram TF-IDF + 다항 LR은 한국어 짧은 안내문에서 macro F1 0.70~0.80에
도달하는 강력한 베이스라인이다. 이 환경에서 SBERT를 못 돌릴 때 첫 번째
실전 모델로 삼아도 충분하다.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import LABEL2ID, LABELS, MODEL_DIR, RANDOM_STATE
from .feature_engineering import extract_features
from .text_features import TfidfVectorizer


@dataclass
class SoftmaxClassifier:
    """다항 로지스틱 회귀.

    가중치 W: (n_features, n_classes), bias b: (n_classes,)
    예측 확률: softmax(x @ W + b)
    """

    n_classes: int
    learning_rate: float = 0.5
    weight_decay: float = 1e-4
    epochs: int = 250
    batch_size: int = 32
    seed: int = RANDOM_STATE

    W: np.ndarray = field(default_factory=lambda: np.zeros(0))
    b: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def _softmax(self, z: np.ndarray) -> np.ndarray:
        z = z - z.max(axis=1, keepdims=True)  # 수치 안정성
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def fit(self, X: np.ndarray, y: np.ndarray, *, class_weight: np.ndarray | None = None) -> "SoftmaxClassifier":
        rng = np.random.default_rng(self.seed)
        n, d = X.shape
        self.W = rng.normal(0, 0.01, size=(d, self.n_classes)).astype(np.float32)
        self.b = np.zeros(self.n_classes, dtype=np.float32)
        # 클래스 불균형 보정 가중치 (예: '비용' 18건처럼 적은 클래스 부스팅)
        if class_weight is None:
            counts = np.bincount(y, minlength=self.n_classes).astype(np.float32)
            class_weight = (counts.max() / np.clip(counts, 1, None)).astype(np.float32)

        for epoch in range(self.epochs):
            idx = rng.permutation(n)
            for start in range(0, n, self.batch_size):
                batch = idx[start : start + self.batch_size]
                xb, yb = X[batch], y[batch]
                # forward
                logits = xb @ self.W + self.b
                probs = self._softmax(logits)
                # cross-entropy gradient
                ohe = np.zeros_like(probs)
                ohe[np.arange(len(yb)), yb] = 1
                grad_logits = (probs - ohe) * class_weight[yb][:, None] / len(yb)
                grad_W = xb.T @ grad_logits + self.weight_decay * self.W
                grad_b = grad_logits.sum(axis=0)
                # decay learning rate (느린 코사인 형태)
                lr = self.learning_rate * (0.5 + 0.5 * np.cos(np.pi * epoch / self.epochs))
                self.W -= lr * grad_W
                self.b -= lr * grad_b
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._softmax(X @ self.W + self.b)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self.predict_proba(X), axis=1)


# ------------------------------------------------------------------------------
# 통합 분류 파이프라인
# ------------------------------------------------------------------------------
class SimpleNoticeClassifier:
    """TF-IDF + numpy LR + 룰 기반 카테고리 키워드 보조.

    피처 구성:
        [tfidf | urgency | submit_verb | money | health_urgent | length |
         kw_per_label * 6]
    이렇게 의미 신호(tfidf)와 명시적 룰 신호를 함께 주면, 적은 데이터에서도
    성능이 안정된다.
    """

    def __init__(self, *, epochs: int = 250, lr: float = 0.5):
        self.vectorizer = TfidfVectorizer(min_df=1, max_features=20000)
        self.clf = SoftmaxClassifier(
            n_classes=len(LABELS), epochs=epochs, learning_rate=lr
        )
        self._extra_keys: list[str] = []  # 추가 피처 컬럼 이름

    # --- 피처 구성 ----------------------------------------------------------
    def _extra_features(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        keys: list[str] = []
        for t in texts:
            f = extract_features(t)
            d = f.as_dict()
            # NaN을 0으로 (학습 안정)
            if np.isnan(d.get("days_to_deadline", float("nan"))):
                d["days_to_deadline"] = 14.0  # "마감 정보 없음" 디폴트
            d["text_length"] = min(d["text_length"], 200) / 200.0  # 정규화
            rows.append(list(d.values()))
            if not keys:
                keys = list(d.keys())
        self._extra_keys = keys
        return np.array(rows, dtype=np.float32)

    def _build_X(self, texts: list[str], *, fit: bool) -> np.ndarray:
        tfidf = (
            self.vectorizer.fit_transform(texts)
            if fit
            else self.vectorizer.transform(texts)
        )
        extra = self._extra_features(texts)
        return np.hstack([tfidf, extra]).astype(np.float32)

    # --- 학습/평가/추론 ----------------------------------------------------
    def fit(self, texts: list[str], labels: list[str]) -> "SimpleNoticeClassifier":
        X = self._build_X(texts, fit=True)
        y = np.array([LABEL2ID[l] for l in labels], dtype=np.int64)
        self.clf.fit(X, y)
        return self

    def predict(self, texts: list[str]) -> list[str]:
        X = self._build_X(texts, fit=False)
        ids = self.clf.predict(X)
        return [LABELS[i] for i in ids]

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        X = self._build_X(texts, fit=False)
        return self.clf.predict_proba(X)

    # --- 영속화 -------------------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        path = path or MODEL_DIR / "simple_classifier.pkl"
        with path.open("wb") as f:
            pickle.dump(self, f)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "SimpleNoticeClassifier":
        path = path or MODEL_DIR / "simple_classifier.pkl"
        with path.open("rb") as f:
            return pickle.load(f)


if __name__ == "__main__":
    # 빠른 동작 확인
    from .data_loader import build_dataset

    split = build_dataset()
    clf = SimpleNoticeClassifier(epochs=100)
    clf.fit(split.train["original_text"].tolist(), split.train["category"].tolist())
    preds = clf.predict(split.val["original_text"].tolist())
    correct = sum(p == y for p, y in zip(preds, split.val["category"].tolist()))
    print(f"validation accuracy={correct}/{len(preds)} = {correct/len(preds):.3f}")
