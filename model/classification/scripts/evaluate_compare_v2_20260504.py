"""
evaluate_compare_v2_20260504.py
================================
담당: 경이 (kyeongyi)
작성일: 2026-05-04

목적:
    split_v2_20260504.csv (695개 확장 데이터) 기준으로
    두 모델의 성능을 비교·저장한다.

    [비교 모델]
      1. Simple   : TF-IDF + Logistic Regression (베이스라인)
      2. KcELECTRA: 파인튜닝 모델 (03_train_kcelectra_v2_20260504.ipynb 실행 후 사용 가능)

    [공정 비교 원칙]
      - 두 모델 모두 split_v2_20260504.csv의 동일한 test 세트(69개)로 평가
      - 학습 데이터도 동일한 train 세트(556개) 사용

    [출력 파일 — 타임스탬프 포함]
      data/eval_results_simple_20260504.json
      data/eval_results_kcelectra_20260504.json   (KcELECTRA 준비 후 생성)
      data/eval_comparison_summary_20260504.csv

실행:
    cd model/classification
    python scripts/evaluate_compare_v2_20260504.py
    python scripts/evaluate_compare_v2_20260504.py --split val   # val 세트로 평가
"""

import argparse
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.pipeline import Pipeline

_BASE = Path(__file__).parent.parent
sys.path.insert(0, str(_BASE / "src"))

SPLIT_CSV    = _BASE / "data" / "split_v2_20260504.csv"
SIMPLE_PKL   = _BASE / "checkpoints" / "simple_tfidf_logreg_v2_20260504.pkl"
KCELECTRA_CKPT = _BASE / "checkpoints" / "kcelectra-category-v2"

DATA_DIR = _BASE / "data"
TS       = "20260504"  # 타임스탬프

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]


# ──────────────────────────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────────────────────────
def load_split(split: str = "test") -> tuple[list[str], list[str]]:
    """
    split_v2_20260504.csv에서 지정한 split의 text와 category를 반환.
    split: "train" | "val" | "test"
    """
    if not SPLIT_CSV.exists():
        raise FileNotFoundError(
            f"{SPLIT_CSV} 없음 — split_dataset_v2_20260504.py 먼저 실행하세요."
        )
    df = pd.read_csv(SPLIT_CSV, encoding="utf-8-sig")
    df = df[df["split"] == split]
    df = df[df["category"].isin(LABELS)]
    return df["text"].tolist(), df["category"].tolist()


# ──────────────────────────────────────────────────────────────────
# Simple 모델 (TF-IDF + LogReg)
# ──────────────────────────────────────────────────────────────────
def train_simple() -> Pipeline:
    """
    v2 train 데이터로 베이스라인 재학습.

    왜 재학습이 필요한가?
      기존 simple_tfidf_logreg.pkl은 v1 데이터(244개) 기준으로 학습됨.
      v2 데이터(556개 train)로 재학습해야 동일 조건의 비교가 가능.
    """
    texts, labels = load_split("train")
    print(f"[simple] train 데이터: {len(texts)}개")

    pipe = Pipeline([
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
    pipe.fit(texts, labels)

    SIMPLE_PKL.parent.mkdir(parents=True, exist_ok=True)
    with open(SIMPLE_PKL, "wb") as f:
        pickle.dump(pipe, f)
    print(f"[simple] 모델 저장: {SIMPLE_PKL.name}")
    return pipe


def _load_simple() -> Pipeline:
    if SIMPLE_PKL.exists():
        with open(SIMPLE_PKL, "rb") as f:
            return pickle.load(f)
    return train_simple()


def evaluate_simple(split: str = "test") -> dict:
    """Simple 모델 평가 → 결과 dict 반환."""
    texts, true_labels = load_split(split)
    pipe = _load_simple()
    pred_labels = pipe.predict(texts)

    report = classification_report(
        true_labels, pred_labels,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)

    print("\n[Simple] 분류 리포트")
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))

    # 결과 구조 — 노트북 시각화와 호환되는 형식
    result = {
        "model":          "simple",
        "macro_f1":       round(macro_f1, 4),
        "macro_precision": round(report["macro avg"]["precision"], 4),
        "macro_recall":   round(report["macro avg"]["recall"], 4),
        "per_class": {
            lbl: {
                "precision": round(report[lbl]["precision"], 4),
                "recall":    round(report[lbl]["recall"], 4),
                "f1":        round(report[lbl]["f1-score"], 4),
                "support":   report[lbl]["support"],
            }
            for lbl in LABELS
        },
        "confusion_matrix": cm.tolist(),
        "labels":           LABELS,
        "split_used":       split,
        "data_version":     "v4_20260504",
        "train_size":       len(load_split("train")[0]),
        "test_size":        len(texts),
    }
    return result


# ──────────────────────────────────────────────────────────────────
# KcELECTRA 모델
# ──────────────────────────────────────────────────────────────────
def _kcelectra_ready() -> bool:
    """
    03_train_kcelectra_v2_20260504.ipynb 실행 후 생성되는 체크포인트 확인.
    체크포인트 없으면 평가 스킵 — 에러 없이 진행.
    """
    try:
        import torch  # noqa: F401
        from transformers import AutoTokenizer  # noqa: F401
    except ImportError:
        print("[kcelectra] torch/transformers 미설치 — KcELECTRA 평가 스킵")
        return False

    required = [
        KCELECTRA_CKPT / "config.json",
        KCELECTRA_CKPT / "label2id.json",
    ]
    model_file = (
        (KCELECTRA_CKPT / "model.safetensors").exists()
        or (KCELECTRA_CKPT / "pytorch_model.bin").exists()
    )
    return all(f.exists() for f in required) and model_file


