"""두 모델 galsan unseen 비교 평가 스크립트."""
import json
import sys
import torch
import numpy as np
from pathlib import Path
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from sklearn.metrics import (
    classification_report, f1_score,
    precision_score, recall_score, accuracy_score,
)

sys.stdout.reconfigure(encoding="utf-8")

TEST_FILE = Path("data/draft/unseen_test_galsan.jsonl")
MODELS = {
    "v3.1 Small": {"path": "checkpoints/koelectra-binary-v3.1", "default_thr": 0.55},
    "Base":       {"path": "checkpoints/koelectra-binary-base",  "default_thr": 0.40},
}
MAX_LEN = 128
BATCH   = 64
DEVICE  = "cuda" if torch.cuda.is_available() else "cpu"
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
rows   = [json.loads(l) for l in TEST_FILE.open(encoding="utf-8") if l.strip()]
texts  = [r["text"] for r in rows]
y_true = [int(bool(r.get("is_todo"))) for r in rows]
print(f"테스트셋(galsan unseen): {len(texts)}건  True={sum(y_true)}  False={len(y_true)-sum(y_true)}")
print(f"device: {DEVICE}\n")

# ── 추론 ─────────────────────────────────────────────────────────────────────
all_probs = {}
for name, cfg in MODELS.items():
    print(f"로딩: {name}  ({cfg['path']})")
    tok = AutoTokenizer.from_pretrained(cfg["path"])
    mdl = AutoModelForSequenceClassification.from_pretrained(cfg["path"], num_labels=2)
    mdl.to(DEVICE).eval()
    probs = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]
        enc = tok(batch, truncation=True, padding=True,
                  max_length=MAX_LEN, return_tensors="pt")
        enc = {k: v.to(DEVICE) for k, v in enc.items()}
        with torch.no_grad():
            logits = mdl(**enc).logits
        probs.extend(torch.softmax(logits, dim=-1)[:, 1].cpu().numpy())
    all_probs[name] = np.array(probs)
    print(f"  완료\n")

# ── 임계값 탐색 ───────────────────────────────────────────────────────────────
best_info = {}
for name, cfg in MODELS.items():
    probs   = all_probs[name]
    default = cfg["default_thr"]
    print(f"=== {name} — 임계값 탐색 ===")
    print(f"  {'Threshold':>10} {'F1':>8} {'Precision':>10} {'Recall':>8}")
    print("  " + "-" * 42)
    best_f1, best_thr = 0.0, default
    for thr in THRESHOLDS:
        preds = (probs >= thr).astype(int)
        f1  = f1_score(y_true, preds, pos_label=1, zero_division=0)
        pre = precision_score(y_true, preds, pos_label=1, zero_division=0)
        rec = recall_score(y_true, preds, pos_label=1, zero_division=0)
        tag = ""
        if thr == default:
            tag = " <- predict.py 현재값"
        if f1 > best_f1:
            best_f1, best_thr = f1, thr
            tag += " *best"
        print(f"  {thr:>10.2f} {f1:>8.4f} {pre:>10.4f} {rec:>8.4f}{tag}")
    best_info[name] = {"thr": best_thr, "f1": best_f1}
    print()

# ── 최종 리포트 ───────────────────────────────────────────────────────────────
SEP = "=" * 60
print(SEP)
print("최종 분류 리포트 (각 모델 galsan unseen 최적 임계값)")
print(SEP)
summary = {}
for name, bi in best_info.items():
    thr   = bi["thr"]
    preds = (all_probs[name] >= thr).astype(int)
    acc   = accuracy_score(y_true, preds)
    f1    = f1_score(y_true, preds, pos_label=1, zero_division=0)
    pre   = precision_score(y_true, preds, pos_label=1, zero_division=0)
    rec   = recall_score(y_true, preds, pos_label=1, zero_division=0)
    summary[name] = {"acc": acc, "f1": f1, "pre": pre, "rec": rec, "thr": thr}
    print(f"\n[{name}]  threshold={thr}")
    print(classification_report(
        y_true, preds,
        target_names=["노이즈", "할 일"],
        digits=4, zero_division=0,
    ))
    print(f"  Accuracy: {acc:.4f}")

# ── 최종 비교 요약 ────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("최종 요약 비교")
print(SEP)
print(f"{'모델':<12} {'Threshold':>10} {'Accuracy':>10} {'F1':>8} {'Precision':>10} {'Recall':>8}")
print("-" * 62)
for name, s in summary.items():
    print(f"{name:<12} {s['thr']:>10.2f} {s['acc']:>10.4f} {s['f1']:>8.4f} {s['pre']:>10.4f} {s['rec']:>8.4f}")

a, b = list(summary.values())
print("\n변화 (Base - Small):")
print(f"  Accuracy  : {b['acc']-a['acc']:+.4f}")
print(f"  F1        : {b['f1'] -a['f1'] :+.4f}")
print(f"  Precision : {b['pre']-a['pre']:+.4f}")
print(f"  Recall    : {b['rec']-a['rec']:+.4f}")
