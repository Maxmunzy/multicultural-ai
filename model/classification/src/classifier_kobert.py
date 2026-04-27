"""KoBERT/KoELECTRA fine-tuning 트랙 (최고 성능, GPU 또는 인내심 필요).

언제 쓰는가?
- 데이터가 1,000건 이상으로 늘었을 때
- 라벨 노이즈가 적고 재현 가능 라이브러리 환경이 보장된 서버일 때
- 1~2% 추가 성능을 짜야 할 때

CPU에서도 동작은 하지만 epoch당 수 분 걸린다 (200건 기준 1 epoch ≈ 2~3분).
실제 운영을 위한 권장 환경:
- GPU (Colab T4, RTX 3060 등): 1~2분/epoch
- CPU에서는 KoELECTRA-small 또는 monologg/distilkobert 추천

대안: Qwen2.5
-------------
LM(생성) 모델인 Qwen2.5-0.5B를 분류로 쓰려면 LoRA + 분류 헤드가 정석이지만
0.5B도 CPU 학습은 비현실적이다. 추론만 가능하다면 zero-shot prompt로
카테고리를 묻는 방식도 가능하다. 본 파일에는 fine-tune 코드만 두고,
zero-shot 방식은 `qwen_zero_shot.py`(선택)에 분리해 두면 좋다.

사용법:
    from src.classifier_kobert import train_kobert
    model_dir = train_kobert(train_texts, train_labels, epochs=5)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .config import KOBERT_MODEL, KOELECTRA_MODEL, LABEL2ID, LABELS, MODEL_DIR

try:
    import torch
    from torch.utils.data import DataLoader, Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )
    TORCH_OK = True
except ImportError:
    TORCH_OK = False


class _NoticeDataset:
    """단순 (text, label) 데이터셋."""

    def __init__(self, texts: list[str], labels: list[int], tokenizer, max_len: int = 128):
        self.texts = texts
        self.labels = labels
        self.tok = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        enc = self.tok(
            self.texts[idx],
            truncation=True,
            padding="max_length",
            max_length=self.max_len,
            return_tensors="pt",
        )
        item = {k: v.squeeze(0) for k, v in enc.items()}
        item["labels"] = torch.tensor(self.labels[idx], dtype=torch.long)
        return item


def train_kobert(
    train_texts: list[str],
    train_labels: list[str],
    *,
    val_texts: list[str] | None = None,
    val_labels: list[str] | None = None,
    model_name: str = KOELECTRA_MODEL,  # KoELECTRA-base가 KoBERT보다 가볍고 강함
    epochs: int = 5,
    batch_size: int = 16,
    lr: float = 2e-5,
    output_dir: Path | None = None,
) -> Path:
    """가장 단순한 fine-tuning 루프. transformers + torch가 있는 환경에서 동작."""
    if not TORCH_OK:
        raise ImportError(
            "`pip install torch transformers` 가 필요합니다 (CPU 버전 가능)."
        )

    output_dir = output_dir or (MODEL_DIR / "kobert_classifier")
    output_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name, num_labels=len(LABELS)
    )

    y_train = [LABEL2ID[l] for l in train_labels]
    train_ds = _NoticeDataset(train_texts, y_train, tokenizer)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    total_steps = epochs * len(train_loader)
    sched = get_linear_schedule_with_warmup(
        optim, num_warmup_steps=int(0.1 * total_steps), num_training_steps=total_steps
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    # 클래스 가중치 (데이터가 적은 비용 클래스 보정)
    counts = np.bincount(y_train, minlength=len(LABELS)).astype(np.float32)
    class_weight = torch.tensor(
        counts.max() / np.clip(counts, 1, None), dtype=torch.float32, device=device
    )
    loss_fn = torch.nn.CrossEntropyLoss(weight=class_weight)

    for epoch in range(1, epochs + 1):
        model.train()
        epoch_loss = 0.0
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            out = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                token_type_ids=batch.get("token_type_ids"),
            )
            loss = loss_fn(out.logits, batch["labels"])
            optim.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            sched.step()
            epoch_loss += loss.item()
        print(f"epoch {epoch}/{epochs} loss={epoch_loss/len(train_loader):.4f}")

        # 옵션: 매 에폭 val 평가
        if val_texts:
            acc = _eval(model, tokenizer, val_texts, val_labels, device)
            print(f"  val acc={acc:.3f}")

    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    return output_dir


def _eval(model, tokenizer, texts, labels, device) -> float:
    model.eval()
    correct = 0
    with torch.no_grad():
        for t, gold in zip(texts, labels):
            enc = tokenizer(t, return_tensors="pt", truncation=True, max_length=128).to(device)
            logits = model(**enc).logits
            pred_id = int(logits.argmax(-1).item())
            if LABELS[pred_id] == gold:
                correct += 1
    return correct / len(texts)


def predict_kobert(model_dir: Path, texts: list[str]) -> list[str]:
    """저장된 KoBERT/KoELECTRA로 추론."""
    if not TORCH_OK:
        raise ImportError("`pip install torch transformers` 가 필요합니다.")
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device).eval()
    out = []
    with torch.no_grad():
        for t in texts:
            enc = tokenizer(t, return_tensors="pt", truncation=True, max_length=128).to(device)
            logits = model(**enc).logits
            out.append(LABELS[int(logits.argmax(-1).item())])
    return out


# ---- Qwen2.5 zero-shot helper (선택) -----------------------------------------
def qwen_zero_shot_predict(text: str, *, model_name: str = "Qwen/Qwen2.5-0.5B") -> str:
    """별도 학습 없이 LM에 카테고리를 직접 묻는 방식.

    장점: 학습 불필요, 즉시 도입.
    단점: CPU에서도 0.5B가 느리고 (초당 1~2 문장), 정확도가 fine-tune보다 낮음.
    추천: 콜드 스타트 시 임시 분류 → 라벨 데이터 더 모이면 fine-tune 전환.
    """
    if not TORCH_OK:
        raise ImportError("`pip install torch transformers` 가 필요합니다.")
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name)
    prompt = (
        "다음 가정통신문 문장을 정확히 하나의 카테고리로만 분류하세요.\n"
        "선택지: " + ", ".join(LABELS) + "\n"
        f"문장: {text}\n"
        "카테고리:"
    )
    enc = tok(prompt, return_tensors="pt")
    out = model.generate(**enc, max_new_tokens=8, do_sample=False)
    decoded = tok.decode(out[0, enc.input_ids.shape[1] :], skip_special_tokens=True).strip()
    # 출력에서 가장 먼저 나오는 라벨 찾기
    for l in LABELS:
        if l in decoded:
            return l
    return "기타"
