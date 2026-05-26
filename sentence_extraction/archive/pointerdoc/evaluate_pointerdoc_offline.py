"""PointerDoc 오프라인 평가 — Claude 호출 없이 학습 라벨로 직접 검증.

흐름:
1. pointerdoc_train.jsonl 로드 (Claude 라벨이 정답)
2. ipynb와 동일하게 random.seed(42) split → val_records 추출
3. 각 val record에 대해 PointerDoc 추론
4. 정답 sentence_row_ids vs 예측 row_ids set 비교 (IoU @ 0.5 threshold)
5. Sentence-level recall / precision / F1 출력

사용 (로컬 GPU 없으면 CPU 동작):
    python sentence_extraction/evaluate_pointerdoc_offline.py \\
        --checkpoint sentence_extraction/data/pointerdoc_best.pt \\
        --jsonl sentence_extraction/data/pointerdoc_train.jsonl \\
        --out sentence_extraction/data/eval_pointerdoc_offline.json
"""

from __future__ import annotations

import argparse
import io
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoTokenizer

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from pointerdoc_model import PointerDoc, PointerDocConfig


def iou(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def match_score(
    pred_sets: list[set[int]],
    gt_sets: list[set[int]],
    threshold: float = 0.5,
) -> tuple[float, float, float, list[float]]:
    """각 GT sentence에 대해 IoU 가장 큰 예측 찾아서 매칭 (1-to-1 아닌 best-match).

    Returns (recall, precision, f1, per_gt_best_iou).
    """
    if not gt_sets and not pred_sets:
        return 1.0, 1.0, 1.0, []
    if not gt_sets:
        return 1.0, 0.0, 0.0, []
    if not pred_sets:
        return 0.0, 1.0, 0.0, [0.0] * len(gt_sets)

    matched_gt = 0
    per_gt: list[float] = []
    used_pred = set()
    for gt in gt_sets:
        best_iou = 0.0
        best_pi = -1
        for pi, p in enumerate(pred_sets):
            if pi in used_pred:
                continue
            score = iou(gt, p)
            if score > best_iou:
                best_iou = score
                best_pi = pi
        per_gt.append(best_iou)
        if best_iou >= threshold and best_pi >= 0:
            matched_gt += 1
            used_pred.add(best_pi)

    recall = matched_gt / len(gt_sets)
    precision = matched_gt / len(pred_sets)
    f1 = 2 * recall * precision / max(recall + precision, 1e-9)
    return recall, precision, f1, per_gt


def resolve_image_path(rec: dict[str, Any], image_dir: Path) -> Path:
    """jsonl의 image_path가 Windows 형식이어도 image_dir에서 basename으로 찾기."""
    name = rec["image_path"].replace("\\", "/").rsplit("/", 1)[-1]
    return image_dir / name


def predict_one(
    rec: dict[str, Any],
    model: PointerDoc,
    processor,
    tokenizer,
    cfg: PointerDocConfig,
    device: str,
    image_dir: Path,
    active_threshold: float = 0.5,
    row_threshold: float = 0.5,
) -> list[set[int]]:
    """한 record의 predicted row_id sets 반환."""
    img_path = resolve_image_path(rec, image_dir)
    img = Image.open(img_path).convert("RGB")
    n = min(len(rec["bboxes"]), cfg.max_rows)

    pixel = processor(images=img, return_tensors="pt")["pixel_values"].to(device)

    bboxes_t = torch.zeros(1, cfg.max_rows, 4, device=device)
    bboxes_t[0, :n] = torch.tensor(rec["bboxes"][:n], dtype=torch.float32, device=device)

    mask_t = torch.zeros(1, cfg.max_rows, dtype=torch.bool, device=device)
    mask_t[0, :n] = True

    texts = rec["row_texts"][:n]
    tok = tokenizer(
        texts, padding="max_length", truncation=True,
        max_length=cfg.text_max_length, return_tensors="pt"
    )
    text_ids = torch.zeros(1, cfg.max_rows, cfg.text_max_length, dtype=torch.long, device=device)
    text_mask = torch.zeros(1, cfg.max_rows, cfg.text_max_length, dtype=torch.long, device=device)
    text_ids[0, :n] = tok["input_ids"].to(device)
    text_mask[0, :n] = tok["attention_mask"].to(device)

    preds = model.predict(
        pixel, bboxes_t, mask_t,
        text_ids=text_ids, text_mask=text_mask,
        active_threshold=active_threshold,
        row_threshold=row_threshold,
    )
    return [set(s) for s in preds[0]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--jsonl", required=True, type=Path)
    ap.add_argument("--image-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--active-threshold", type=float, default=0.5)
    ap.add_argument("--row-threshold", type=float, default=0.5)
    ap.add_argument("--iou-threshold", type=float, default=0.5)
    ap.add_argument("--val-fraction", type=float, default=0.1)
    ap.add_argument("--all", action="store_true", help="val split 무시하고 전체 평가")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    # Load checkpoint
    ckpt = torch.load(str(args.checkpoint), map_location=device, weights_only=False)
    cfg = PointerDocConfig(**ckpt["cfg"])
    model = PointerDoc(cfg).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    processor = AutoImageProcessor.from_pretrained(cfg.vision_model_id)
    tokenizer = AutoTokenizer.from_pretrained(cfg.text_model_id)
    print(f"Model loaded — vision={cfg.vision_model_id}, text={cfg.text_model_id}")
    print(f"  active_threshold={args.active_threshold}, row_threshold={args.row_threshold}")

    # Load + split (ipynb와 동일)
    records: list[dict[str, Any]] = []
    with open(args.jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not args.all:
        random.seed(42)
        random.shuffle(records)
        n_val = max(50, int(len(records) * args.val_fraction))
        val_records = records[:n_val]
        print(f"Val split: {len(val_records)} / total {len(records)}")
    else:
        val_records = records
        print(f"All records: {len(val_records)}")

    if args.limit:
        val_records = val_records[: args.limit]

    # Evaluate
    per_pdf: list[dict[str, Any]] = []
    recalls: list[float] = []
    precisions: list[float] = []
    f1s: list[float] = []
    all_per_gt_ious: list[float] = []

    t_total_start = time.time()
    for i, rec in enumerate(val_records, 1):
        try:
            pred_sets = predict_one(
                rec, model, processor, tokenizer, cfg, device, args.image_dir,
                active_threshold=args.active_threshold,
                row_threshold=args.row_threshold,
            )
        except Exception as e:
            print(f"  [{i}] FAILED {rec['pdf']}: {e}", file=sys.stderr)
            continue

        gt_sets = [set(s) for s in rec["sentence_row_ids"]]
        recall, precision, f1, per_gt = match_score(pred_sets, gt_sets, args.iou_threshold)

        recalls.append(recall)
        precisions.append(precision)
        f1s.append(f1)
        all_per_gt_ious.extend(per_gt)

        per_pdf.append({
            "pdf": rec["pdf"],
            "n_gt_sentences": len(gt_sets),
            "n_pred_sentences": len(pred_sets),
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "per_gt_best_iou": per_gt,
        })
        if i % 10 == 0 or i == len(val_records):
            print(f"  [{i}/{len(val_records)}] avg recall so far: {statistics.mean(recalls):.3f}")

    elapsed = time.time() - t_total_start

    # Summary
    print()
    print("=" * 60)
    print(f"Evaluated: {len(per_pdf)} PDFs in {elapsed:.1f}s ({elapsed/max(len(per_pdf),1):.2f}s/PDF)")
    if recalls:
        print(f"avg recall    (IoU>={args.iou_threshold}): {statistics.mean(recalls):.3f}")
        print(f"avg precision (IoU>={args.iou_threshold}): {statistics.mean(precisions):.3f}")
        print(f"avg F1                              : {statistics.mean(f1s):.3f}")
    if all_per_gt_ious:
        print()
        print("=== per-GT IoU distribution ===")
        buckets = [0.0, 0.3, 0.5, 0.7, 0.9, 1.01]
        labels = ["<0.3", "0.3-0.5", "0.5-0.7", "0.7-0.9", ">=0.9"]
        counts = [0] * len(labels)
        for v in all_per_gt_ious:
            for k in range(len(labels)):
                if buckets[k] <= v < buckets[k + 1]:
                    counts[k] += 1
                    break
        n = len(all_per_gt_ious)
        for lbl, c in zip(labels, counts):
            print(f"  {lbl:>9}: {c:>5} ({100*c/n:.1f}%)")
        print(f"  mean: {statistics.mean(all_per_gt_ious):.3f}, median: {statistics.median(all_per_gt_ious):.3f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "n_pdfs": len(per_pdf),
                "avg_recall": statistics.mean(recalls) if recalls else 0.0,
                "avg_precision": statistics.mean(precisions) if precisions else 0.0,
                "avg_f1": statistics.mean(f1s) if f1s else 0.0,
                "iou_threshold": args.iou_threshold,
                "active_threshold": args.active_threshold,
                "row_threshold": args.row_threshold,
            },
            "per_pdf": per_pdf,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
