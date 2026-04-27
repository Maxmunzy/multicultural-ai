"""SBERT 임베딩 + LightGBM 분류기 (메인 권장 모델, CPU 친화).

왜 이 조합인가?
---------------
1. **SBERT (sentence-transformers)**: 한국어 짧은 안내문에서 의미 단위 유사도를
   잘 잡는다. CPU에서도 ~ms/문장으로 충분히 빠르다.
2. **LightGBM**: 트리 부스팅이라 비선형 결합/소수 클래스에 강하다. 200~500건
   같은 작은 데이터에서도 신경망 분류 헤드보다 안정적.
3. **임베딩 캐시**: SBERT 임베딩은 한 번만 계산하고 .npy로 저장. 재학습은
   초 단위.

추천 모델 (config.SBERT_MODELS 순서대로 fallback):
- paraphrase-multilingual-MiniLM-L12-v2 (50MB, 빠름, 다국어)
- jhgan/ko-sroberta-multitask (한국어 STS 강력)

사용법:
    from src.classifier_sbert import SbertLgbmClassifier
    clf = SbertLgbmClassifier()
    clf.fit(train_texts, train_labels)
    preds = clf.predict(test_texts)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import LABEL2ID, LABELS, MODEL_DIR, SBERT_MODELS
from .feature_engineering import extract_features

try:
    from sentence_transformers import SentenceTransformer
    SBERT_OK = True
except ImportError:
    SBERT_OK = False

try:
    import lightgbm as lgb
    LGB_OK = True
except ImportError:
    LGB_OK = False

try:
    import joblib
except ImportError:
    joblib = None


def _load_sbert(model_name: str | None = None) -> "SentenceTransformer":
    """가장 가벼운 모델부터 시도. 다운로드 실패 시 다음 후보로 fallback."""
    if not SBERT_OK:
        raise ImportError(
            "`pip install sentence-transformers` 가 필요합니다."
        )
    candidates = [model_name] if model_name else list(SBERT_MODELS)
    last_err: Exception | None = None
    for cand in candidates:
        try:
            return SentenceTransformer(cand, device="cpu")
        except Exception as e:  # 인터넷/공간 부족 등
            last_err = e
            continue
    raise RuntimeError(f"SBERT 모델 로드 실패. 마지막 에러: {last_err}")


def _build_extra(texts: list[str]) -> np.ndarray:
    """룰 기반 보조 피처 (시급도 등)를 임베딩 옆에 붙인다."""
    rows = []
    for t in texts:
        f = extract_features(t)
        d = f.as_dict()
        days = d.get("days_to_deadline", float("nan"))
        if np.isnan(days):
            days = 14.0
        rows.append(
            [
                d["urgency_score"],
                d["has_deadline"],
                d["has_today_tomorrow"],
                d["has_this_week"],
                d["has_submit_verb"],
                d["has_money"],
                d["has_no_action"],
                d["has_health_urgent"],
                np.log1p(days),
                min(d["text_length"], 200) / 200.0,
                d["kw_제출"], d["kw_준비물"], d["kw_일정"],
                d["kw_비용"], d["kw_건강·안전"], d["kw_기타"],
            ]
        )
    return np.asarray(rows, dtype=np.float32)


class SbertLgbmClassifier:
    """SBERT 임베딩 + 보조 피처 → LightGBM 다중 분류."""

    def __init__(self, *, sbert_model: str | None = None, num_leaves: int = 31):
        self.sbert_name = sbert_model
        self.num_leaves = num_leaves
        self._sbert: "SentenceTransformer | None" = None
        self._booster: "lgb.Booster | None" = None

    def _ensure_sbert(self):
        if self._sbert is None:
            self._sbert = _load_sbert(self.sbert_name)
        return self._sbert

    def _embed(self, texts: list[str]) -> np.ndarray:
        sbert = self._ensure_sbert()
        emb = sbert.encode(
            texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(emb, dtype=np.float32)

    def _features(self, texts: list[str]) -> np.ndarray:
        return np.hstack([self._embed(texts), _build_extra(texts)])

    def fit(self, texts: list[str], labels: list[str]) -> "SbertLgbmClassifier":
        if not LGB_OK:
            raise ImportError("`pip install lightgbm` 가 필요합니다.")
        X = self._features(texts)
        y = np.array([LABEL2ID[l] for l in labels], dtype=np.int64)
        train_set = lgb.Dataset(X, label=y)
        params = {
            "objective": "multiclass",
            "num_class": len(LABELS),
            "metric": "multi_logloss",
            "num_leaves": self.num_leaves,
            "learning_rate": 0.05,
            "feature_fraction": 0.85,
            "bagging_fraction": 0.85,
            "bagging_freq": 5,
            "min_data_in_leaf": 5,
            "verbosity": -1,
        }
        self._booster = lgb.train(
            params, train_set, num_boost_round=400,
            callbacks=[lgb.early_stopping(40)] if False else None,
        )
        return self

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        if self._booster is None:
            raise RuntimeError("fit() 먼저 호출하세요.")
        X = self._features(texts)
        return self._booster.predict(X)

    def predict(self, texts: list[str]) -> list[str]:
        proba = self.predict_proba(texts)
        return [LABELS[i] for i in np.argmax(proba, axis=1)]

    def save(self, dirpath: Path | None = None) -> Path:
        dirpath = dirpath or MODEL_DIR / "sbert_lgbm"
        dirpath.mkdir(parents=True, exist_ok=True)
        if self._booster is not None:
            self._booster.save_model(str(dirpath / "booster.txt"))
        meta = {
            "sbert_name": self.sbert_name,
            "num_leaves": self.num_leaves,
            "labels": list(LABELS),
        }
        if joblib is not None:
            joblib.dump(meta, dirpath / "meta.joblib")
        return dirpath

    @classmethod
    def load(cls, dirpath: Path | None = None) -> "SbertLgbmClassifier":
        dirpath = dirpath or MODEL_DIR / "sbert_lgbm"
        meta = joblib.load(dirpath / "meta.joblib")
        obj = cls(sbert_model=meta["sbert_name"], num_leaves=meta["num_leaves"])
        obj._booster = lgb.Booster(model_file=str(dirpath / "booster.txt"))
        return obj
