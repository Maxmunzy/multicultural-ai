"""
evaluate_compare_ensemble_20260505.py
======================================
담당: 경이 (kyeongyi)
작성일: 2026-05-05

목적:
    Simple + KcELECTRA 소프트 투표 앙상블 평가.
    KcELECTRA 단독(v3, Macro F1 0.8545)이 목표 +5%에 0.71%p 미달하여
    devlog 우선순위 3에 따라 앙상블 시도.

    [비교 모델]
      1. Simple   : TF-IDF + Logistic Regression  (baseline 0.8116)
      2. KcELECTRA: v3 파인튜닝 단독              (0.8545)
      3. Ensemble : KcELECTRA×0.7 + Simple×0.3   (목표: 0.8616+)

    [앙상블 방식]
      소프트 투표(Soft Voting) — 두 모델의 확률을 가중 합산 후 argmax
      combined[i] = weight_kc × kc_prob[i] + (1-weight_kc) × s_prob[i]

    [출력 파일 - data/20260505/]
      eval_results_ensemble_20260505.json
      eval_comparison_summary_ensemble_20260505.csv

실행:
    cd model/classification
    python scripts/evaluate_compare_ensemble_20260505.py
    python scripts/evaluate_compare_ensemble_20260505.py --weight_kc 0.6
    python scripts/evaluate_compare_ensemble_20260505.py --search_weights
"""

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline

_BASE = Path(__file__).parent.parent
sys.path.insert(0, str(_BASE / "src"))

SPLIT_CSV      = _BASE / "data" / "split_v5_20260505.csv"
SIMPLE_PKL     = _BASE / "checkpoints" / "simple_tfidf_logreg_v3_20260505.pkl"
KCELECTRA_CKPT = _BASE / "checkpoints" / "kcelectra-category-v3"
OUT_DIR        = _BASE / "data" / "20260505"

# HF Hub fallback (로컬 체크포인트 없을 때)
_HF_REPO      = "kysophia/kcelectra-category"
_HF_SUBFOLDER = "kcelectra-category-v3"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]
_LABEL_TO_COL = {lbl: i for i, lbl in enumerate(LABELS)}


# ──────────────────────────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────────────────────────
def load_split(split: str = "test") -> tuple[list[str], list[str]]:
    if not SPLIT_CSV.exists():
        raise FileNotFoundError(f"{SPLIT_CSV} 없음")
    df = pd.read_csv(SPLIT_CSV, encoding="utf-8-sig")
    df = df[df["split"] == split]
    df = df[df["category"].isin(LABELS)]
    return df["text"].tolist(), df["category"].tolist()


# ──────────────────────────────────────────────────────────────────
# Simple 확률 행렬 (N, 6)
# ──────────────────────────────────────────────────────────────────
def _load_simple() -> Pipeline:
    if not SIMPLE_PKL.exists():
        raise FileNotFoundError(
            f"{SIMPLE_PKL.name} 없음.\n"
            "  먼저 실행: python scripts/evaluate_compare_v3_20260505.py"
        )
    with open(SIMPLE_PKL, "rb") as f:
        return pickle.load(f)


def get_simple_proba(texts: list[str]) -> np.ndarray:
    """Simple predict_proba → LABELS 순서로 열 정렬한 (N, 6) 행렬."""
    pipe = _load_simple()
    raw = pipe.predict_proba(texts)          # (N, K), pipe.classes_ 순서
    classes = list(pipe.classes_)
    out = np.zeros((len(texts), len(LABELS)))
    for j, lbl in enumerate(LABELS):
        if lbl in classes:
            out[:, j] = raw[:, classes.index(lbl)]
    return out


# ──────────────────────────────────────────────────────────────────
# KcELECTRA 확률 행렬 (N, 6)
# ──────────────────────────────────────────────────────────────────
def _load_kcelectra_model():
    """(device, tokenizer, model, id2label) 반환. 로컬 우선, HF Hub fallback."""
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError:
        raise ImportError("pip install torch transformers")

    device = "cuda" if torch.cuda.is_available() else "cpu"

    local_ready = (
        KCELECTRA_CKPT.exists()
        and (KCELECTRA_CKPT / "config.json").exists()
        and any(
            (KCELECTRA_CKPT / f).exists()
            for f in ("pytorch_model.bin", "model.safetensors")
        )
    )

    if local_ready:
        tokenizer = AutoTokenizer.from_pretrained(str(KCELECTRA_CKPT))
        model = AutoModelForSequenceClassification.from_pretrained(
            str(KCELECTRA_CKPT), num_labels=len(LABELS), ignore_mismatched_sizes=True
        )
        src = str(KCELECTRA_CKPT)
    else:
        print(f"[kcelectra] 로컬 없음 → HF Hub 다운로드: {_HF_REPO}/{_HF_SUBFOLDER}")
        tokenizer = AutoTokenizer.from_pretrained(_HF_REPO, subfolder=_HF_SUBFOLDER)
        model = AutoModelForSequenceClassification.from_pretrained(
            _HF_REPO, subfolder=_HF_SUBFOLDER, num_labels=len(LABELS)
        )
        src = f"{_HF_REPO}/{_HF_SUBFOLDER}"

    model.to(device).eval()
    print(f"[kcelectra] 모델 로드: {src} → device={device}")

    labels_file = KCELECTRA_CKPT / "label2id.json"
    if local_ready and labels_file.exists():
        with open(labels_file, encoding="utf-8") as f:
            label2id: dict[str, int] = json.load(f)
        id2label = {v: k for k, v in label2id.items()}
    else:
        id2label = {i: lbl for i, lbl in enumerate(LABELS)}

    return device, tokenizer, model, id2label


