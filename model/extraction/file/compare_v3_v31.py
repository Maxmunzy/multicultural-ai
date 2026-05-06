"""
compare_v3_v31.py
=================
v3 vs v3.1 모델 성능 비교
두 테스트셋 모두 실행:
  A) v3.1 val split      (v3.1 학습 시 held-out 20%)
  B) unseen_test_galsan  (두 모델 모두 완전 unseen)
"""

import json
import os
import sys
import io
from pathlib import Path
import torch
from sklearn.metrics import accuracy_score, f1_score, classification_report
from transformers import AutoTokenizer, AutoModelForSequenceClassification

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

# 상대 경로로 로드하기 위해 ROOT로 이동
os.chdir(str(_ROOT))

V3_MODEL   = Path("checkpoints/koelectra-binary")
V31_MODEL  = Path("checkpoints/koelectra-binary-v3.1")

TEST_SETS = {
    "A_v31_val": Path("data/draft/v3.1_val_split.jsonl"),
    "B_galsan":  Path("data/draft/unseen_test_galsan.jsonl"),
}

def load_jsonl(path: Path):
    texts, labels = [], []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if "text" not in obj or "is_todo" not in obj:
            continue
        texts.append(str(obj["text"]))
        labels.append(int(bool(obj["is_todo"])))
    return texts, labels

def evaluate(model_path: Path, texts: list, true_labels: list, name: str):
    mp = model_path.as_posix()
    tokenizer = AutoTokenizer.from_pretrained(mp)
    model = AutoModelForSequenceClassification.from_pretrained(mp)
    model.eval()

    pred_labels = []
    batch_size = 32
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            enc = tokenizer(
                batch, truncation=True, max_length=128,
                padding=True, return_tensors="pt"
            )
            logits = model(**enc).logits
            preds = torch.argmax(logits, dim=-1).tolist()
            pred_labels.extend(preds)

    acc = accuracy_score(true_labels, pred_labels)
    f1  = f1_score(true_labels, pred_labels, pos_label=1, zero_division=0)

    print(f"\n  [{name}]  Accuracy={acc*100:.2f}%  F1(할 일)={f1:.4f}")
    print(classification_report(
        true_labels, pred_labels,
        target_names=["노이즈", "할 일"],
        digits=4,
        zero_division=0,
    ))
    return acc, f1, pred_labels


results = {}

for ts_name, ts_path in TEST_SETS.items():
    texts, true_labels = load_jsonl(ts_path)
    true_cnt = sum(true_labels)
    print(f"\n{'='*65}")
    print(f"테스트셋: {ts_name}  ({len(texts)}개 | True {true_cnt} / False {len(texts)-true_cnt})")
    print(f"{'='*65}")

    print("\n--- v3 모델 ---")
    v3_acc, v3_f1, _ = evaluate(V3_MODEL, texts, true_labels, "v3")

    print("--- v3.1 모델 ---")
    v31_acc, v31_f1, _ = evaluate(V31_MODEL, texts, true_labels, "v3.1")

    d_acc = (v31_acc - v3_acc) * 100
    d_f1  = v31_f1 - v3_f1

    print(f"\n  [요약] {ts_name}")
    print(f"  {'모델':<10} {'Accuracy':>10} {'F1(할 일)':>12}")
    print(f"  {'-'*36}")
    print(f"  {'v3':<10} {v3_acc*100:>9.2f}% {v3_f1:>12.4f}")
    print(f"  {'v3.1':<10} {v31_acc*100:>9.2f}% {v31_f1:>12.4f}")
    print(f"  {'변화':<10} {'+' if d_acc>=0 else ''}{d_acc:>8.2f}%p {'+' if d_f1>=0 else ''}{d_f1:>11.4f}")

    results[ts_name] = {
        "v3":  {"acc": v3_acc,  "f1": v3_f1},
        "v31": {"acc": v31_acc, "f1": v31_f1},
        "delta_acc": d_acc,
        "delta_f1":  d_f1,
    }

print(f"\n{'='*65}")
print("[전체 요약]")
print(f"{'='*65}")
for ts_name, r in results.items():
    print(f"\n{ts_name}")
    print(f"  v3   → Accuracy {r['v3']['acc']*100:.2f}%  F1 {r['v3']['f1']:.4f}")
    print(f"  v3.1 → Accuracy {r['v31']['acc']*100:.2f}%  F1 {r['v31']['f1']:.4f}")
    sign_a = "+" if r["delta_acc"] >= 0 else ""
    sign_f = "+" if r["delta_f1"]  >= 0 else ""
    print(f"  변화  → {sign_a}{r['delta_acc']:.2f}%p  {sign_f}{r['delta_f1']:.4f}")

if __name__ == "__main__":
    pass
