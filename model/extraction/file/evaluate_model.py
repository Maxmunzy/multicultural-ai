"""
evaluate_model.py
=================
Base 모델 vs v2 Fine-tuned vs v3 Fine-tuned 성능 비교

[실행 전 준비]
  1. test_data.jsonl 준비
       python scripts/export_predict_output.py  # 자동 생성
  2. 체크포인트 배치
       checkpoints/koelectra-binary/       ← 현재(v3) 모델
       checkpoints/koelectra-binary-v2/    ← 이전(v2) 모델 (선택)

[사용법]
  # Base vs v3
  python file/evaluate_model.py

  # Base vs v2 vs v3
  python file/evaluate_model.py --v2_model ../checkpoints/koelectra-binary-v2

  # 테스트 데이터 직접 지정
  python file/evaluate_model.py --test_data ../data/train/test_data.jsonl
"""

import argparse
import sys
from pathlib import Path

from sklearn.metrics import accuracy_score, classification_report, f1_score
from transformers import pipeline

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_TEST_DATA    = _ROOT / "data" / "train" / "test_data.jsonl"
BASE_MODEL_ID        = "monologg/koelectra-small-v3-discriminator"
V3_MODEL_PATH        = str(_ROOT / "checkpoints" / "koelectra-binary")
V2_MODEL_PATH        = str(_ROOT / "checkpoints" / "koelectra-binary-v2")

_LABEL_MAP = {
    "노이즈":  0,
    "할 일":   1,
    "LABEL_0": 0,
    "LABEL_1": 1,
}


def _parse_label(raw: str) -> int:
    if raw in _LABEL_MAP:
        return _LABEL_MAP[raw]
    try:
        return int(raw.split("_")[-1])
    except ValueError:
        raise ValueError(f"알 수 없는 라벨: {raw!r}")


def evaluate_model(
    model_path: str,
    test_texts: list[str],
    true_labels: list[int],
    model_name: str = "Model",
) -> tuple[float, float]:
    print(f"\n[{model_name}] 추론 중...")
    clf = pipeline(
        "text-classification",
        model=model_path,
        tokenizer=model_path,
        device=-1,
        truncation=True,
        max_length=128,
    )
    predictions = clf(test_texts, batch_size=16)
    pred_labels = [_parse_label(p["label"]) for p in predictions]

    acc = accuracy_score(true_labels, pred_labels)
    f1  = f1_score(true_labels, pred_labels, pos_label=1, zero_division=0)

    print(f"[{model_name}] 완료")
    print(f"  Accuracy : {acc * 100:.2f}%")
    print(f"  F1-Score : {f1:.4f}")
    print()
    print(classification_report(
        true_labels, pred_labels,
        target_names=["노이즈(0)", "할 일(1)"],
        digits=4,
        zero_division=0,
    ))
    return acc, f1


def load_test_data(path: Path) -> tuple[list[str], list[int]]:
    import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Base / v2 / v3 모델 성능 비교")
    parser.add_argument(
        "--test_data",
        type=Path,
        default=DEFAULT_TEST_DATA,
        help=f"테스트 JSONL 경로 (기본: {DEFAULT_TEST_DATA})",
    )
    parser.add_argument(
        "--v3_model",
        default=V3_MODEL_PATH,
        help=f"v3 Fine-tuned 모델 경로 (기본: {V3_MODEL_PATH})",
    )
    parser.add_argument(
        "--v2_model",
        default=None,
        help="v2 Fine-tuned 모델 경로 (없으면 Base vs v3 비교만 수행)",
    )
    args = parser.parse_args()

    if not args.test_data.exists():
        print(f"[오류] 테스트 파일이 없습니다: {args.test_data}", file=sys.stderr)
        print("  먼저 실행: python scripts/export_predict_output.py", file=sys.stderr)
        sys.exit(1)

    test_texts, true_labels = load_test_data(args.test_data)
    print(f"테스트 문장: {len(test_texts)}개")
    print(f"  할 일(1): {sum(true_labels)}개  "
          f"노이즈(0): {len(true_labels) - sum(true_labels)}개")

    # ── Base 모델 ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Base 모델 (파인튜닝 전, 랜덤 가중치)")
    print("=" * 60)
    base_acc, base_f1 = evaluate_model(
        BASE_MODEL_ID, test_texts, true_labels, "Base"
    )

    # ── v2 Fine-tuned (선택) ──────────────────────────────────────────────
    v2_acc = v2_f1 = None
    if args.v2_model:
        v2_path = Path(args.v2_model)
        if not v2_path.exists():
            print(f"[경고] v2 모델 경로 없음: {v2_path} — 건너뜀", file=sys.stderr)
        else:
            print("=" * 60)
            print("v2 Fine-tuned 모델")
            print("=" * 60)
            v2_acc, v2_f1 = evaluate_model(
                str(v2_path), test_texts, true_labels, "v2 Fine-tuned"
            )

    # ── v3 Fine-tuned ─────────────────────────────────────────────────────
    print("=" * 60)
    print("v3 Fine-tuned 모델 (v3_dual_labeled_clean.jsonl 학습)")
    print("=" * 60)
    v3_acc, v3_f1 = evaluate_model(
        args.v3_model, test_texts, true_labels, "v3 Fine-tuned"
    )

    # ── 비교 요약 ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[성능 비교 요약]")
    print("=" * 60)
    print(f"{'모델':<22} {'Accuracy':>10} {'F1 (할 일)':>12}")
    print("-" * 48)
    print(f"{'Base 모델':<22} {base_acc*100:>9.2f}% {base_f1:>12.4f}")
    if v2_acc is not None:
        print(f"{'v2 Fine-tuned':<22} {v2_acc*100:>9.2f}% {v2_f1:>12.4f}")
    print(f"{'v3 Fine-tuned':<22} {v3_acc*100:>9.2f}% {v3_f1:>12.4f}")
    print("-" * 48)

    ref_acc = v2_acc if v2_acc is not None else base_acc
    ref_f1  = v2_f1  if v2_f1  is not None else base_f1
    ref_name = "v2 대비" if v2_acc is not None else "Base 대비"
    delta_acc = (v3_acc - ref_acc) * 100
    delta_f1  = v3_f1 - ref_f1
    print(f"{'v3 향상 폭 (' + ref_name + ')':<22} "
          f"{'+' if delta_acc>=0 else ''}{delta_acc:>8.2f}%p "
          f"{'+' if delta_f1>=0 else ''}{delta_f1:>11.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
