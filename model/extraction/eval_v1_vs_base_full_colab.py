"""
eval_v1_vs_base_full_colab.py
==============================
base-v1 (v3.1.3) vs base (v4_merged 현재 모델)
— seen(val split) + unseen(galsan) 동시 비교 (Colab GPU용)

실행 순서:
  1. 런타임 유형: T4 GPU
  2. 이 파일 전체를 Colab 셀에 붙여넣고 실행
  3. 업로드 창이 두 번 뜸:
       1차: v3.1_val_split.jsonl   (seen)
       2차: unseen_test_galsan.jsonl (unseen)
  4. 결과 출력 — 노트북 셀 1의 MODELS / THR_DATA 에 복붙
"""

# ── 패키지 설치 ───────────────────────────────────────────────────────────────
import subprocess
subprocess.run(["pip", "install", "transformers", "torch", "scikit-learn", "-q"],
               check=True)

# ── 파일 업로드 ───────────────────────────────────────────────────────────────
from google.colab import files

print("① v3.1_val_split.jsonl (seen) 업로드하세요.")
up1 = files.upload()
SEEN_FILE = next(iter(up1))

print("② unseen_test_galsan.jsonl (unseen) 업로드하세요.")
up2 = files.upload()
UNSEEN_FILE = next(iter(up2))

# ── 공통 설정 ─────────────────────────────────────────────────────────────────
import json, numpy as np, torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score,
    recall_score, classification_report,
)

HF_REPO    = "yunjeong116/koelectra-extractor"
DEVICE     = "cuda" if torch.cuda.is_available() else "cpu"
MAX_LEN    = 128
BATCH      = 64
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

MODELS_CFG = {
    "base-v1 (v3.1.3)": {
        "revision":    "base-v1",
        "subfolder":   "koelectra-extractor",
        "default_thr": 0.55,
    },
    "base (v4_merged)": {
        "revision":    "main",
        "subfolder":   "",          # main 브랜치 루트
        "default_thr": 0.40,
    },
}

print(f"\ndevice: {DEVICE}\n")

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
def load_jsonl(path):
    texts, labels = [], []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        obj = json.loads(line)
        if "text" not in obj or "is_todo" not in obj:
            continue
        texts.append(str(obj["text"]))
        labels.append(int(bool(obj["is_todo"])))
    return texts, labels

seen_texts,   seen_labels   = load_jsonl(SEEN_FILE)
unseen_texts, unseen_labels = load_jsonl(UNSEEN_FILE)

print(f"[Seen]   {len(seen_texts)}문장  할 일={sum(seen_labels)}  노이즈={len(seen_labels)-sum(seen_labels)}")
print(f"[Unseen] {len(unseen_texts)}문장  할 일={sum(unseen_labels)}  노이즈={len(unseen_labels)-sum(unseen_labels)}\n")

# ── 추론 (확률값 저장) ────────────────────────────────────────────────────────
all_probs = {}   # {model_name: {"seen": ndarray, "unseen": ndarray}}

for name, cfg in MODELS_CFG.items():
    print(f"로딩: {name}  (revision={cfg['revision']}, subfolder={cfg['subfolder'] or '(root)'})")
    kw = dict(pretrained_model_name_or_path=HF_REPO, revision=cfg["revision"])
    if cfg["subfolder"]:
        kw["subfolder"] = cfg["subfolder"]

    tok = AutoTokenizer.from_pretrained(**kw)
    mdl = AutoModelForSequenceClassification.from_pretrained(**kw, num_labels=2)
    mdl.to(DEVICE).eval()

    def infer(texts):
        probs = []
        for i in range(0, len(texts), BATCH):
            batch = texts[i : i + BATCH]
            enc = tok(batch, truncation=True, padding=True,
                      max_length=MAX_LEN, return_tensors="pt")
            enc = {k: v.to(DEVICE) for k, v in enc.items()}
            with torch.no_grad():
                logits = mdl(**enc).logits
            probs.extend(torch.softmax(logits, dim=-1)[:, 1].cpu().numpy())
        return np.array(probs)

    all_probs[name] = {
        "seen":   infer(seen_texts),
        "unseen": infer(unseen_texts),
    }
    print(f"  완료\n")