def get_kcelectra_proba(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """KcELECTRA softmax → LABELS 순서로 열 정렬한 (N, 6) 행렬. 배치 처리."""
    import torch

    device, tokenizer, model, id2label = _load_kcelectra_model()
    out = np.zeros((len(texts), len(LABELS)))

    with torch.no_grad():
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            enc = tokenizer(
                batch,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=128,
            ).to(device)
            probs = torch.softmax(model(**enc).logits, dim=-1).cpu().numpy()
            for b_i, prob_row in enumerate(probs):
                for k_i, p in enumerate(prob_row):
                    lbl = id2label.get(k_i, "기타")
                    col = _LABEL_TO_COL.get(lbl, _LABEL_TO_COL["기타"])
                    out[start + b_i, col] = p

    return out


# ──────────────────────────────────────────────────────────────────
# 앙상블 평가
# ──────────────────────────────────────────────────────────────────
def evaluate_ensemble(
    split: str,
    weight_kc: float,
    s_proba: np.ndarray,
    kc_proba: np.ndarray,
    true_labels: list[str],
) -> dict:
    """소프트 투표. s_proba / kc_proba를 받아 가중 합산 → 분류 리포트 반환."""
    combined = weight_kc * kc_proba + (1.0 - weight_kc) * s_proba
    pred_idx = combined.argmax(axis=1)
    pred_labels = [LABELS[i] for i in pred_idx]

    report = classification_report(
        true_labels, pred_labels,
        labels=LABELS, output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)

    return {
        "model":            "ensemble",
        "version":          f"kc{weight_kc:.1f}+s{1-weight_kc:.1f}",
        "weight_kc":        weight_kc,
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
        "data_version":     "v5_20260505",
    }


# ──────────────────────────────────────────────────────────────────
# val 세트 가중치 그리드 탐색
# ──────────────────────────────────────────────────────────────────
def search_best_weight() -> float:
    """val 세트에서 weight_kc 0.4~0.9 탐색 → 최적 weight 반환."""
    print("\n[weight 탐색] val 세트 기준 KcELECTRA 가중치 최적화")

    val_texts, val_labels = load_split("val")
    print(f"  val {len(val_texts)}건 확률 계산 중...")
    val_s  = get_simple_proba(val_texts)
    val_kc = get_kcelectra_proba(val_texts)

    print(f"\n  {'weight_kc':>10s}  {'val Macro F1':>14s}")
    print("  " + "-" * 28)

    best_w, best_f1 = 0.7, 0.0
    for w in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        res = evaluate_ensemble("val", w, val_s, val_kc, val_labels)
        mark = " ← best" if res["macro_f1"] > best_f1 else ""
        print(f"  {w:>10.1f}  {res['macro_f1']:>14.4f}{mark}")
        if res["macro_f1"] > best_f1:
            best_f1, best_w = res["macro_f1"], w

    print(f"\n  최적 weight_kc = {best_w}  (val Macro F1 = {best_f1:.4f})")
    return best_w


# ──────────────────────────────────────────────────────────────────
# 저장 + 비교 출력
# ──────────────────────────────────────────────────────────────────
def _summary_row(res: dict) -> dict:
    row = {
        "macro_f1":        res.get("macro_f1", "-"),
        "macro_precision": res.get("macro_precision", "-"),
        "macro_recall":    res.get("macro_recall", "-"),
    }
    for lbl in LABELS:
        row[f"f1_{lbl}"] = res.get("per_class", {}).get(lbl, {}).get("f1", "-")
    return row


def _build_result_from_proba(
    proba: np.ndarray,
    true_labels: list[str],
    model_name: str,
    split: str,
) -> dict:
    """확률 행렬 → 분류 리포트 dict (JSON 없을 때 fallback)."""
    pred_labels = [LABELS[i] for i in proba.argmax(axis=1)]
    report = classification_report(true_labels, pred_labels,
                                   labels=LABELS, output_dict=True, zero_division=0)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)
    cm = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    return {
        "model":            model_name,
        "version":          "v3",
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
        "data_version":     "v5_20260505",
    }


