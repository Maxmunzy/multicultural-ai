"""PointerDoc — End-to-end PDF page image → sentence_list with variant-zero guarantee.

DCGAN 철학 적용:
- DINOv2-with-registers-small (22M, FROZEN) — vision backbone
- Sentence queries (DETR 방식, learnable)
- Pointer decoder — output vocabulary = {row_0, ..., row_N} only → 변형 0 구조적 보장

학습 데이터:
- image: 페이지 PNG
- bboxes: 각 row의 [x0, y0, x1, y1] (normalized [0, 1])
- sentence_row_ids: 각 sentence의 row indices (multi-label per query)

추론:
- image + bboxes → (active queries, row pointers)
- 각 active query → row_ids → sentence text = " ".join(pdfplumber_rows[i])
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel


@dataclass
class PointerDocConfig:
    vision_model_id: str = "facebook/dinov2-small"  # without-registers (transformers 4.46 호환)
    vision_hidden_size: int = 384  # DINOv2-small
    text_model_id: str = "monologg/kocharelectra-small-discriminator"
    text_hidden_size: int = 256  # KoCharELECTRA-small
    text_max_length: int = 48  # per-row token max
    d_model: int = 256
    nhead: int = 8
    num_decoder_layers: int = 4
    dim_feedforward: int = 1024
    dropout: float = 0.1
    num_queries: int = 32  # 가정통신문 평균 sentence 수
    max_rows: int = 128
    bbox_pe_dim: int = 64  # bbox sinusoidal embedding dim per coordinate
    use_text: bool = True  # False 면 vision+bbox만 (A 변형)
    use_vision: bool = True  # False 면 text+bbox만 (B 변형)


def bbox_sinusoidal_pe(bbox: torch.Tensor, dim: int) -> torch.Tensor:
    """bbox [x0, y0, x1, y1] (normalized) → sinusoidal positional embedding.

    Args:
        bbox: (..., 4) in [0, 1]
        dim: total output dim (must be divisible by 8 — 4 coords × sin+cos)
    Returns:
        (..., dim)
    """
    assert dim % 8 == 0, "dim must be divisible by 8"
    dim_per_coord = dim // 4
    half = dim_per_coord // 2
    device = bbox.device
    div = torch.exp(torch.arange(half, device=device).float() * -(torch.log(torch.tensor(10000.0)) / half))
    # bbox shape (..., 4) → (..., 4, 1) * (half,) → (..., 4, half)
    angle = bbox.unsqueeze(-1) * div
    sin = torch.sin(angle)  # (..., 4, half)
    cos = torch.cos(angle)
    pe = torch.stack([sin, cos], dim=-1)  # (..., 4, half, 2)
    pe = pe.flatten(start_dim=-3)  # (..., 4 * half * 2) = (..., dim)
    return pe


class BboxEncoder(nn.Module):
    """bbox 좌표 → bbox feature. Sinusoidal PE + linear projection."""

    def __init__(self, d_model: int, pe_dim: int):
        super().__init__()
        self.pe_dim = pe_dim
        self.proj = nn.Linear(pe_dim, d_model)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, bboxes: torch.Tensor) -> torch.Tensor:
        """bboxes: (B, R, 4) → bbox features (B, R, d_model)."""
        pe = bbox_sinusoidal_pe(bboxes, self.pe_dim)
        x = self.proj(pe)
        return self.norm(x)


# Backward-compat alias
RowEncoder = BboxEncoder


class PointerDoc(nn.Module):
    """DINOv2 (frozen) + sentence queries + pointer-to-row decoder."""

    def __init__(self, cfg: PointerDocConfig | None = None):
        super().__init__()
        self.cfg = cfg or PointerDocConfig()
        c = self.cfg

        # ❶ Vision backbone (frozen) — DINOv2
        if c.use_vision:
            self.vision = AutoModel.from_pretrained(c.vision_model_id)
            for p in self.vision.parameters():
                p.requires_grad = False
            self.vision.eval()
            self.vision_proj = nn.Linear(c.vision_hidden_size, c.d_model)
        else:
            self.vision = None
            self.vision_proj = None

        # ❷ Text backbone (frozen) — KoCharELECTRA-small (Hangul char-level)
        if c.use_text:
            self.text_encoder = AutoModel.from_pretrained(c.text_model_id)
            for p in self.text_encoder.parameters():
                p.requires_grad = False
            self.text_encoder.eval()
            self.text_proj = nn.Linear(c.text_hidden_size, c.d_model)
        else:
            self.text_encoder = None
            self.text_proj = None

        # ❸ bbox encoder (학습됨)
        pe_total = max(64, (c.bbox_pe_dim // 8) * 8)
        self.bbox_encoder = BboxEncoder(c.d_model, pe_total)
        # alias for backward compatibility
        self.row_encoder = self.bbox_encoder

        # ❸ Sentence queries (learnable)
        self.query_embed = nn.Parameter(torch.randn(c.num_queries, c.d_model) * 0.02)

        # ❹ Cross-attention decoder
        decoder_layer = nn.TransformerDecoderLayer(
            d_model=c.d_model,
            nhead=c.nhead,
            dim_feedforward=c.dim_feedforward,
            dropout=c.dropout,
            batch_first=True,
            norm_first=True,
        )
        self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=c.num_decoder_layers)
        self.decoder_norm = nn.LayerNorm(c.d_model)

        # ❺ Heads
        self.pointer_head = nn.Linear(c.d_model, c.d_model)
        self.row_key_head = nn.Linear(c.d_model, c.d_model)
        self.activity_head = nn.Linear(c.d_model, 1)  # is this query an active sentence?

    @torch.no_grad()
    def encode_vision(self, pixel_values: torch.Tensor) -> torch.Tensor:
        """DINOv2 features. (B, 3, H, W) → (B, P, D_v)."""
        self.vision.eval()
        out = self.vision(pixel_values=pixel_values)
        return out.last_hidden_state

    @torch.no_grad()
    def encode_text(
        self,
        text_ids: torch.Tensor,         # (B, R, T)
        text_mask: torch.Tensor,        # (B, R, T) attention mask
        row_mask: torch.Tensor,         # (B, R) row valid mask
    ) -> torch.Tensor:
        """KoCharELECTRA forward per row → row text features (B, R, D_text)."""
        B, R, T = text_ids.shape
        flat_ids = text_ids.view(B * R, T)
        flat_mask = text_mask.view(B * R, T)

        # Replace empty-row tokens with [CLS]-only to avoid empty attention
        empty_rows = ~row_mask.view(B * R)
        if empty_rows.any():
            # Set [CLS]=2 (kocharelectra) and mask all-1 for those rows minimally
            flat_ids[empty_rows] = 0
            flat_mask[empty_rows] = 0
            flat_mask[empty_rows, 0] = 1  # at least one token

        self.text_encoder.eval()
        out = self.text_encoder(input_ids=flat_ids, attention_mask=flat_mask)
        hidden = out.last_hidden_state  # (B*R, T, D_text)
        # mean pool with mask
        mask_f = flat_mask.unsqueeze(-1).float()
        summed = (hidden * mask_f).sum(dim=1)
        denom = mask_f.sum(dim=1).clamp(min=1)
        pooled = summed / denom  # (B*R, D_text)
        return pooled.view(B, R, -1)  # (B, R, D_text)

    def forward(
        self,
        pixel_values: torch.Tensor | None,
        bboxes: torch.Tensor,
        row_mask: torch.Tensor,
        text_ids: torch.Tensor | None = None,
        text_mask: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            pixel_values: (B, 3, H, W) image, or None when use_vision=False
            bboxes: (B, R, 4) in [0, 1]
            row_mask: (B, R) bool — True = valid row
            text_ids: (B, R, T) per-row token ids, or None when use_text=False
            text_mask: (B, R, T) attention mask
        Returns:
            row_scores: (B, Q, R) logits per (query, row)
            is_active: (B, Q) logit per query
        """
        device = bboxes.device
        B = bboxes.size(0)

        # ── bbox feature (always) ──
        row_tok = self.bbox_encoder(bboxes)                # (B, R, D)

        # ── text feature (optional) ──
        if self.cfg.use_text:
            assert text_ids is not None and text_mask is not None, "use_text=True requires text_ids/text_mask"
            text_feat = self.encode_text(text_ids, text_mask, row_mask)  # (B, R, D_text)
            row_tok = row_tok + self.text_proj(text_feat)  # (B, R, D)

        # ── memory: vision tokens (optional) + row tokens ──
        if self.cfg.use_vision:
            assert pixel_values is not None, "use_vision=True requires pixel_values"
            vision_feat = self.encode_vision(pixel_values)         # (B, P, D_v)
            vision_tok = self.vision_proj(vision_feat)             # (B, P, D)
            P = vision_tok.size(1)
            memory = torch.cat([vision_tok, row_tok], dim=1)       # (B, P+R, D)
            vision_pad = torch.zeros(B, P, dtype=torch.bool, device=device)
            memory_pad = torch.cat([vision_pad, ~row_mask], dim=1) # (B, P+R)
        else:
            memory = row_tok
            memory_pad = ~row_mask

        # ── queries ──
        queries = self.query_embed.unsqueeze(0).expand(B, -1, -1)  # (B, Q, D)

        # ── decoder ──
        decoded = self.decoder(queries, memory, memory_key_padding_mask=memory_pad)
        decoded = self.decoder_norm(decoded)                       # (B, Q, D)

        # ── heads ──
        is_active = self.activity_head(decoded).squeeze(-1)        # (B, Q)
        q_proj = self.pointer_head(decoded)                        # (B, Q, D)
        r_proj = self.row_key_head(row_tok)                        # (B, R, D)
        row_scores = torch.einsum("bqd,brd->bqr", q_proj, r_proj)  # (B, Q, R)
        row_scores = row_scores.masked_fill(~row_mask.unsqueeze(1), -1e9)

        return {
            "row_scores": row_scores,
            "is_active": is_active,
        }

    @torch.no_grad()
    def predict(
        self,
        pixel_values: torch.Tensor | None,
        bboxes: torch.Tensor,
        row_mask: torch.Tensor,
        text_ids: torch.Tensor | None = None,
        text_mask: torch.Tensor | None = None,
        active_threshold: float = 0.5,
        row_threshold: float = 0.5,
    ) -> list[list[list[int]]]:
        """추론 — 각 PDF별로 active query 골라서 row_ids 리스트 출력.

        Returns:
            batch[b] = list of sentences. sentence = list of row indices.
        """
        out = self.forward(pixel_values, bboxes, row_mask, text_ids=text_ids, text_mask=text_mask)
        active_prob = torch.sigmoid(out["is_active"])
        row_prob = torch.sigmoid(out["row_scores"])

        results = []
        B = bboxes.size(0)
        for b in range(B):
            sentences = []
            for q in range(self.cfg.num_queries):
                if active_prob[b, q].item() < active_threshold:
                    continue
                row_ids = (row_prob[b, q] > row_threshold).nonzero(as_tuple=True)[0].tolist()
                if row_ids:
                    sentences.append(sorted(row_ids))
            results.append(sentences)
        return results


