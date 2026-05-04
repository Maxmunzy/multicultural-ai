"""
train_koelectra.ipynb과 동일한 val split을 재현하여
predict.py A단계 결과를 JSONL로 저장.

출력 파일
  --output_predict  경이님이 B단계 입력으로 사용하는 A단계 결과
                    {text, source, due_date, amount, confidence, action_hint}
  --output_test     evaluate_model.py 용 테스트셋
                    {text, is_todo}

사용법
  python scripts/export_predict_output.py
  python scripts/export_predict_output.py \\
      --data model/extraction/data/train/v3_dual_labeled_clean.jsonl \\
      --output_predict data/processed/predict_output_testset.jsonl \\
      --output_test    model/extraction/data/train/test_data.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# predict.py 가 model/extraction/file/ 에 있으므로 sys.path 추가
_HERE = Path(__file__).resolve().parent
_EXTRACT_FILE = _HERE.parent / "model" / "extraction" / "file"
sys.path.insert(0, str(_EXTRACT_FILE))

from predict import (  # noqa: E402
    _classify,
    extract_action_hint,
    extract_amount,
    extract_due_date,
)
from sklearn.model_selection import train_test_split  # noqa: E402


def load_data(path: Path) -> tuple[list[str], list[int]]:
    texts, labels = [], []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        text = str(obj.get("text", "") or "").strip()
        if len(text) < 7:
            continue
        texts.append(text)
        labels.append(int(bool(obj.get("is_todo", False))))
    return texts, labels


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--data",
        type=Path,
        default=Path("model/extraction/data/train/v3_dual_labeled_clean.jsonl"),
    )
    p.add_argument(
        "--output_predict",
        type=Path,
        default=Path("data/processed/predict_output_testset.jsonl"),
        help="경이님용 A단계 출력 JSONL",
    )
    p.add_argument(
        "--output_test",
        type=Path,
        default=Path("model/extraction/data/train/test_data.jsonl"),
        help="evaluate_model.py 용 테스트셋 JSONL",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"[로드] {args.data}")
    texts, labels = load_data(args.data)
    print(f"  전체: {len(texts)}행")

    # train_koelectra.ipynb 와 동일한 split 파라미터
    _, val_texts, _, val_labels = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )
    print(f"  val split: {len(val_texts)}행 "
          f"(할 일={sum(val_labels)}, 노이즈={len(val_labels)-sum(val_labels)})")

    # ── test_data.jsonl 저장 ────────────────────────────────────────────
    args.output_test.parent.mkdir(parents=True, exist_ok=True)
    with args.output_test.open("w", encoding="utf-8") as f:
        for text, label in zip(val_texts, val_labels):
            f.write(json.dumps({"text": text, "is_todo": bool(label)}, ensure_ascii=False) + "\n")
    print(f"[저장] test_data.jsonl → {args.output_test}")

    # ── A단계 추론 → predict_output_testset.jsonl ───────────────────────
    args.output_predict.parent.mkdir(parents=True, exist_ok=True)
    predict_rows = []
    skipped = 0

    print("[추론] A단계 실행 중...")
    for i, (text, true_label) in enumerate(zip(val_texts, val_labels), 1):
        if i % 500 == 0:
            print(f"  {i}/{len(val_texts)} ({i/len(val_texts)*100:.1f}%)")

        confidence = _classify(text)
        if confidence is None:
            skipped += 1
            continue

        predict_rows.append({
            "text":         text,
            "source":       None,
            "due_date":     extract_due_date(text),
            "amount":       extract_amount(text),
            "confidence":   round(confidence, 4),
            "action_hint":  extract_action_hint(text),
            # 검증용 필드 (경이님이 필요 없으면 무시해도 됨)
            "true_is_todo": bool(true_label),
        })

    with args.output_predict.open("w", encoding="utf-8") as f:
        for row in predict_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[저장] A단계 결과 → {args.output_predict}")
    print(f"  총 {len(predict_rows)}행 저장 (정규식 필터 제외: {skipped}행)")


if __name__ == "__main__":
    main()
