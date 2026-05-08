"""
relabel_false_model.py
======================
v4_labeled.jsonl의 is_todo=False 문장을 koelectra-binary-base 모델로 재검수.
BINARY_THRESHOLD 이상이면 True로 전환.

사용법:
  python scripts/relabel_false_model.py \
    --input  model/extraction/data/train/v4_labeled.jsonl \
    --output model/extraction/data/train/v4_relabeled.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

import torch
from transformers import pipeline

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parent.parent
# small 모델: 14M params — CPU에서 base(110M) 대비 ~10배 빠름, threshold 0.55 사용
_CHECKPOINT = _ROOT / "model" / "extraction" / "checkpoints" / "koelectra-binary-v3.1"
BINARY_THRESHOLD = 0.55
BATCH_SIZE = 256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=_CHECKPOINT)
    parser.add_argument("--threshold", type=float, default=BINARY_THRESHOLD)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[오류] 파일 없음: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"모델 로드: {args.checkpoint}")
    clf = pipeline(
        "text-classification",
        model=str(args.checkpoint),
        tokenizer=str(args.checkpoint),
        device=-1,
        truncation=True,
        max_length=128,
    )
    print(f"  threshold={args.threshold}")

    # 전체 레코드 로드
    records = []
    for line in args.input.read_text("utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    print(f"전체 문장: {len(records)}개")

    # False 문장 인덱스 추출
    false_indices = [i for i, r in enumerate(records) if not r.get("is_todo", False)]
    false_texts   = [records[i]["text"] for i in false_indices]
    print(f"  is_todo=False (재검수 대상): {len(false_indices)}개")

    # 배치 추론
    flipped = 0
    scores: list[float] = []
    for start in range(0, len(false_texts), BATCH_SIZE):
        batch = false_texts[start:start + BATCH_SIZE]
        results = clf(batch, batch_size=BATCH_SIZE)
        for r in results:
            prob = r["score"] if r["label"] == "할 일" else 1.0 - r["score"]
            scores.append(prob)
        done = min(start + BATCH_SIZE, len(false_texts))
        if done % 2000 == 0 or done == len(false_texts):
            print(f"  진행: {done}/{len(false_texts)}", flush=True)

    # 레이블 업데이트
    for idx, score in zip(false_indices, scores):
        if score >= args.threshold:
            records[idx]["is_todo"] = True
            records[idx]["label_reason"] = f"model_relabel(conf={score:.3f})"
            flipped += 1

    # 저장
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total_true  = sum(1 for r in records if r.get("is_todo"))
    total_false = len(records) - total_true
    print(f"\n재라벨링 완료")
    print(f"  False → True 전환: {flipped}개")
    print(f"  최종 is_todo=True : {total_true}개 ({total_true/len(records)*100:.1f}%)")
    print(f"  최종 is_todo=False: {total_false}개 ({total_false/len(records)*100:.1f}%)")
    print(f"  저장: {args.output}")


if __name__ == "__main__":
    main()
