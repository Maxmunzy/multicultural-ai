"""분류·중요도 평가 도구. sklearn 없이 numpy로 모든 지표를 계산.

지표
----
- accuracy
- macro F1, weighted F1
- per-class precision/recall/F1
- confusion matrix (markdown 표로 저장)
- importance MAE, RMSE, Spearman 상관

CLI:
    python -m src.evaluate
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .config import LABELS, REPORT_DIR


def confusion_matrix(y_true: list[str], y_pred: list[str]) -> np.ndarray:
    n = len(LABELS)
    idx = {l: i for i, l in enumerate(LABELS)}
    cm = np.zeros((n, n), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        if t in idx and p in idx:
            cm[idx[t], idx[p]] += 1
    return cm


def classification_report(y_true: list[str], y_pred: list[str]) -> dict:
    """numpy로 직접 계산한 분류 리포트."""
    cm = confusion_matrix(y_true, y_pred)
    tp = np.diag(cm).astype(np.float64)
    fp = cm.sum(axis=0) - tp
    fn = cm.sum(axis=1) - tp
    support = cm.sum(axis=1)

    precision = np.divide(tp, tp + fp, out=np.zeros_like(tp), where=(tp + fp) > 0)
    recall = np.divide(tp, tp + fn, out=np.zeros_like(tp), where=(tp + fn) > 0)
    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros_like(tp),
        where=(precision + recall) > 0,
    )

    accuracy = float(tp.sum() / cm.sum()) if cm.sum() else 0.0
    macro_f1 = float(f1.mean())
    weighted_f1 = float(np.average(f1, weights=support)) if support.sum() else 0.0

    report = {
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_class": {
            LABELS[i]: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
            for i in range(len(LABELS))
        },
        "confusion_matrix": cm.tolist(),
    }
    return report


def importance_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """importance 회귀 평가."""
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mae = float(np.mean(np.abs(y_pred - y_true)))
    rmse = float(np.sqrt(np.mean((y_pred - y_true) ** 2)))
    # Spearman = Pearson on ranks
    rt = pd.Series(y_true).rank().values
    rp = pd.Series(y_pred).rank().values
    if rt.std() == 0 or rp.std() == 0:
        spearman = 0.0
    else:
        spearman = float(np.corrcoef(rt, rp)[0, 1])
    # 경이님 임무에 가장 의미있는 지표: "importance 0.85 이상 = 액션 필요" 분류 정확도
    high_true = (y_true >= 0.85).astype(int)
    high_pred = (y_pred >= 0.85).astype(int)
    tp = int(((high_true == 1) & (high_pred == 1)).sum())
    fp = int(((high_true == 0) & (high_pred == 1)).sum())
    fn = int(((high_true == 1) & (high_pred == 0)).sum())
    prec = tp / (tp + fp) if tp + fp > 0 else 0.0
    rec = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec > 0 else 0.0
    return {
        "MAE": mae,
        "RMSE": rmse,
        "Spearman": spearman,
        "high_importance_threshold": 0.85,
        "high_importance_precision": float(prec),
        "high_importance_recall": float(rec),
        "high_importance_f1": float(f1),
    }


def render_markdown_report(
    title: str,
    cls_report: dict,
    imp_report: dict | None,
    *,
    extra_note: str = "",
) -> str:
    cm = cls_report["confusion_matrix"]
    md = []
    md.append(f"# {title}\n")
    if extra_note:
        md.append(f"_{extra_note}_\n")
    md.append("## 분류 지표\n")
    md.append(f"- accuracy: **{cls_report['accuracy']:.4f}**")
    md.append(f"- macro F1: **{cls_report['macro_f1']:.4f}**")
    md.append(f"- weighted F1: **{cls_report['weighted_f1']:.4f}**\n")

    md.append("### 카테고리별\n")
    md.append("| 카테고리 | precision | recall | f1 | support |")
    md.append("| --- | ---: | ---: | ---: | ---: |")
    for label, m in cls_report["per_class"].items():
        md.append(
            f"| {label} | {m['precision']:.3f} | {m['recall']:.3f} | "
            f"{m['f1']:.3f} | {m['support']} |"
        )
    md.append("")

    md.append("### 혼동 행렬 (행=정답, 열=예측)\n")
    header = "| true \\ pred | " + " | ".join(LABELS) + " |"
    sep = "| --- | " + " | ".join(["---"] * len(LABELS)) + " |"
    md.append(header)
    md.append(sep)
    for i, row in enumerate(cm):
        md.append(f"| {LABELS[i]} | " + " | ".join(str(v) for v in row) + " |")
    md.append("")

    if imp_report:
        md.append("## 중요도 회귀 지표\n")
        md.append(f"- MAE: **{imp_report['MAE']:.4f}**")
        md.append(f"- RMSE: **{imp_report['RMSE']:.4f}**")
        md.append(f"- Spearman: **{imp_report['Spearman']:.4f}**")
        md.append(
            f"- 고중요(≥0.85) precision: {imp_report['high_importance_precision']:.3f} / "
            f"recall: {imp_report['high_importance_recall']:.3f} / "
            f"F1: {imp_report['high_importance_f1']:.3f}"
        )
    return "\n".join(md)


# ------------------------------------------------------------------------------
# 평가 러너
# ------------------------------------------------------------------------------
def evaluate_pipeline(
    classifier,
    importance_scorer,
    df: pd.DataFrame,
    *,
    name: str = "model",
    save: bool = True,
) -> dict:
    texts = df["original_text"].tolist()
    y_true = df["category"].tolist()
    y_pred = classifier.predict(texts)
    cls_rep = classification_report(y_true, y_pred)

    imp_rep = None
    if importance_scorer is not None and "importance" in df.columns:
        imp_pred = importance_scorer.predict(texts, y_pred)  # 예측 카테고리로 (실전과 동일)
        imp_rep = importance_metrics(df["importance"].values, imp_pred)

    md = render_markdown_report(
        f"평가 결과 — {name}", cls_rep, imp_rep,
        extra_note="`importance_scorer.predict()`는 *분류 예측* 카테고리로 호출됨 (실 운영과 동일).",
    )

    if save:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"report_{name}.md").write_text(md, encoding="utf-8")
        (REPORT_DIR / f"report_{name}.json").write_text(
            json.dumps({"classification": cls_rep, "importance": imp_rep}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {"classification": cls_rep, "importance": imp_rep, "markdown": md}


if __name__ == "__main__":
    # 빠른 테스트
    from .data_loader import build_dataset
    from .classifier_simple import SimpleNoticeClassifier
    from .importance_scorer import ImportanceScorer

    split = build_dataset()
    clf = SimpleNoticeClassifier(epochs=300)
    clf.fit(split.train["original_text"].tolist(), split.train["category"].tolist())
    scorer = ImportanceScorer()
    scorer.fit(
        split.train["original_text"].tolist(),
        split.train["category"].tolist(),
        split.train["importance"].tolist(),
    )
    out = evaluate_pipeline(clf, scorer, split.test, name="simple_demo")
    print(out["markdown"])