# ── Loss ──

def hungarian_match(pred_row_probs: torch.Tensor, gt_row_sets: list[list[int]]) -> list[tuple[int, int]]:
    """각 PDF별로 Hungarian matching: pred queries ↔ gt sentences.

    Args:
        pred_row_probs: (Q, R) sigmoid probabilities
        gt_row_sets: list of list[int] — ground truth row indices per sentence
    Returns:
        matches: list of (query_idx, gt_idx)
    """
    from scipy.optimize import linear_sum_assignment

    Q, R = pred_row_probs.shape
    G = len(gt_row_sets)
    if G == 0:
        return []

    # Cost matrix: BCE loss between pred and gt row mask
    cost = torch.zeros(Q, G)
    for g, row_set in enumerate(gt_row_sets):
        gt_mask = torch.zeros(R, device=pred_row_probs.device)
        for ri in row_set:
            if ri < R:
                gt_mask[ri] = 1.0
        # BCE = -[gt * log(p) + (1-gt) * log(1-p)] summed over rows
        eps = 1e-7
        p = pred_row_probs.clamp(eps, 1 - eps)
        bce_per_q = -(gt_mask * torch.log(p) + (1 - gt_mask) * torch.log(1 - p)).sum(dim=-1)  # (Q,)
        cost[:, g] = bce_per_q.cpu()

    row_ind, col_ind = linear_sum_assignment(cost.detach().numpy())
    return list(zip(row_ind.tolist(), col_ind.tolist()))


