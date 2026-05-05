"""
evaluate_compare_v6_20260506.py
================================
담당: 경이 (kyeongyi)
작성일: 2026-05-06

목적:
    split_v6_20260506.csv (5412행 v6 데이터) 기준으로
    두 모델의 성능을 비교·저장·출력한다.

    [비교 모델]
      1. Simple   : TF-IDF + Logistic Regression (베이스라인, v6 train 재학습)
      2. KcELECTRA: 파인튜닝 모델 v7 (10_train_kcelectra_v7_20260506.ipynb 실행 후)

    [출력 파일 - data/20260506/ 폴더]
      eval_results_simple_v6_20260506.json
      eval_results_kcelectra_v6_20260506.json
      eval_comparison_summary_v6_20260506.csv

실행:
    cd model/classification
    python scripts/evaluate_compare_v6_20260506.py
    python scripts/evaluate_compare_v6_20260506.py --split val
    python scripts/evaluate_compare_v6_20260506.py --retrain   # Simple 강제 재학습
"""

import argparse
import json
import pickle
import sys
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

SPLIT_CSV      = _BASE / "data" / "split_v6_20260506.csv"
SIMPLE_PKL     = _BASE / "checkpoints" / "simple_tfidf_logreg_v6_20260506.pkl"
KCELECTRA_CKPT = _BASE / "checkpoints" / "kcelectra-category-v7"
OUT_DIR        = _BASE / "data" / "20260506"
TS             = "v6_20260506"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]


# ──────────────────────────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────────────────────────
def load_split(split: str = "test") -> tuple[list[str], list[str]]:
    if not SPLIT_CSV.exists():
        raise FileNotFoundError(
            f"{SPLIT_CSV} 없음 - split_dataset_v6_20260506.py 먼저 실행하세요."
        )
    df = pd.read_csv(SPLIT_CSV, encoding="utf-8-sig")
    df = df[df["split"] == split]
    df = df[df["category"].isin(LABELS)]
    return df["text"].tolist(), df["category"].tolist()


# ──────────────────────────────────────────────────────────────────
# Simple 모델 (TF-IDF + LogReg)
# ──────────────────────────────────────────────────────────────────
def train_simple() -> Pipeline:
    texts, labels = load_split("train")
    print(f"[simple] train 데이터: {len(texts)}개")

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=50_000,
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
    texts, true_labels = load_split(split)
    pipe = _load_simple()
    pred_labels = pipe.predict(texts)

    report = classification_report(
        true_labels, pred_labels,
        labels=LABELS, output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)

    print("\n[Simple - TF-IDF + LogReg] 분류 리포트")
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))

    return {
        "model":            "simple",
        "version":          "v6",
        "macro_f1":         round(macro_f1, 4),
        "macro_precision":  round(report["macro avg"]["precision"], 4),
        "macro_recall":     round(report["macro avg"]["recall"], 4),
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
        "data_version":     "v6_20260506",
        "train_size":       len(load_split("train")[0]),
        "test_size":        len(texts),
    }


