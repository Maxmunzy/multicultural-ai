"""
evaluate_model.py
=================
Base 모델 vs Fine-tuned 모델 성능 비교 (강사님 제출용)

[실행 전 준비]
  1. test_data.jsonl 준비 — 학습에 쓰지 않은 문장 데이터
     형식: {"text": "문장...", "is_todo": true/false}
  2. Fine-tuned 모델 다운로드 후 아래 경로에 압축 해제
     checkpoints/koelectra-binary/

[사용법]
  python file/evaluate_model.py
  python file/evaluate_model.py --test_data data/test_data.jsonl
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from transformers import pipeline

# Windows 터미널 UTF-8 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# 스크립트 위치 기준 기본 경로
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_TEST_DATA      = _ROOT / "data" / "test_data.jsonl"
BASE_MODEL_PATH        = "monologg/koelectra-small-v3-discriminator"
FINETUNED_MODEL_PATH   = str(_ROOT / "checkpoints" / "koelectra-binary")

# 파인튜닝 모델의 id2label 이 한국어로 설정되어 있으므로 양쪽 형식 모두 처리
_LABEL_MAP = {
    "노이즈":  0,
    "할 일":   1,
    "LABEL_0": 0,
    "LABEL_1": 1,
}


def _parse_label(raw_label: str) -> int:
    """pipeline 출력 라벨을 0/1 정수로 변환"""
    if raw_label in _LABEL_MAP:
        return _LABEL_MAP[raw_label]
    # 혹시 LABEL_X 형태인 경우 fallback
    try:
        return int(raw_label.split("_")[-1])
    except ValueError:
        raise ValueError(f"알 수 없는 라벨: {raw_label!r}")


def evaluate_model(
    model_path: str,
    test_texts: list[str],
    true_labels: list[int],
    model_name: str = "Model",
) -> tuple[float, float]:
    """
    단일 모델 평가.

    Returns:
        (accuracy, f1_score) 튜플
    """
    print(f"\n[{model_name}] 추론 중...")

    clf = pipeline(
        "text-classification",
        model=model_path,
        tokenizer=model_path,
        device=-1,          # CPU 사용 (-1), GPU는 0
        truncation=True,    # 학습 조건과 일치
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Base vs Fine-tuned 모델 성능 비교")
    parser.add_argument(
        "--test_data",
        type=Path,
        default=DEFAULT_TEST_DATA,
        help=f"테스트 JSONL 경로 (기본: {DEFAULT_TEST_DATA})",
    )
    parser.add_argument(
        "--finetuned",
        default=FINETUNED_MODEL_PATH,
        help=f"파인튜닝 모델 경로 (기본: {FINETUNED_MODEL_PATH})",
    )
    args = parser.parse_args()

    # ── 테스트 데이터 로드 ────────────────────────────────────────────────────
    if not args.test_data.exists():
        print(f"[오류] 테스트 파일이 없습니다: {args.test_data}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_json(args.test_data, lines=True)

    if "text" not in df.columns or "is_todo" not in df.columns:
        print("[오류] JSONL에 'text', 'is_todo' 컬럼이 필요합니다.", file=sys.stderr)
        sys.exit(1)

    test_texts  = df["text"].tolist()
    true_labels = [int(v) for v in df["is_todo"]]   # bool -> 0/1

    print(f"테스트 문장: {len(test_texts)}개")
    print(f"  할 일(1): {sum(true_labels)}개  "
          f"노이즈(0): {len(true_labels) - sum(true_labels)}개")

    # ── Base 모델 평가 ────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("Base 모델 평가 (파인튜닝 전, 랜덤 가중치)")
    print("=" * 55)
    base_acc, base_f1 = evaluate_model(
        BASE_MODEL_PATH, test_texts, true_labels, "Base 모델"
    )

    # ── Fine-tuned 모델 평가 ──────────────────────────────────────────────────
    print("=" * 55)
    print("Fine-tuned 모델 평가 (KoELECTRA 이진 분류 학습 후)")
    print("=" * 55)
    ft_acc, ft_f1 = evaluate_model(
        args.finetuned, test_texts, true_labels, "Fine-tuned 모델"
    )

    # ── 강사님 제출용 비교 요약 ───────────────────────────────────────────────
    print("=" * 55)
    print("[강사님 제출용: Base vs Fine-tuned 성능 비교]")
    print("=" * 55)
    print(f"{'모델':<18} {'Accuracy':>10} {'F1-Score':>10}")
    print("-" * 42)
    print(f"{'Base 모델':<18} {base_acc*100:>9.2f}% {base_f1:>10.4f}")
    print(f"{'Fine-tuned 모델':<18} {ft_acc*100:>9.2f}% {ft_f1:>10.4f}")
    print("-" * 42)
    acc_delta = (ft_acc - base_acc) * 100
    f1_delta  = ft_f1 - base_f1
    sign_acc  = "+" if acc_delta >= 0 else ""
    sign_f1   = "+" if f1_delta  >= 0 else ""
    print(f"{'향상 폭':<18} {sign_acc}{acc_delta:>8.2f}%p {sign_f1}{f1_delta:>9.4f}")
    print("=" * 55)


if __name__ == "__main__":
    main()