def save_and_compare(simple_res: dict, kc_res: dict, ens_res: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ens_path = OUT_DIR / "eval_results_ensemble_20260505.json"
    with open(ens_path, "w", encoding="utf-8") as f:
        json.dump(ens_res, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {ens_path.name}")

    label_e = f"Ensemble(kc{ens_res['weight_kc']:.1f}+s{1-ens_res['weight_kc']:.1f})"
    rows = [
        {"model": "Simple (TF-IDF+LR)",      **_summary_row(simple_res)},
        {"model": "KcELECTRA v3 (단독)",      **_summary_row(kc_res)},
        {"model": label_e,                    **_summary_row(ens_res)},
    ]
    summary_path = OUT_DIR / "eval_comparison_summary_ensemble_20260505.csv"
    pd.DataFrame(rows).to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"[저장] {summary_path.name}")

    s_f1  = simple_res["macro_f1"]
    kc_f1 = kc_res["macro_f1"]
    e_f1  = ens_res["macro_f1"]

    print("\n" + "=" * 60)
    print("  앙상블 성능 비교 (v5 데이터 - 4992행)")
    print("=" * 60)
    print(f"  Simple      Macro F1 : {s_f1:.4f}  (baseline)")
    print(f"  KcELECTRA   Macro F1 : {kc_f1:.4f}  (Delta vs Simple: {kc_f1-s_f1:+.4f})")
    print(f"  Ensemble    Macro F1 : {e_f1:.4f}  (Delta vs Simple: {e_f1-s_f1:+.4f})")
    print()

    delta = e_f1 - s_f1
    if delta >= 0.05:
        print("  ★ 앙상블 5%+ 향상 달성! 채택 확정")
    elif delta > 0:
        print(f"  ~ 앙상블 소폭 향상 ({delta:+.4f}) — --search_weights 또는 추가 튜닝 권장")
    else:
        print("  ✗ 앙상블이 Simple 미달 — weight_kc 조정 필요")

    print("\n  [카테고리별 F1 비교]")
    print(f"  {'카테고리':10s} {'Simple':>8s} {'KcELEC':>8s} {'Ensemble':>10s}")
    print("  " + "-" * 42)
    for lbl in LABELS:
        s = simple_res["per_class"].get(lbl, {}).get("f1", 0.0)
        k = kc_res["per_class"].get(lbl, {}).get("f1", 0.0)
        e = ens_res["per_class"].get(lbl, {}).get("f1", 0.0)
        best = " ★" if e > max(s, k) else ("  " if e >= max(s, k) else "  ")
        print(f"  {lbl:10s} {s:>8.4f} {k:>8.4f} {e:>10.4f}{best}")

    print(f"\n[출력 폴더] {OUT_DIR}")


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="KcELECTRA + Simple 소프트 투표 앙상블 평가"
    )
    parser.add_argument("--split", default="test",
                        choices=["train", "val", "test"])
    parser.add_argument("--weight_kc", type=float, default=0.7,
                        help="KcELECTRA 가중치 (0.0~1.0). 기본값 0.7")
    parser.add_argument("--search_weights", action="store_true",
                        help="val 세트에서 0.4~0.9 그리드 탐색 후 최적값으로 test 평가")
    args = parser.parse_args()

    print(f"앙상블 평가 시작 — split: {args.split}, weight_kc: {args.weight_kc}")

    # ① val 세트 가중치 탐색 (--search_weights)
    weight_kc = args.weight_kc
    if args.search_weights:
        weight_kc = search_best_weight()
        print(f"\n[test 평가] 최적 weight_kc={weight_kc} 적용")

    # ② test 확률 행렬
    texts, true_labels = load_split(args.split)
    print(f"\n[데이터] {args.split} 세트 {len(texts)}건")

    print("\n[Simple] 확률 행렬 계산 중...")
    s_proba = get_simple_proba(texts)

    print("[KcELECTRA] 확률 행렬 계산 중... (CPU면 수 분 소요)")
    kc_proba = get_kcelectra_proba(texts)

    # ③ 앙상블 평가
    ens_res = evaluate_ensemble(args.split, weight_kc, s_proba, kc_proba, true_labels)

    # ④ 단독 결과 — 기존 JSON 재활용, 없으면 확률 행렬에서 직접 계산
    simple_json = OUT_DIR / "eval_results_simple_v3_20260505.json"
    kc_json     = OUT_DIR / "eval_results_kcelectra_v3_20260505.json"

    if simple_json.exists():
        with open(simple_json, encoding="utf-8") as f:
            simple_res = json.load(f)
        print(f"[simple] 기존 JSON 재활용: {simple_json.name}")
    else:
        simple_res = _build_result_from_proba(s_proba, true_labels, "simple", args.split)

    if kc_json.exists():
        with open(kc_json, encoding="utf-8") as f:
            kc_res = json.load(f)
        print(f"[kcelectra] 기존 JSON 재활용: {kc_json.name}")
    else:
        kc_res = _build_result_from_proba(kc_proba, true_labels, "kcelectra", args.split)

    # ⑤ 저장 + 비교 출력
    print("\n[앙상블] 분류 리포트")
    pred_labels = [LABELS[i] for i in (weight_kc * kc_proba + (1 - weight_kc) * s_proba).argmax(axis=1)]
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))

    save_and_compare(simple_res, kc_res, ens_res)


if __name__ == "__main__":
    main()