# ──────────────────────────────────────────────────────────────────
# KcELECTRA 모델 (v7 체크포인트)
# ──────────────────────────────────────────────────────────────────
def _kcelectra_ready() -> bool:
    try:
        import torch          # noqa: F401
        from transformers import AutoTokenizer  # noqa: F401
    except ImportError:
        print("[kcelectra] torch/transformers 미설치 - 스킵")
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
    KcELECTRA v7 평가.
    eval_results_kcelectra_v6_20260506.json이 있으면 재활용 (Colab 결과 복붙 시).
    """
    json_path = OUT_DIR / f"eval_results_kcelectra_{TS}.json"

    if json_path.exists():
        print(f"[kcelectra] 기존 JSON 재활용: {json_path.name}")
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)

    if not _kcelectra_ready():
        print(f"[kcelectra] 체크포인트 없음: {KCELECTRA_CKPT}")
        print("  10_train_kcelectra_v7_20260506.ipynb 실행 후 kcelectra-category-v7/를 checkpoints/에 배치하세요.")
        return {}

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
            enc    = tokenizer(text, return_tensors="pt",
                               truncation=True, padding=True, max_length=128).to(device)
            logits = model(**enc).logits
            idx    = int(logits.argmax(dim=-1).item())
            pred_labels.append(id2label.get(idx, "기타"))

    report = classification_report(
        true_labels, pred_labels,
        labels=LABELS, output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)

    print("\n[KcELECTRA v7] 분류 리포트")
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))

    result = {
        "model":            "kcelectra",
        "version":          "v7",
        "macro_f1":         round(macro_f1, 4),
        "macro_precision":  round(report["macro avg"]["precision"], 4),
        "macro_recall":     round(report["macro avg"]["recall"], 4),
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
        "data_version":     "v6_20260506",
    }
    return result


# ──────────────────────────────────────────────────────────────────
# 저장 + 비교 출력
# ──────────────────────────────────────────────────────────────────
def save_and_compare(simple_res: dict, kcelectra_res: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    simple_path = OUT_DIR / f"eval_results_simple_{TS}.json"
    with open(simple_path, "w", encoding="utf-8") as f:
        json.dump(simple_res, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {simple_path.name}")

    kc_path = OUT_DIR / f"eval_results_kcelectra_{TS}.json"
    if kcelectra_res:
        with open(kc_path, "w", encoding="utf-8") as f:
            json.dump(kcelectra_res, f, ensure_ascii=False, indent=2)
        print(f"[저장] {kc_path.name}")

    rows = [{"model": "Simple (TF-IDF + LR, v6)", **_summary_row(simple_res)}]
    if kcelectra_res:
        rows.append({"model": "KcELECTRA v7 (fine-tuned, v6)", **_summary_row(kcelectra_res)})

    summary_df   = pd.DataFrame(rows)
    summary_path = OUT_DIR / f"eval_comparison_summary_{TS}.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"[저장] {summary_path.name}")

    # 비교 출력
    SIMPLE_V5_F1 = 0.8116  # v5 데이터 기준 베이스라인 (비교 기준 유지)
    V3_TEST_F1   = 0.8545

    print("\n" + "=" * 60)
    print("  성능 비교 결과 (v6 데이터 - 5412행)")
    print("=" * 60)
    print(f"  [참고] v5 Simple 베이스라인: {SIMPLE_V5_F1:.4f}")
    print(f"  [참고] v3 KcELECTRA Test F1: {V3_TEST_F1:.4f}")
    print(f"  Simple v6  Macro F1 : {simple_res['macro_f1']:.4f}  (v5 대비: {simple_res['macro_f1'] - SIMPLE_V5_F1:+.4f})")

    if kcelectra_res:
        delta_simple  = kcelectra_res["macro_f1"] - simple_res["macro_f1"]
        delta_v5base  = kcelectra_res["macro_f1"] - SIMPLE_V5_F1
        delta_v3      = kcelectra_res["macro_f1"] - V3_TEST_F1
        print(f"  KcELECTRA v7 Macro F1 : {kcelectra_res['macro_f1']:.4f}")
        print(f"  v5 Simple 대비        : {delta_v5base:+.4f}")
        print(f"  v3 KcELECTRA 대비     : {delta_v3:+.4f}")
        print()
        if delta_v5base >= 0.05:
            print("  ★ v5 Simple 대비 5%+ 향상 — 최종 목표 달성!")
        elif delta_v3 > 0:
            print("  ↑ v3 KcELECTRA 초과 — v7 채택, 5% 목표에 근접")
        elif kcelectra_res["macro_f1"] > SIMPLE_V5_F1:
            print("  ~ Simple보다 향상 (v3 미달 또는 동등)")
        else:
            print("  ✗ Simple보다 낮음 — 추가 분석 필요")

        print("\n  [카테고리별 F1 비교]")
        print(f"  {'카테고리':10s} {'Simple':>8s} {'KcELECTRA':>10s} {'차이':>8s}")
        print("  " + "-" * 42)
        for lbl in LABELS:
            s_f1 = simple_res["per_class"].get(lbl, {}).get("f1", 0)
            k_f1 = kcelectra_res["per_class"].get(lbl, {}).get("f1", 0)
            diff = k_f1 - s_f1
            mark = "↑" if diff > 0.02 else ("↓" if diff < -0.02 else "~")
            print(f"  {lbl:10s} {s_f1:>8.4f} {k_f1:>10.4f} {diff:>+7.4f} {mark}")
    else:
        print("  KcELECTRA v7: 평가 미완료 — 10_train_kcelectra_v7_20260506.ipynb 실행 후 재시도")

    print(f"\n[출력 폴더] {OUT_DIR}")


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

    print(f"평가 시작 - split: {args.split}, 데이터: v6_20260506")

    if args.retrain and SIMPLE_PKL.exists():
        SIMPLE_PKL.unlink()
        print("[simple] 기존 PKL 삭제 → 재학습")

    simple_res    = evaluate_simple(args.split)
    kcelectra_res = evaluate_kcelectra(args.split)

    save_and_compare(simple_res, kcelectra_res)


if __name__ == "__main__":
    main()
