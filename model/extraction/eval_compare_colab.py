"""
eval_compare_colab.py
=====================
base-v1 vs base(v4_merged) — galsan unseen 비교 평가 (Colab GPU용)

실행 전 확인:
  - 런타임 유형: T4 GPU
  - 테스트 파일: unseen_test_galsan.jsonl 업로드 필요
"""

# ── 패키지 설치 ───────────────────────────────────────────────────────────────
import subprocess
subprocess.run(["pip", "install", "transformers", "torch", "scikit-learn", "-q"], check=True)

# ── 테스트 데이터 업로드 ──────────────────────────────────────────────────────
from google.colab import files
print("unseen_test_galsan.jsonl 파일을 선택하세요.")
uploaded = files.upload()
TEST_FILE = next(iter(uploaded))   # 업로드된 파일명 자동 감지

# ── 공통 설정 ─────────────────────────────────────────────────────────────────
import json, sys
import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from sklearn.metrics import (
    classification_report, f1_score,
    precision_score, recall_score, accuracy_score,
)

HF_REPO   = "yunjeong116/koelectra-extractor"
MODELS = {
    "base-v1": {
        "revision":  "base-v1",
        "subfolder": "koelectra-extractor",   # base-v1 브랜치는 서브폴더에 가중치 있음
        "default_thr": 0.55,
    },
    "base (v4_merged)": {
        "revision":  "main",
        "subfolder": "",                       # main 브랜치 루트에 가중치 있음
        "default_thr": 0.40,
    },
}

MAX_LEN    = 128
BATCH      = 64
DEVICE     = "cuda" if torch.cuda.is_available() else "cpu"
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
rows   = [json.loads(l) for l in open(TEST_FILE, encoding="utf-8") if l.strip()]
texts  = [r["text"] for r in rows]
y_true = [int(bool(r.get("is_todo"))) for r in rows]
print(f"\n테스트셋(galsan unseen): {len(texts)}건  "
      f"할 일={sum(y_true)}  노이즈={len(y_true)-sum(y_true)}")
print(f"device: {DEVICE}\n")

# ── 추론 ─────────────────────────────────────────────────────────────────────
all_probs = {}
for name, cfg in MODELS.items():
    print(f"로딩: {name}  (revision={cfg['revision']}, subfolder={cfg['subfolder'] or '(root)'})")
    load_kwargs = dict(
        pretrained_model_name_or_path=HF_REPO,
        revision=cfg["revision"],
    )
    if cfg["subfolder"]:
        load_kwargs["subfolder"] = cfg["subfolder"]

    tok = AutoTokenizer.from_pretrained(**load_kwargs)
    mdl = AutoModelForSequenceClassification.from_pretrained(**load_kwargs, num_labels=2)
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
print(f"{'모델':<18} {'Threshold':>10} {'Accuracy':>10} {'F1':>8} {'Precision':>10} {'Recall':>8}")
print("-" * 68)
for name, s in summary.items():
    print(f"{name:<18} {s['thr']:>10.2f} {s['acc']:>10.4f} {s['f1']:>8.4f} {s['pre']:>10.4f} {s['rec']:>8.4f}")

v1, v2 = list(summary.values())
print("\n변화 (v4_merged - base-v1):")
print(f"  Accuracy  : {v2['acc']-v1['acc']:+.4f}")
print(f"  F1        : {v2['f1'] -v1['f1'] :+.4f}")
print(f"  Precision : {v2['pre']-v1['pre']:+.4f}")
print(f"  Recall    : {v2['rec']-v1['rec']:+.4f}")
