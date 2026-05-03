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
from datetime import datetime
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


def _fill_per_class_from_cm(res: dict) -> dict:
    """Colab 저장 JSON에 per_class가 없을 때 confusion_matrix에서 보완."""
    if res.get("per_class"):
        return res
    cm = res.get("confusion_matrix")
    labels = res.get("labels", LABELS)
    if not cm:
        return res
    per_class = {}
    for i, label in enumerate(labels):
        tp = cm[i][i]
        fp = sum(cm[r][i] for r in range(len(cm))) - tp
        fn = sum(cm[i]) - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[label] = {
            "precision": round(precision, 4),
            "recall":    round(recall, 4),
            "f1":        round(f1, 4),
            "support":   sum(cm[i]),
        }
    res["per_class"] = per_class
    return res


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
            result = json.load(f)
        result = _fill_per_class_from_cm(result)
        # per_class 보완된 내용을 다시 저장
        with open(cached_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

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
    ts = datetime.now().strftime("%Y%m%d")

    def _write_json(data: dict, canonical: str) -> None:
        with open(OUT_DIR / canonical, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        stem = canonical.replace(".json", "")
        with open(OUT_DIR / f"{stem}_{ts}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    _write_json(simple_res, "eval_results_simple.json")
    if kcelectra_res:
        _write_json(kcelectra_res, "eval_results_kcelectra.json")

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
    summary_df.to_csv(OUT_DIR / f"eval_comparison_summary_{ts}.csv", index=False, encoding="utf-8-sig")
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
