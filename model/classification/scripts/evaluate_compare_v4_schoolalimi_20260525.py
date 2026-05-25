"""
evaluate_compare_v4_schoolalimi_20260525.py
============================================
담당: 경이 (kyeongyi)
작성일: 2026-05-25

목적:
    KcELECTRA v4 (학교알리미 공공데이터 증강) vs v3_2 성능 비교
    - 동일 test 세트(split_v4_schoolalimi_20260525.csv test, 1593행)로 공정 비교
    - 증강 데이터 효과 측정: 건강·안전 / 일정 / 비용 카테고리 중점 분석

    [비교 모델]
      1. Simple   : TF-IDF + LogReg (v4 train 데이터로 재학습)
      2. KcELECTRA v3_2: 기존 baseline  (Macro F1 = 0.8374)
      3. KcELECTRA v4  : 학교알리미 증강 (14_train_kcelectra_v4_schoolalimi_20260525.ipynb)

    [증강 데이터 요약]
      건강·안전: +152개 (1718→1870)
      일정      : +237개 (1552→1789)
      비용      : +62개  (677→739)
      총 추가   : 564행 (train+val에만, test 불변)

    [출력 파일 - data/20260525/]
      eval_results_simple_v4_20260525.json
      eval_results_kcelectra_v4_20260525.json   ← Colab 결과 자동 활용
      eval_comparison_summary_v4_20260525.csv
      compare_macro_f1_v3v4_20260525.png
      compare_percat_f1_v3v4_20260525.png
      compare_confusion_v3v4_20260525.png
      version_trend_20260525.png

실행:
    cd model/classification
    python scripts/evaluate_compare_v4_schoolalimi_20260525.py
    python scripts/evaluate_compare_v4_schoolalimi_20260525.py --split val
    python scripts/evaluate_compare_v4_schoolalimi_20260525.py --no-chart  # 차트 생략
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

_BASE   = Path(__file__).parent.parent
sys.path.insert(0, str(_BASE / "src"))

# ── 경로 ─────────────────────────────────────────────────────────────────
SPLIT_V4_CSV   = _BASE / "data" / "split_v4_schoolalimi_20260525.csv"
SIMPLE_PKL     = _BASE / "checkpoints" / "simple_tfidf_logreg_v4_20260525.pkl"
KCELECTRA_CKPT = _BASE / "checkpoints" / "kcelectra-category-v4"
OUT_DIR        = _BASE / "data" / "20260525"
V3_JSON        = _BASE / "data" / "20260509" / "eval_results_kcelectra_v3_2_20260509.json"
TS             = "v4_20260525"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]

# ── 기존 버전 Macro F1 (version_trend 차트용) ────────────────────────────
VERSION_HISTORY = {
    "v2_2\n(20260503)": 0.8076,
    "v3\n(20260505)":   0.8545,
    "v3_2\n(20260509)": 0.8374,
}


# -----------------------------------------------------------------------
# 데이터 로드 (v4 CSV 기준)
# -----------------------------------------------------------------------
def load_split(split: str = "test") -> tuple[list[str], list[str]]:
    if not SPLIT_V4_CSV.exists():
        raise FileNotFoundError(
            f"{SPLIT_V4_CSV} 없음 - merge_split_v4_schoolalimi_20260525.py 먼저 실행하세요."
        )
    df = pd.read_csv(SPLIT_V4_CSV, encoding="utf-8-sig")
    df = df[df["split"] == split]
    df = df[df["category"].isin(LABELS)]
    return df["text"].tolist(), df["category"].tolist()


# -----------------------------------------------------------------------
# Simple 모델 (TF-IDF + LogReg)
# -----------------------------------------------------------------------
def train_simple() -> Pipeline:
    texts, labels = load_split("train")
    print(f"[simple] v4 train 데이터: {len(texts)}개 (증강 포함)")

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


def _load_simple(retrain: bool = False) -> Pipeline:
    if not retrain and SIMPLE_PKL.exists():
        with open(SIMPLE_PKL, "rb") as f:
            return pickle.load(f)
    return train_simple()


def evaluate_simple(split: str = "test", retrain: bool = False) -> dict:
    texts, true_labels = load_split(split)
    pipe = _load_simple(retrain)
    pred_labels = pipe.predict(texts)

    report   = classification_report(
        true_labels, pred_labels,
        labels=LABELS, output_dict=True, zero_division=0,
    )
    cm       = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)

    print("\n[Simple - TF-IDF + LogReg v4] 분류 리포트")
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))

    train_texts, _ = load_split("train")
    return {
        "model":           "simple",
        "version":         "v4",
        "macro_f1":        round(macro_f1, 4),
        "macro_precision": round(report["macro avg"]["precision"], 4),
        "macro_recall":    round(report["macro avg"]["recall"], 4),
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
        "data_version":     "v4_schoolalimi_20260525",
        "train_size":       len(train_texts),
        "test_size":        len(texts),
    }


# -----------------------------------------------------------------------
# KcELECTRA v4 (beomi/kcelectra-base 파인튜닝, 증강 데이터 포함)
# -----------------------------------------------------------------------
def _kcelectra_ready() -> bool:
    try:
        import torch          # noqa: F401
        from transformers import AutoTokenizer  # noqa: F401
    except ImportError:
        print("[kcelectra] torch/transformers 미설치 - JSON 재활용 모드로 전환")
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


def evaluate_kcelectra_v4(split: str = "test") -> dict:
    """
    KcELECTRA v4 평가.
    Colab 학습 후 eval_results_kcelectra_v4_20260525.json이 있으면 재활용.
    checkpoints/kcelectra-category-v4/ 가 있으면 직접 추론.
    """
    json_path = OUT_DIR / f"eval_results_kcelectra_{TS}.json"

    if json_path.exists():
        print(f"[kcelectra v4] 기존 JSON 재활용: {json_path.name}")
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)

    if not _kcelectra_ready():
        print(f"\n[kcelectra v4] 체크포인트 없음: {KCELECTRA_CKPT}")
        print("  14_train_kcelectra_v4_schoolalimi_20260525.ipynb (Colab) 실행 후")
        print("  kcelectra-category-v4/ 를 checkpoints/ 에 배치하거나")
        print("  eval_results_kcelectra_v4_20260525.json 을 data/20260525/ 에 배치하세요.")
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
    BATCH = 32
    with torch.no_grad():
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            enc   = tokenizer(
                batch, return_tensors="pt",
                truncation=True, padding=True, max_length=128,
            ).to(device)
            logits = model(**enc).logits
            idxs   = logits.argmax(dim=-1).tolist()
            pred_labels.extend([id2label.get(idx, "기타") for idx in idxs])

    report   = classification_report(
        true_labels, pred_labels,
        labels=LABELS, output_dict=True, zero_division=0,
    )
    cm       = confusion_matrix(true_labels, pred_labels, labels=LABELS)
    macro_f1 = f1_score(true_labels, pred_labels, labels=LABELS,
                        average="macro", zero_division=0)

    print("\n[KcELECTRA v4 — beomi/kcelectra-base + 학교알리미 증강] 분류 리포트")
    print(classification_report(true_labels, pred_labels, labels=LABELS, zero_division=0))

    result = {
        "model":           "kcelectra",
        "version":         "v4",
        "base_model":      "beomi/kcelectra-base",
        "macro_f1":        round(macro_f1, 4),
        "macro_precision": round(report["macro avg"]["precision"], 4),
        "macro_recall":    round(report["macro avg"]["recall"], 4),
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
        "data_version":     "v4_schoolalimi_20260525",
        "augment_source":   "학교알리미_공공데이터",
        "augment_added":    {"건강·안전": 152, "일정": 237, "비용": 62},
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[저장] {json_path.name}")
    return result


# -----------------------------------------------------------------------
# 차트 생성
# -----------------------------------------------------------------------
def _load_v3_results() -> dict:
    if V3_JSON.exists():
        with open(V3_JSON, encoding="utf-8") as f:
            return json.load(f)
    return {"macro_f1": 0.8374, "per_class": {
        "일정":    {"f1": 0.8665}, "준비물": {"f1": 0.8736},
        "제출":    {"f1": 0.8233}, "비용":   {"f1": 0.8095},
        "건강·안전": {"f1": 0.8034}, "기타":  {"f1": 0.8479},
    }, "confusion_matrix": [
        [159,0,10,1,2,22],[1,38,0,0,1,4],[3,0,254,4,1,54],
        [0,1,4,68,1,10],[0,0,5,0,188,21],[10,4,28,11,61,627],
    ], "labels": LABELS}


def _make_charts(simple_res: dict, v4_res: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        import numpy as np
    except ImportError:
        print("[차트] matplotlib/numpy 미설치 - 차트 생략")
        return

    # 한글 폰트
    font_path = None
    for candidate in ["NanumGothic", "Malgun Gothic", "AppleGothic", "DejaVu Sans"]:
        try:
            fp = fm.findfont(fm.FontProperties(family=candidate))
            if fp and "DejaVu" not in fp:
                font_path = fp
                break
        except Exception:
            pass
    if font_path:
        plt.rcParams["font.family"] = fm.FontProperties(fname=font_path).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    v3_res = _load_v3_results()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1) Macro F1 비교 바 차트 (v3_2 vs v4) ───────────────────────────
    fig, ax = plt.subplots(figsize=(7, 4))
    models  = ["KcELECTRA v3_2\n(baseline)", "Simple v4\n(TF-IDF+LR)", "KcELECTRA v4\n(학교알리미 증강)"]
    f1s     = [
        v3_res.get("macro_f1", 0.8374),
        simple_res.get("macro_f1", 0),
        v4_res.get("macro_f1", 0),
    ]
    colors  = ["#90A4AE", "#78909C", "#1565C0"]
    bars    = ax.bar(models, f1s, color=colors, width=0.5, edgecolor="white", linewidth=1.2)
    ax.set_ylim(0.70, 1.00)
    ax.set_ylabel("Macro F1", fontsize=11)
    ax.set_title("KcELECTRA v3_2 vs v4 — Macro F1 비교\n(학교알리미 공공데이터 증강 효과)", fontsize=12)
    ax.axhline(y=v3_res.get("macro_f1", 0.8374), color="#B71C1C", linestyle="--",
               linewidth=1.2, alpha=0.8, label=f"v3_2 baseline ({v3_res.get('macro_f1',0.8374):.4f})")
    ax.legend(fontsize=9)
    for bar, val in zip(bars, f1s):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, val + 0.003,
                    f"{val:.4f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    fig.tight_layout()
    out_path = OUT_DIR / "compare_macro_f1_v3v4_20260525.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[차트] {out_path.name}")

    # ── 2) 카테고리별 F1 비교 ────────────────────────────────────────────
    if v4_res:
        fig, ax = plt.subplots(figsize=(10, 5))
        x      = np.arange(len(LABELS))
        width  = 0.28
        v3_f1s = [v3_res["per_class"].get(l, {}).get("f1", 0) for l in LABELS]
        v4_f1s = [v4_res["per_class"].get(l, {}).get("f1", 0) for l in LABELS]
        sm_f1s = [simple_res["per_class"].get(l, {}).get("f1", 0) for l in LABELS]

        ax.bar(x - width, v3_f1s, width, label="KcELECTRA v3_2 (baseline)",
               color="#90A4AE", edgecolor="white")
        ax.bar(x,          sm_f1s, width, label="Simple v4 (TF-IDF+LR)",
               color="#B0BEC5", edgecolor="white")
        ax.bar(x + width,  v4_f1s, width, label="KcELECTRA v4 (학교알리미 증강)",
               color="#1565C0", edgecolor="white")

        ax.set_xticks(x)
        ax.set_xticklabels(LABELS, fontsize=11)
        ax.set_ylim(0.60, 1.05)
        ax.set_ylabel("F1 Score", fontsize=11)
        ax.set_title("카테고리별 F1 비교: v3_2 vs v4 (학교알리미 증강)", fontsize=12)
        ax.legend(fontsize=9)
        ax.axhline(y=0.90, color="gray", linestyle=":", alpha=0.5)

        # 증강 효과 표시: 건강·안전 / 일정 / 비용
        for lbl in ["건강·안전", "일정", "비용"]:
            idx    = LABELS.index(lbl)
            v3_val = v3_f1s[idx]
            v4_val = v4_f1s[idx]
            delta  = v4_val - v3_val
            if delta != 0:
                arrow = "+" if delta > 0 else ""
                ax.annotate(f"{arrow}{delta:.3f}",
                            xy=(idx + width, v4_val),
                            xytext=(idx + width, v4_val + 0.035),
                            ha="center", fontsize=8,
                            color="#1B5E20" if delta > 0 else "#B71C1C",
                            arrowprops=dict(arrowstyle="-", color="gray", lw=0.5))

        fig.tight_layout()
        out_path = OUT_DIR / "compare_percat_f1_v3v4_20260525.png"
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[차트] {out_path.name}")

    # ── 3) 혼동 행렬 나란히 비교 (v3_2 vs v4) ───────────────────────────
    if v4_res and v4_res.get("confusion_matrix"):
        import numpy as np

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        label_short = ["일정", "준비물", "제출", "비용", "건강\n안전", "기타"]

        for ax_i, (title, cm_data) in enumerate([
            (f"v3_2 (Macro F1={v3_res.get('macro_f1',0.8374):.4f})", v3_res.get("confusion_matrix", [])),
            (f"v4 (Macro F1={v4_res.get('macro_f1',0):.4f})\n[학교알리미 증강]", v4_res.get("confusion_matrix", [])),
        ]):
            if not cm_data:
                continue
            cm_arr = np.array(cm_data)
            im     = axes[ax_i].imshow(cm_arr, interpolation="nearest",
                                       cmap="Blues" if ax_i == 0 else "Greens")
            axes[ax_i].set_title(title, fontsize=11)
            axes[ax_i].set_xlabel("예측 레이블", fontsize=10)
            axes[ax_i].set_ylabel("실제 레이블", fontsize=10)
            axes[ax_i].set_xticks(range(len(LABELS)))
            axes[ax_i].set_yticks(range(len(LABELS)))
            axes[ax_i].set_xticklabels(label_short, fontsize=9)
            axes[ax_i].set_yticklabels(LABELS, fontsize=9)
            thresh = cm_arr.max() / 2.0
            for r in range(cm_arr.shape[0]):
                for c in range(cm_arr.shape[1]):
                    axes[ax_i].text(c, r, str(cm_arr[r, c]),
                                    ha="center", va="center", fontsize=7,
                                    color="white" if cm_arr[r, c] > thresh else "black")
            fig.colorbar(im, ax=axes[ax_i], fraction=0.046, pad=0.04)

        fig.suptitle("혼동 행렬 비교: KcELECTRA v3_2 vs v4\n(행=실제, 열=예측 / 강조: 기타↔건강·안전 경계)", fontsize=12)
        fig.tight_layout()
        out_path = OUT_DIR / "compare_confusion_v3v4_20260525.png"
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[차트] {out_path.name}")

    # ── 4) 버전 트렌드 ───────────────────────────────────────────────────
    trend_data = dict(VERSION_HISTORY)
    if v4_res:
        trend_data[f"v4\n(20260525)"] = v4_res.get("macro_f1", 0)

    fig, ax = plt.subplots(figsize=(8, 4))
    vers    = list(trend_data.keys())
    vals    = list(trend_data.values())
    colors  = ["#78909C"] * (len(vers) - 1) + (["#1565C0"] if v4_res else ["#78909C"])

    ax.plot(vers, vals, marker="o", color="#1565C0", linewidth=2, markersize=8)
    for i, (v, val) in enumerate(zip(vers, vals)):
        ax.text(i, val + 0.005, f"{val:.4f}", ha="center", va="bottom",
                fontsize=9, fontweight="bold",
                color="#1565C0" if i == len(vers) - 1 else "#455A64")

    ax.set_ylim(0.75, 0.95)
    ax.set_ylabel("Macro F1", fontsize=11)
    ax.set_title("KcELECTRA 버전별 Macro F1 추이\n(학교알리미 공공데이터 증강 효과 포함)", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    if v4_res:
        ax.axvspan(len(vers) - 1.5, len(vers) - 0.5,
                   alpha=0.08, color="#1565C0", label="학교알리미 증강 (v4)")
        ax.legend(fontsize=9)
    fig.tight_layout()
    out_path = OUT_DIR / "version_trend_20260525.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[차트] {out_path.name}")


# -----------------------------------------------------------------------
# 저장 + 비교 출력
# -----------------------------------------------------------------------
def save_and_compare(simple_res: dict, v4_res: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Simple JSON
    simple_path = OUT_DIR / f"eval_results_simple_{TS}.json"
    with open(simple_path, "w", encoding="utf-8") as f:
        json.dump(simple_res, f, ensure_ascii=False, indent=2)
    print(f"[저장] {simple_path.name}")

    # KcELECTRA v4 JSON (이미 evaluate_kcelectra_v4 내에서 저장됨, 없으면 재저장)
    if v4_res:
        v4_path = OUT_DIR / f"eval_results_kcelectra_{TS}.json"
        if not v4_path.exists():
            with open(v4_path, "w", encoding="utf-8") as f:
                json.dump(v4_res, f, ensure_ascii=False, indent=2)

    # Summary CSV
    v3_res = _load_v3_results()

    def _row(label, res):
        row = {"model": label,
               "macro_f1":        res.get("macro_f1", "-"),
               "macro_precision":  res.get("macro_precision", "-"),
               "macro_recall":     res.get("macro_recall", "-")}
        for lbl in LABELS:
            row[f"f1_{lbl}"] = res.get("per_class", {}).get(lbl, {}).get("f1", "-")
        return row

    rows = [
        _row("KcELECTRA v3_2 (baseline, beomi/kcelectra-base)", v3_res),
        _row("Simple v4 (TF-IDF + LogReg, 증강 데이터)", simple_res),
    ]
    if v4_res:
        rows.append(_row("KcELECTRA v4 (beomi/kcelectra-base + 학교알리미 증강)", v4_res))

    summary_df   = pd.DataFrame(rows)
    summary_path = OUT_DIR / f"eval_comparison_summary_{TS}.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"[저장] {summary_path.name}")

    # ── 콘솔 출력 ───────────────────────────────────────────────────────
    v3_f1 = v3_res.get("macro_f1", 0.8374)
    print("\n" + "=" * 70)
    print("  성능 비교 결과 — KcELECTRA v4 학교알리미 공공데이터 증강")
    print("  기준 모델: KcELECTRA v3_2 (beomi/kcelectra-base, Macro F1 = 0.8374)")
    print("=" * 70)
    print(f"  v3_2 baseline Macro F1 : {v3_f1:.4f}")
    print(f"  Simple v4    Macro F1  : {simple_res['macro_f1']:.4f}"
          f"  (v3_2 대비: {simple_res['macro_f1'] - v3_f1:+.4f})")

    if v4_res:
        v4_f1       = v4_res["macro_f1"]
        delta_v3    = v4_f1 - v3_f1
        delta_simple = v4_f1 - simple_res["macro_f1"]

        print(f"  KcELECTRA v4 Macro F1  : {v4_f1:.4f}")
        print(f"  v3_2 대비              : {delta_v3:+.4f}")
        print(f"  Simple v4 대비         : {delta_simple:+.4f}")
        print()

        if delta_v3 > 0:
            print(f"  => KcELECTRA v4가 v3_2 대비 {delta_v3:+.4f} 향상 -- 증강 효과 확인!")
        elif delta_v3 == 0:
            print("  => v3_2와 동일 (증강 효과 미미)")
        else:
            print(f"  => v3_2 대비 {delta_v3:.4f} 하락 -- 하이퍼파라미터/재학습 필요")

        # 목표 카테고리 분석
        print("\n  [증강 목표 카테고리 효과 분석]")
        print(f"  {'카테고리':10s} {'v3_2 F1':>10s} {'v4 F1':>10s} {'변화':>8s} {'주목'}")
        print("  " + "-" * 52)
        highlight = {"건강·안전", "일정", "비용"}
        for lbl in LABELS:
            v3_lf1 = v3_res["per_class"].get(lbl, {}).get("f1", 0)
            v4_lf1 = v4_res["per_class"].get(lbl, {}).get("f1", 0)
            delta  = v4_lf1 - v3_lf1
            mark   = ("↑ 증강 목표" if delta > 0.005 and lbl in highlight
                      else "↓" if delta < -0.005
                      else "~")
            print(f"  {lbl:10s} {v3_lf1:>10.4f} {v4_lf1:>10.4f} {delta:>+7.4f}  {mark}")

        # 기타↔건강·안전 경계 분석
        if v4_res.get("confusion_matrix") and v3_res.get("confusion_matrix"):
            cm_v3 = v4_res["confusion_matrix"]  # [건강·안전 row, 기타 col]
            v4_cm = v4_res["confusion_matrix"]
            v3_cm = v3_res["confusion_matrix"]
            lbl_idx = {l: i for i, l in enumerate(LABELS)}
            ha_idx  = lbl_idx.get("건강·안전", 4)
            gi_idx  = lbl_idx.get("기타", 5)

            v3_ha2gi = v3_cm[ha_idx][gi_idx] if v3_cm else "-"
            v3_gi2ha = v3_cm[gi_idx][ha_idx] if v3_cm else "-"
            v4_ha2gi = v4_cm[ha_idx][gi_idx] if v4_cm else "-"
            v4_gi2ha = v4_cm[gi_idx][ha_idx] if v4_cm else "-"

            print("\n  [기타 <-> 건강·안전 경계 오분류 변화]")
            print(f"  건강·안전 -> 기타:  v3_2={v3_ha2gi}건  ->  v4={v4_ha2gi}건")
            print(f"  기타 -> 건강·안전:  v3_2={v3_gi2ha}건  ->  v4={v4_gi2ha}건")
    else:
        print("\n  KcELECTRA v4: 평가 미완료")
        print("  14_train_kcelectra_v4_schoolalimi_20260525.ipynb (Colab) 실행 후")
        print("  eval_results_kcelectra_v4_20260525.json을 data/20260525/ 에 배치하세요.")

    print(f"\n[출력 폴더] {OUT_DIR}")


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split",    default="test", choices=["train", "val", "test"])
    parser.add_argument("--retrain",  action="store_true", help="Simple 모델 강제 재학습")
    parser.add_argument("--no-chart", action="store_true", help="차트 생성 스킵")
    args = parser.parse_args()

    print("=" * 70)
    print(" KcELECTRA v4 vs v3_2 성능 비교")
    print(" 증강: 학교알리미 공공데이터 (교육부, data.go.kr)")
    print(f" split: {args.split} | 데이터: v4_schoolalimi_20260525 (16512행)")
    print("=" * 70)

    if args.retrain and SIMPLE_PKL.exists():
        SIMPLE_PKL.unlink()
        print("[simple] 기존 PKL 삭제 -> 재학습\n")

    simple_res = evaluate_simple(args.split, retrain=args.retrain)
    v4_res     = evaluate_kcelectra_v4(args.split)

    save_and_compare(simple_res, v4_res)

    if not args.no_chart:
        _make_charts(simple_res, v4_res)


if __name__ == "__main__":
    main()
