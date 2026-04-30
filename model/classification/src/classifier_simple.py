"""
베이스라인 분류기: TF-IDF + Logistic Regression
=================================================
담당: 경이
역할: 라벨 데이터(notice_sample_v3.csv + notices_labeled_v2.csv)로 학습한
      6-class 텍스트 분류기.
      GPU 불필요. CPU에서 수십 ms 이내 추론 가능.
      KcELECTRA 파인튜닝과 성능 비교할 베이스라인.

사용법:
    python classifier_simple.py          # 학습 + 저장
    python classifier_simple.py --eval   # 저장된 모델 평가
"""

import pickle
import argparse
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, confusion_matrix

# 경로 기준: model/classification/
_BASE = Path(__file__).parent.parent
DATA_CSV    = _BASE / "data" / "notice_sample_v3.csv"
LEGACY_CSV  = _BASE / "data" / "notices_labeled_v2.csv"   # 기존 라벨 데이터
SPLIT_CSV   = _BASE / "data" / "split_v1.csv"
MODEL_PKL   = _BASE / "checkpoints" / "simple_tfidf_logreg.pkl"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]

# 기존 CSV는 컬럼명이 'original_text'이므로 통일 처리
_TEXT_COLS = ["text", "original_text", "sentence"]


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼명이 다른 여러 데이터 소스를 text/category 형식으로 통일."""
    for col in _TEXT_COLS:
        if col in df.columns and "text" not in df.columns:
            df = df.rename(columns={col: "text"})
            break
    return df


# ─────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────
def load_data(split: str = "train") -> tuple[list[str], list[str]]:
    """split_v1.csv → 없으면 원본 CSV (+ legacy CSV 병합)에서 텍스트·라벨 로드.

    split: "train" | "val" | "test" | "all"
    """
    if SPLIT_CSV.exists():
        df = pd.read_csv(SPLIT_CSV)
        df = _normalize_df(df)
        if split != "all":
            df = df[df["split"] == split]
    else:
        frames = [pd.read_csv(DATA_CSV)]
        if LEGACY_CSV.exists():
            legacy = pd.read_csv(LEGACY_CSV)
            legacy = _normalize_df(legacy)
            frames.append(legacy)
        df = pd.concat(frames, ignore_index=True)
        df = _normalize_df(df)

    df = df.dropna(subset=["text", "category"])
    df = df[df["category"].isin(LABELS)]
    return df["text"].tolist(), df["category"].tolist()


# ─────────────────────────────────────────────────────────────
# 파이프라인 정의
# ─────────────────────────────────────────────────────────────
def build_pipeline() -> Pipeline:
    """TF-IDF + Logistic Regression 파이프라인.

    TF-IDF 파라미터:
      - analyzer="char_wb": 한국어는 글자 단위 n-gram이 어절 단위보다 OOV에 강함
      - ngram_range=(2, 4): 2~4글자 조합으로 형태소 정보 간접 포착
      - max_features=30000: 메모리·속도 균형
      - sublinear_tf=True: log(1+tf)로 빈도 폭발 억제
    LogReg 파라미터:
      - C=1.0: 기본 정규화 (오버피팅 방지)
      - max_iter=1000: 수렴 보장
      - class_weight="balanced": 클래스 불균형 대응
    """
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=30_000,
            sublinear_tf=True,
        )),
        ("clf", LogisticRegression(
            C=1.0,
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
            solver="lbfgs",
        )),
    ])


# ─────────────────────────────────────────────────────────────
# 학습
# ─────────────────────────────────────────────────────────────
def train() -> Pipeline:
    texts, labels = load_data("train")
    if not texts:
        texts, labels = load_data("all")

    pipe = build_pipeline()
    pipe.fit(texts, labels)

    MODEL_PKL.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PKL, "wb") as f:
        pickle.dump(pipe, f)
    print(f"[simple] 모델 저장 완료: {MODEL_PKL}")
    print(f"[simple] 학습 데이터 수: {len(texts)}개")
    return pipe


# ─────────────────────────────────────────────────────────────
# 로드 (캐시)
# ─────────────────────────────────────────────────────────────
_pipeline: Pipeline | None = None


def load_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    if not MODEL_PKL.exists():
        print("[simple] 저장된 모델 없음 → 학습 시작")
        _pipeline = train()
    else:
        with open(MODEL_PKL, "rb") as f:
            _pipeline = pickle.load(f)
    return _pipeline


# ─────────────────────────────────────────────────────────────
# 추론
# ─────────────────────────────────────────────────────────────
def predict_simple(text: str) -> dict:
    """텍스트 → 카테고리 + 신뢰도(각 클래스 확률).

    반환:
        {
            "category": str,          # 예측 라벨
            "confidence": float,      # 예측 클래스 확률
            "probs": dict[str, float] # 전체 클래스 확률 (explain 용)
        }
    """
    pipe = load_pipeline()
    proba = pipe.predict_proba([text])[0]
    classes = pipe.classes_

    idx = proba.argmax()
    return {
        "category":   classes[idx],
        "confidence": float(proba[idx]),
        "probs":      {c: float(p) for c, p in zip(classes, proba)},
    }


# ─────────────────────────────────────────────────────────────
# 평가
# ─────────────────────────────────────────────────────────────
def evaluate(split: str = "test") -> dict:
    texts, true_labels = load_data(split)
    if not texts:
        texts, true_labels = load_data("all")

    pipe = load_pipeline()
    pred_labels = pipe.predict(texts)

    report = classification_report(
        true_labels, pred_labels,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(true_labels, pred_labels, labels=LABELS)

    print("\n[simple] 분류 리포트")
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))
    print("[simple] Confusion Matrix")
    print(cm)

    return {"report": report, "confusion_matrix": cm.tolist(), "model": "simple"}


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", action="store_true", help="저장된 모델 평가")
    args = parser.parse_args()

    if args.eval:
        evaluate()
    else:
        train()
        evaluate("test")