def evaluate_kcelectra(split: str = "test") -> dict:
    """
    KcELECTRA 평가.
    체크포인트 없거나 torch 미설치 → 빈 dict 반환 (스킵).

    eval_results_kcelectra_20260504.json이 이미 있으면 재사용.
    (Colab에서 학습 후 JSON만 복사해도 동작)
    """
    json_path = DATA_DIR / f"eval_results_kcelectra_{TS}.json"

    # JSON 재활용 (Colab에서 다운로드해서 data/ 에 넣은 경우)
    if json_path.exists():
        print(f"[kcelectra] 기존 JSON 재활용: {json_path.name}")
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)

    if not _kcelectra_ready():
        print("[kcelectra] 체크포인트 없음 — 03_train_kcelectra_v2_20260504.ipynb 실행 후 재시도")
        return {}

    # 체크포인트가 있을 때만 실행
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    texts, true_labels = load_split(split)

    with open(KCELECTRA_CKPT / "label2id.json", encoding="utf-8") as f:
        label2id: dict[str, int] = json.load(f)
    id2label = {v: k for k, v in label2id.items()}

    device    = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(str(KCELECTRA_CKPT))
    model     = AutoModelForSequenceClassification.from_pretrained(
        str(KCELECTRA_CKPT), num_labels=len(LABELS), ignore_mismatched_sizes=True
    ).to(device)
    model.eval()

    pred_labels = []
    with torch.no_grad():
        for text in texts:
            enc = tokenizer(text, return_tensors="pt",
                            truncation=True, padding=True, max_length=128).to(device)
            logits = model(**enc).logits
            idx    = int(logits.argmax(dim=-1).item())
            pred_labels.append(id2label.get(idx, "기타"))

    report = classification_report(
        true_labels, pred_labels,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)

    print("\n[KcELECTRA] 분류 리포트")
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))

    result = {
        "model":          "kcelectra",
        "macro_f1":       round(macro_f1, 4),
        "macro_precision": round(report["macro avg"]["precision"], 4),
        "macro_recall":   round(report["macro avg"]["recall"], 4),
        "per_class": {
            lbl: {
                "precision": round(report[lbl]["precision"], 4),
                "recall":    round(report[lbl]["recall"], 4),
                "f1":        round(report[lbl]["f1-score"], 4),
                "support":   report[lbl]["support"],
            }
            for lbl in LABELS
        },
        "confusion_matrix": cm.tolist(),
        "labels":           LABELS,
        "split_used":       split,
        "data_version":     "v4_20260504",
    }
    return result


# ──────────────────────────────────────────────────────────────────
# 저장 + 비교 출력
# ──────────────────────────────────────────────────────────────────
def save_and_compare(simple_res: dict, kcelectra_res: dict) -> None:
    # Simple 결과 저장
    simple_path = DATA_DIR / f"eval_results_simple_{TS}.json"
    with open(simple_path, "w", encoding="utf-8") as f:
        json.dump(simple_res, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {simple_path.name}")

    # KcELECTRA 결과 저장 (있을 때만)
    kc_path = DATA_DIR / f"eval_results_kcelectra_{TS}.json"
    if kcelectra_res:
        with open(kc_path, "w", encoding="utf-8") as f:
            json.dump(kcelectra_res, f, ensure_ascii=False, indent=2)
        print(f"[저장] {kc_path.name}")

    # 비교 요약 CSV
    rows = [{"model": "Simple (TF-IDF + LR)", **_summary_row(simple_res)}]
    if kcelectra_res:
        rows.append({"model": "KcELECTRA (fine-tuned)", **_summary_row(kcelectra_res)})

    summary_df = pd.DataFrame(rows)
    summary_path = DATA_DIR / f"eval_comparison_summary_{TS}.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"[저장] {summary_path.name}")

    # 채택 판정
    print("\n" + "=" * 50)
    print("  성능 비교 결과")
    print("=" * 50)
    print(f"  Simple    Macro F1 : {simple_res['macro_f1']:.4f}")
    if kcelectra_res:
        delta = kcelectra_res["macro_f1"] - simple_res["macro_f1"]
        print(f"  KcELECTRA Macro F1 : {kcelectra_res['macro_f1']:.4f}")
        print(f"  Delta              : {delta:+.4f}")
        if delta >= 0.05:
            print("  >> KcELECTRA 5%+ 향상: 채택 권장!")
        elif delta >= 0:
            print("  >> KcELECTRA 소폭 향상: 추가 데이터/튜닝 권장")
        else:
            print("  >> Simple 유지 권장")
    else:
        print("  KcELECTRA: 평가 미완료 (노트북 실행 후 재시도)")


def _summary_row(res: dict) -> dict:
    row = {
        "macro_f1":        res.get("macro_f1", "-"),
        "macro_precision": res.get("macro_precision", "-"),
        "macro_recall":    res.get("macro_recall", "-"),
    }
    for lbl in LABELS:
        row[f"f1_{lbl}"] = res.get("per_class", {}).get(lbl, {}).get("f1", "-")
    return row


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--retrain", action="store_true",
                        help="Simple 모델 강제 재학습 (PKL 있어도 새로 학습)")
    args = parser.parse_args()

    print(f"평가 시작 — split: {args.split}, 데이터: v4_20260504")

    # Simple 재학습 여부
    if args.retrain and SIMPLE_PKL.exists():
        SIMPLE_PKL.unlink()
        print("[simple] 기존 PKL 삭제 → 재학습")

    simple_res     = evaluate_simple(args.split)
    kcelectra_res  = evaluate_kcelectra(args.split)

    save_and_compare(simple_res, kcelectra_res)


if __name__ == "__main__":
    main()
