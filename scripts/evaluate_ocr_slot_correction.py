"""Evaluate OCR slot correction against a small CSV dataset.

This script is intentionally lightweight so field-test OCR text can be pasted
into a CSV during the morning test and scored immediately.

Input columns:
    case_id, source_type, slot_type, raw_ocr, ground_truth, note

Output:
    outputs/ocr_slot_correction_eval.csv
    outputs/ocr_slot_correction_eval.md
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.ocr_slot_corrector import apply_ocr_slot_corrections


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = cur
    return prev[-1]


def cer(pred: str, truth: str) -> float:
    if not truth:
        return 0.0 if not pred else 1.0
    return edit_distance(pred, truth) / len(truth)


def read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def evaluate(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        raw = row.get("raw_ocr", "")
        truth = row.get("ground_truth", "")
        corrected, changes = apply_ocr_slot_corrections(raw)
        raw_exact = raw == truth
        corrected_exact = corrected == truth
        raw_cer = cer(raw, truth)
        corrected_cer = cer(corrected, truth)
        review_required = any(c.get("review_required") for c in changes)

        out.append({
            "case_id": row.get("case_id", ""),
            "source_type": row.get("source_type", ""),
            "slot_type": row.get("slot_type", ""),
            "raw_ocr": raw,
            "corrected": corrected,
            "ground_truth": truth,
            "raw_exact": str(raw_exact),
            "corrected_exact": str(corrected_exact),
            "raw_cer": f"{raw_cer:.4f}",
            "corrected_cer": f"{corrected_cer:.4f}",
            "cer_delta": f"{raw_cer - corrected_cer:.4f}",
            "correction_count": str(len(changes)),
            "review_required": str(review_required),
            "corrections": " | ".join(
                f"{c['slot_type']}:{c['raw_text']}->{c['corrected_text']}"
                for c in changes
            ),
            "note": row.get("note", ""),
        })
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_md(path: Path, rows: list[dict], input_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(rows)
    raw_exact = sum(r["raw_exact"] == "True" for r in rows)
    corrected_exact = sum(r["corrected_exact"] == "True" for r in rows)
    raw_cer_avg = sum(float(r["raw_cer"]) for r in rows) / total if total else 0.0
    corrected_cer_avg = sum(float(r["corrected_cer"]) for r in rows) / total if total else 0.0
    changed = sum(int(r["correction_count"]) > 0 for r in rows)
    review = sum(r["review_required"] == "True" for r in rows)

    lines = [
        "# OCR Slot Correction Eval",
        "",
        f"- input: `{input_path}`",
        f"- cases: {total}",
        "",
        "## Summary",
        "",
        "| metric | raw OCR | corrected |",
        "|---|---:|---:|",
        f"| exact match | {raw_exact}/{total} ({raw_exact / total * 100:.0f}%) | {corrected_exact}/{total} ({corrected_exact / total * 100:.0f}%) |",
        f"| avg CER | {raw_cer_avg:.4f} | {corrected_cer_avg:.4f} |",
        "",
        f"- correction_applied: {changed}/{total}",
        f"- review_required: {review}/{total}",
        "",
        "## Cases",
        "",
        "| case | slot | raw | corrected | truth | pass | corrections |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        passed = "OK" if r["corrected_exact"] == "True" else "CHECK"
        lines.append(
            f"| {r['case_id']} | {r['slot_type']} | {r['raw_ocr']} | {r['corrected']} | "
            f"{r['ground_truth']} | {passed} | {r['corrections']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="data/ocr_slot_correction_eval_sample.csv",
        help="CSV with raw_ocr and ground_truth columns.",
    )
    parser.add_argument(
        "--output",
        default="outputs/ocr_slot_correction_eval.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--md",
        default="outputs/ocr_slot_correction_eval.md",
        help="Output Markdown report path.",
    )
    args = parser.parse_args()

    input_path = ROOT / args.input
    output_path = ROOT / args.output
    md_path = ROOT / args.md

    rows = evaluate(read_rows(input_path))
    write_csv(output_path, rows)
    write_md(md_path, rows, input_path)

    total = len(rows)
    corrected_exact = sum(r["corrected_exact"] == "True" for r in rows)
    raw_exact = sum(r["raw_exact"] == "True" for r in rows)
    print(f"OCR slot correction eval: raw={raw_exact}/{total}, corrected={corrected_exact}/{total}")
    print(f"CSV: {output_path}")
    print(f"MD : {md_path}")


if __name__ == "__main__":
    main()