# ── 임계값 탐색 + 결과 수집 ──────────────────────────────────────────────────
SEP = "=" * 65
results = {}   # {model_name: {split: {thr, acc, f1, prec, rec}}}

for name, cfg in MODELS_CFG.items():
    results[name] = {}
    for split, y_true in [("seen", seen_labels), ("unseen", unseen_labels)]:
        probs   = all_probs[name][split]
        default = cfg["default_thr"]
        print(f"{SEP}")
        print(f"  {name}  [{split}]  임계값 탐색")
        print(f"{SEP}")
        print(f"  {'Threshold':>10} {'F1':>8} {'Prec':>9} {'Recall':>8}")
        print("  " + "-" * 40)

        best_f1, best_thr = 0.0, default
        thr_rows = []
        for thr in THRESHOLDS:
            preds = (probs >= thr).astype(int)
            f1  = f1_score(y_true, preds, pos_label=1, zero_division=0)
            pre = precision_score(y_true, preds, pos_label=1, zero_division=0)
            rec = recall_score(y_true, preds, pos_label=1, zero_division=0)
            tag = " <- default" if thr == default else ""
            if f1 > best_f1:
                best_f1, best_thr = f1, thr
                tag += " *best"
            print(f"  {thr:>10.2f} {f1:>8.4f} {pre:>9.4f} {rec:>8.4f}{tag}")
            thr_rows.append((thr, f1, pre, rec))

        # 최적 threshold 기준 최종 지표
        preds = (probs >= best_thr).astype(int)
        results[name][split] = {
            "thr":  best_thr,
            "acc":  accuracy_score(y_true, preds),
            "f1":   f1_score(y_true, preds, pos_label=1, zero_division=0),
            "prec": precision_score(y_true, preds, pos_label=1, zero_division=0),
            "rec":  recall_score(y_true, preds, pos_label=1, zero_division=0),
            "thr_rows": thr_rows,
        }
        print()

# ── 최종 비교 요약 ────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  최종 비교 요약 (각 모델 최적 threshold 기준)")
print(SEP)

for split in ["seen", "unseen"]:
    tag = "Seen (v3.1_val_split)" if split == "seen" else "Unseen (galsan)"
    print(f"\n  [{tag}]")
    print(f"  {'모델':<20} {'Thr':>5} {'Acc':>8} {'F1':>8} {'Prec':>8} {'Recall':>8}")
    print("  " + "-" * 62)
    vals = []
    for name in MODELS_CFG:
        r = results[name][split]
        print(f"  {name:<20} {r['thr']:>5.2f} {r['acc']:>8.4f} {r['f1']:>8.4f} "
              f"{r['prec']:>8.4f} {r['rec']:>8.4f}")
        vals.append(r)
    if len(vals) == 2:
        a, b = vals
        print(f"  {'향상 폭 (base - v1)':<20} {'':>5} "
              f"{b['acc']-a['acc']:>+8.4f} {b['f1']-a['f1']:>+8.4f} "
              f"{b['prec']-a['prec']:>+8.4f} {b['rec']-a['rec']:>+8.4f}")

# ── 노트북 복붙용 출력 ────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  ★ 노트북 셀 1 복붙용 — MODELS 업데이트")
print(SEP)

for name, cfg in MODELS_CFG.items():
    for split in ["seen", "unseen"]:
        r = results[name][split]
        print(f"# {name} [{split}]  thr={r['thr']}")
        print(f"  acc={r['acc']:.4f}  f1={r['f1']:.4f}  "
              f"prec={r['prec']:.4f}  rec={r['rec']:.4f}")

print(f"\n{SEP}")
print("  ★ 노트북 셀 1 복붙용 — THR_DATA (unseen, F1)")
print(SEP)
for name in MODELS_CFG:
    thr_rows = results[name]["unseen"]["thr_rows"]
    f1s  = [f'{r[1]:.4f}' for r in thr_rows]
    pres = [f'{r[2]:.4f}' for r in thr_rows]
    recs = [f'{r[3]:.4f}' for r in thr_rows]
    print(f"# {name}")
    print(f"  f1:   [{', '.join(f1s)}]")
    print(f"  prec: [{', '.join(pres)}]")
    print(f"  rec:  [{', '.join(recs)}]")
