"""
베이스라인 vs KcELECTRA 성능 비교 스크립트
===========================================
담당: 경이
목적: 동일한 test 데이터로 두 모델의 성능을 비교하여 CSV·JSON으로 저장.
      결과는 02_evaluate_compare.ipynb에서 시각화.

실행:
    python scripts/evaluate_compare.py              # test split 평가
    python scripts/evaluate_compare.py --split val  # val split 평가

결과 파일:
    data/eval_results_simple.json
    data/eval_results_kcelectra.json
    data/eval_comparison_summary.csv

평가 지표:
    - Macro F1  : 클래스 불균형 무관 전체 성능 (메인 지표)
    - Per-class F1, Precision, Recall
    - Confusion Matrix
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

_BASE = Path(__file__).parent.parent
sys.path.insert(0, str(_BASE))

from src.classifier_simple import load_pipeline, load_data
from src.classifier_kcelectra import predict_kcelectra, is_ready as kcelectra_ready

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]
OUT_DIR = _BASE / "data"


def evaluate_simple(split: str = "test") -> dict:
    texts, true_labels = load_data(split)
    if not texts:
        texts, true_labels = load_data("all")

    pipe = load_pipeline()
    pred_labels = pipe.predict(texts)

    return _make_result("simple", true_labels, list(pred_labels))


def evaluate_kcelectra(split: str = "test") -> dict:
    # Colab에서 이미 평가한 JSON이 있으면 재활용 (torch 없는 환경에서도 비교 가능)
    cached_json = OUT_DIR / "eval_results_kcelectra.json"
    if cached_json.exists() and not kcelectra_ready():
        print(f"[compare] Colab 결과 파일 사용: {cached_json.name}")
        with open(cached_json, encoding="utf-8") as f:
            return json.load(f)

    if not kcelectra_ready():
        print("[compare] KcELECTRA 체크포인트 없음. 01_train_kcelectra.ipynb 먼저 실행하세요.")
        return {}

    texts, true_labels = load_data(split)
    if not texts:
        texts, true_labels = load_data("all")

    pred_labels = [predict_kcelectra(t)["category"] for t in texts]
    return _make_result("kcelectra", true_labels, pred_labels)


def _make_result(model_name: str, true: list, pred: list) -> dict:
    macro_f1  = f1_score(true, pred, labels=LABELS, average="macro",  zero_division=0)
    macro_pre = precision_score(true, pred, labels=LABELS, average="macro", zero_division=0)
    macro_rec = recall_score(true, pred, labels=LABELS, average="macro", zero_division=0)

    report = classification_report(
        true, pred, labels=LABELS, output_dict=True, zero_division=0
    )
    cm = confusion_matrix(true, pred, labels=LABELS)

    print(f"\n{'='*50}")
    print(f"[{model_name}] 분류 리포트")
    print(classification_report(true, pred, labels=LABELS, zero_division=0))
    print(f"[{model_name}] Macro F1={macro_f1:.4f}  Pre={macro_pre:.4f}  Rec={macro_rec:.4f}")
    print(f"[{model_name}] Confusion Matrix:\n{cm}")

    return {
        "model":          model_name,
        "macro_f1":       round(macro_f1, 4),
        "macro_precision":round(macro_pre, 4),
        "macro_recall":   round(macro_rec, 4),
        "per_class":      {
            label: {
                "precision": round(report[label]["precision"], 4),
                "recall":    round(report[label]["recall"], 4),
                "f1":        round(report[label]["f1-score"], 4),
                "support":   report[label]["support"],
            }
            for label in LABELS if label in report
        },
        "confusion_matrix": cm.tolist(),
        "labels":           LABELS,
    }


def save_and_compare(simple_res: dict, kcelectra_res: dict) -> None:
    with open(OUT_DIR / "eval_results_simple.json", "w", encoding="utf-8") as f:
        json.dump(simple_res, f, ensure_ascii=False, indent=2)

    if kcelectra_res:
        with open(OUT_DIR / "eval_results_kcelectra.json", "w", encoding="utf-8") as f:
            json.dump(kcelectra_res, f, ensure_ascii=False, indent=2)

    rows = []
    for res in [simple_res, kcelectra_res]:
        if not res:
            continue
        row = {
            "model":          res["model"],
            "macro_f1":       res["macro_f1"],
            "macro_precision":res["macro_precision"],
            "macro_recall":   res["macro_recall"],
        }
        for label in LABELS:
            if label in res.get("per_class", {}):
                row[f"{label}_f1"] = res["per_class"][label]["f1"]
        rows.append(row)

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(OUT_DIR / "eval_comparison_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n[compare] 결과 저장 완료 → {OUT_DIR}")
    print("\n── 성능 요약 ──")
    print(summary_df[["model", "macro_f1", "macro_precision", "macro_recall"]].to_string(index=False))

    if kcelectra_res:
        delta = kcelectra_res["macro_f1"] - simple_res["macro_f1"]
        print(f"\n KcELECTRA vs Simple  ΔMacro F1 = {delta:+.4f}")
        if delta >= 0.05:
            print("  → KcELECTRA 5%+ 향상: 채택 권장!")
        else:
            print("  → 5% 미만 향상: Simple 유지 고려")


def main(split: str = "test") -> None:
    print(f"[compare] 평가 split: {split}")

    simple_res     = evaluate_simple(split)
    kcelectra_res  = evaluate_kcelectra(split)

    save_and_compare(simple_res, kcelectra_res)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="test", choices=["train", "val", "test", "all"])
    args = parser.parse_args()
    main(split=args.split)