def pointerdoc_loss(
    out: dict[str, torch.Tensor],
    gt_row_sets_batch: list[list[list[int]]],
    row_mask: torch.Tensor,
    active_weight: float = 1.0,
    row_weight: float = 5.0,
) -> dict[str, torch.Tensor]:
    """배치 손실 — Hungarian match + BCE per (matched query, row) + activity BCE.

    Args:
        out: model forward output {row_scores: (B, Q, R), is_active: (B, Q)}
        gt_row_sets_batch: per-PDF list of row_id lists
        row_mask: (B, R) True = valid
    """
    device = out["row_scores"].device
    B, Q, R = out["row_scores"].shape
    row_probs = torch.sigmoid(out["row_scores"])

    activity_targets = torch.zeros(B, Q, device=device)
    row_targets = torch.zeros(B, Q, R, device=device)
    row_target_mask = torch.zeros(B, Q, R, device=device)  # only matched queries contribute

    for b in range(B):
        gt = gt_row_sets_batch[b]
        if not gt:
            continue
        matches = hungarian_match(row_probs[b].detach(), gt)
        for q_idx, g_idx in matches:
            activity_targets[b, q_idx] = 1.0
            for ri in gt[g_idx]:
                if ri < R:
                    row_targets[b, q_idx, ri] = 1.0
            row_target_mask[b, q_idx, :] = row_mask[b].float()

    activity_loss = F.binary_cross_entropy_with_logits(out["is_active"], activity_targets)

    # Row BCE only on matched queries × valid rows
    if row_target_mask.sum() > 0:
        row_loss_per_elem = F.binary_cross_entropy_with_logits(
            out["row_scores"], row_targets, reduction="none"
        )
        row_loss = (row_loss_per_elem * row_target_mask).sum() / row_target_mask.sum()
    else:
        row_loss = torch.tensor(0.0, device=device)

    total = active_weight * activity_loss + row_weight * row_loss
    return {
        "loss": total,
        "activity_loss": activity_loss,
        "row_loss": row_loss,
    }
