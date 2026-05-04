"""
KcELECTRA 파인튜닝 분류기 — 추론 전용 모듈
============================================
담당: 경이
역할: 01_train_kcelectra.ipynb에서 학습·저장된 모델을 불러와
      텍스트 → 6-class 카테고리 추론 수행.
      학습(Training)은 이 파일이 아닌 notebooks/01_train_kcelectra.ipynb에서 진행.

요구 환경: torch, transformers (CPU 추론 가능)
학습 체크포인트 경로: model/classification/checkpoints/kcelectra-category/
"""

import os
import json
from pathlib import Path
from typing import Optional

# 의존성 지연 임포트 — transformers 없는 환경(CI)에서 모듈 로드만큼은 안전하게
try:
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False

_BASE = Path(__file__).parent.parent
_CKPT_DIR = _BASE / "checkpoints" / "kcelectra-category" # 파인튜닝된 로컬 모델
_LABELS_FILE = _CKPT_DIR / "label2id.json"

# HF Hub fallback — 로컬 체크포인트 없을 때 사용 (학습 전엔 이 경로로 불러옴)
_BASE_MODEL_ID = "monologg/koelectra-small-v3-discriminator" # HuggingFace Hub

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]

_tokenizer = None
_model     = None
_id2label: dict[int, str] = {}
_device = "cpu"

# 가장 핵심적인 함수입니다. 3가지 작업을 합니다.
# ① 로컬 체크포인트 vs Hub 자동 선택
# ② GPU/CPU 자동 선택
# ③ 라벨 맵핑 로드

def _load_model() -> None:
    global _tokenizer, _model, _id2label, _device

    if _model is not None:
        return
    if not _HF_AVAILABLE:
        raise ImportError("torch/transformers가 설치되지 않았습니다. pip install torch transformers")

    _device = "cuda" if torch.cuda.is_available() else "cpu"

    # 로컬 파인튜닝 체크포인트 우선
    _local_ready = (
        _CKPT_DIR.exists()
        and (_CKPT_DIR / "config.json").exists()
        and any(
            (_CKPT_DIR / f).exists()
            for f in ("pytorch_model.bin", "model.safetensors")
        )
    )

    src = str(_CKPT_DIR) if _local_ready else _BASE_MODEL_ID
    num_labels = len(LABELS)

    _tokenizer = AutoTokenizer.from_pretrained(src)
    _model = AutoModelForSequenceClassification.from_pretrained(
        src, num_labels=num_labels, ignore_mismatched_sizes=True
    )
    _model.to(_device)
    _model.eval()

    # 라벨 맵핑 로드 (파인튜닝 완료 후 저장된 파일)
    if _LABELS_FILE.exists():
        with open(_LABELS_FILE, "r", encoding="utf-8") as f:
            label2id: dict[str, int] = json.load(f)
        _id2label = {v: k for k, v in label2id.items()}
    else:
        _id2label = {i: label for i, label in enumerate(LABELS)}

    print(f"[kcelectra] 모델 로드 완료: {src} → device={_device}")


def predict_kcelectra(text: str) -> dict:
    """텍스트 → 카테고리 + 신뢰도.

    반환:
        {
            "category":   str,          # 예측 라벨
            "confidence": float,        # softmax 최대 확률
            "probs":      dict[str, float]
        }
    """
    _load_model()

    inputs = _tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=128,
    ).to(_device)

    # 추론 시 gradient 계산을 끄는 것입니다. 학습이 아닌 예측만 하므로 메모리를 절약하고 속도를 높입니다.
    with torch.no_grad():
        logits = _model(**inputs).logits
        probs  = torch.softmax(logits, dim=-1)[0]

    idx = int(probs.argmax().item())
    label = _id2label.get(idx, "기타")

    return {
        "category":   label,
        "confidence": float(probs[idx].item()),
        "probs": {
            _id2label.get(i, str(i)): float(p.item())
            for i, p in enumerate(probs)
        },
    }


def is_ready() -> bool:
    """파인튜닝된 체크포인트가 준비됐는지 확인."""
    return (
        _HF_AVAILABLE
        and _CKPT_DIR.exists()
        and (_CKPT_DIR / "config.json").exists()
    )
