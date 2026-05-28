"""Hybrid Sentence Extractor — LayoutXLM (frozen) + KoCharELECTRA + BIO head.

처리 순서 (사용자 설계 — visual 먼저, char 정밀화):
  PDF (page image + word + bbox)
   ↓
  [LayoutXLM frozen]
    └─ word + bbox + image → subword representation
   ↓ word별 첫 subword 대표 → char에 broadcast
   ↓
  [KoCharELECTRA] (char encoder, fine-tune)
    └─ char + broadcasted visual context → 통합 char representation
   ↓
  [BIO head] char별 O / B-SENT / I-SENT
   ↓
  sentence_list (변형 0: 원문 char substring)

각 모델의 강점만:
  - LayoutXLM: visual layout (표 column/row, 본문 paragraph 영역)
  - KoCharELECTRA: 한국어 char-level boundary 정밀도

변형 0 보장: encoder + classification only, generation X.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
import torch.nn as nn

LAYOUTXLM_ID = "microsoft/layoutxlm-base"
# v9 base 모델 효과 없음 확인됨 → small 복귀. v10 axis는 LayoutXLM unfreeze로 도메인 적응.
KOCHAR_ID = "monologg/kocharelectra-small-discriminator"
NUM_LABELS = 3  # 0=O, 1=B-SENT, 2=I-SENT


@dataclass
class HybridConfig:
    layoutxlm_id: str = LAYOUTXLM_ID
    kochar_id: str = KOCHAR_ID
    num_labels: int = NUM_LABELS
    layoutxlm_dim: int = 768
    kochar_dim: int = 256  # small (base는 768)
    fusion_hidden: int = 384  # (768 + 256) / 2 가까운 값
    dropout: float = 0.1
    # Class imbalance: B 2%, I 64%, O 34%. B 가중치 ↑
    class_weights: tuple[float, float, float] = (1.0, 8.0, 1.0)
    layoutxlm_frozen: bool = True
    # v10 axis: LayoutXLM 마지막 N layer unfreeze (도메인 적응).
    # frozen=True여도 unfreeze_last_n > 0이면 마지막 N layer만 train.
    # 0 = 전체 frozen (v7과 동등), 2 = 마지막 2 layer 도메인 적응
    layoutxlm_unfreeze_last_n: int = 0
    # CRF — sequence consistency 학습 (단편화 fix용, v7+ axis)
    # True 시 pytorch-crf 의존성 필요 (`pip install pytorch-crf`)
    use_crf: bool = False


class HybridSentenceExtractor(nn.Module):
    """LayoutXLM (frozen) → word repr → char broadcast → KoCharELECTRA → BIO."""

    def __init__(self, config: HybridConfig = HybridConfig()):
        super().__init__()
        from transformers import LayoutLMv2Model, ElectraModel

        self.config = config

        # LayoutXLM (visual + layout encoder)
        self.layoutxlm = LayoutLMv2Model.from_pretrained(config.layoutxlm_id)
        if config.layoutxlm_frozen:
            for p in self.layoutxlm.parameters():
                p.requires_grad = False
            # v10 axis: 마지막 N layer만 unfreeze — 도메인 적응 (cell-boundary signal을 학습 분포에 맞게 재학습)
            if config.layoutxlm_unfreeze_last_n > 0:
                n = config.layoutxlm_unfreeze_last_n
                for layer in self.layoutxlm.encoder.layer[-n:]:
                    for p in layer.parameters():
                        p.requires_grad = True

        # KoCharELECTRA (char-level Korean encoder, fine-tune)
        self.kochar = ElectraModel.from_pretrained(config.kochar_id)

        # Fusion: char_repr (kochar_dim) + word_repr_broadcasted (layoutxlm_dim) → kochar_dim
        fusion_in = config.kochar_dim + config.layoutxlm_dim
        self.fusion = nn.Sequential(
            nn.Linear(fusion_in, config.fusion_hidden),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.fusion_hidden, config.kochar_dim),
        )

        # BIO classification head
        self.classifier = nn.Linear(config.kochar_dim, config.num_labels)

        # Optional CRF layer — sequence consistency (단편화 fix)
        self.crf = None
        if config.use_crf:
            try:
                from torchcrf import CRF
                self.crf = CRF(config.num_labels, batch_first=True)
            except ImportError as e:
                raise ImportError(
                    "use_crf=True requires pytorch-crf: `pip install pytorch-crf`"
                ) from e

        # Loss (CRF 사용 시 unused, but kept for fallback)
        weights = torch.tensor(list(config.class_weights), dtype=torch.float)
        self.register_buffer("class_weights", weights)

    def _get_word_repr(
        self,
        layoutxlm_inputs: dict[str, torch.Tensor],
        word_ids_list: list[list[int | None]],
    ) -> torch.Tensor:
        """LayoutXLM forward → subword repr → word별 첫 subword 대표 → word repr.

        Args:
            layoutxlm_inputs: processor 출력 (input_ids, bbox, image, attention_mask)
            word_ids_list: [B, T] — 각 token이 어느 word에 속하는지 (None for special tokens)

        Returns:
            word_repr: [B, W_max, layoutxlm_dim] — 각 word의 representation
        """
        if self.config.layoutxlm_frozen:
            with torch.no_grad():
                outputs = self.layoutxlm(**layoutxlm_inputs)
        else:
            outputs = self.layoutxlm(**layoutxlm_inputs)
        subword_repr = outputs.last_hidden_state  # [B, T, layoutxlm_dim]

        B, T, D = subword_repr.shape
        # Find max word count across batch
        max_word = 0
        for word_ids in word_ids_list:
            valid = [w for w in word_ids if w is not None]
            if valid:
                max_word = max(max_word, max(valid) + 1)
        if max_word == 0:
            max_word = 1

        word_repr = torch.zeros(B, max_word, D, device=subword_repr.device, dtype=subword_repr.dtype)
        word_mask = torch.zeros(B, max_word, device=subword_repr.device, dtype=torch.bool)
        for b, word_ids in enumerate(word_ids_list):
            seen: set[int] = set()
            for t, wid in enumerate(word_ids):
                if wid is None or wid in seen:
                    continue
                if wid >= max_word:
                    continue
                word_repr[b, wid] = subword_repr[b, t]
                word_mask[b, wid] = True
                seen.add(wid)
        return word_repr, word_mask

    def forward(
        self,
        layoutxlm_inputs: dict[str, torch.Tensor],
        word_ids_list: list[list[int | None]],
        char_input_ids: torch.Tensor,         # [B, C] KoCharELECTRA tokenizer 결과
        char_attention_mask: torch.Tensor,    # [B, C]
        char_to_word: torch.Tensor,           # [B, C] long, 각 char가 어느 word index
        labels: torch.Tensor | None = None,   # [B, C] long, -100=ignore, 0/1/2
    ) -> dict[str, torch.Tensor]:
        # 1. LayoutXLM → word repr
        word_repr, _ = self._get_word_repr(layoutxlm_inputs, word_ids_list)
        # word_repr: [B, W_max, layoutxlm_dim]

        # 2. word → char broadcast (gather)
        B, C = char_to_word.shape
        # char_to_word 범위 clamp (out-of-range 방지)
        max_word = word_repr.size(1)
        ctw_clamped = char_to_word.clamp(min=0, max=max_word - 1)
        # gather [B, C, layoutxlm_dim]
        char_visual_ctx = word_repr.gather(
            1, ctw_clamped.unsqueeze(-1).expand(-1, -1, word_repr.size(-1))
        )
        # char_to_word == -1 (special)인 위치는 zero
        invalid_mask = (char_to_word < 0)
        char_visual_ctx = char_visual_ctx.masked_fill(invalid_mask.unsqueeze(-1), 0.0)

        # 3. KoCharELECTRA forward (char text encoder)
        kochar_outputs = self.kochar(
            input_ids=char_input_ids,
            attention_mask=char_attention_mask,
        )
        char_repr = kochar_outputs.last_hidden_state  # [B, C, kochar_dim]

        # 4. Fusion: concat char_repr + visual_ctx → projection
        fused = torch.cat([char_repr, char_visual_ctx], dim=-1)  # [B, C, kochar+layoutxlm]
        fused = self.fusion(fused)  # [B, C, kochar_dim]

        # 5. BIO classification
        logits = self.classifier(fused)  # [B, C, num_labels]

        result = {"logits": logits}
        if labels is not None:
            if self.crf is not None:
                # CRF loss — sequence consistency 학습
                # mask: -100이 아닌 위치만 (special token/pad 제외)
                # CRF는 첫 step부터 mask=True여야 — char_attention_mask와 결합 X, 그냥 labels 기준
                mask = (labels != -100)
                # mask가 첫 step부터 False면 CRF가 죽음 — 첫 char (CLS) 보정
                # 우리 데이터: [CLS] + chars + [SEP] + pad. [CLS]가 -100이라 mask 0
                # → mask[:, 0] = True로 강제하고 labels[:, 0] = 0 (O)으로 placeholder
                mask = mask.clone()
                mask[:, 0] = True
                labels_safe = labels.clone()
                labels_safe[labels_safe == -100] = 0  # O placeholder
                loss = -self.crf(logits, labels_safe, mask=mask, reduction="mean")
            else:
                loss_fn = nn.CrossEntropyLoss(
                    weight=self.class_weights.to(logits.device),
                    ignore_index=-100,
                )
                loss = loss_fn(
                    logits.reshape(-1, self.config.num_labels),
                    labels.reshape(-1),
                )
            result["loss"] = loss
        else:
            # Inference: CRF Viterbi decode 또는 argmax
            if self.crf is not None:
                # char_attention_mask 기반 (1 = valid char)
                mask = char_attention_mask.bool() if char_attention_mask is not None else None
                if mask is None:
                    mask = torch.ones_like(logits[:, :, 0], dtype=torch.bool)
                mask = mask.clone()
                mask[:, 0] = True
                pred = self.crf.decode(logits, mask=mask)  # list of lists (variable length)
                result["predictions"] = pred
        return result


def count_params(model: nn.Module) -> tuple[int, int]:
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return total, trainable


if __name__ == "__main__":
    # 빠른 sanity check
    config = HybridConfig()
    model = HybridSentenceExtractor(config)
    total, trainable = count_params(model)
    print(f"Total params:     {total/1e6:.1f}M")
    print(f"Trainable params: {trainable/1e6:.1f}M ({100*trainable/total:.1f}%)")
    print(f"LayoutXLM frozen: {config.layoutxlm_frozen}")
    print(f"Architecture OK.")
