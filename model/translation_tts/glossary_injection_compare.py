"""Glossary injection strategy comparison.

Tests 3 injection approaches on school-notice samples:
  A. Direct replace  — swap Korean term with target-lang term before NLLB
  B. Prefix hint     — prepend "번역어: 도화지=giấy vẽ\n" to input
  C. Slot masking    — mask supply terms as __SLOTn__, restore after translation

Run:
    python translation/glossary_injection_compare.py
    python translation/glossary_injection_compare.py --lang vi --limit 8
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
HF_HOME = ROOT / "models" / "huggingface"
NLLB_MODEL = "facebook/nllb-200-distilled-600M"
NLLB_SOURCE_LANG = "kor_Hang"
NLLB_LANG = {"vi": "vie_Latn", "en": "eng_Latn"}

import os
os.environ.setdefault("HF_HOME", str(HF_HOME))
os.environ.setdefault("TRANSFORMERS_CACHE", str(HF_HOME / "hub"))

# ── Test samples ───────────────────────────────────────────────────
# (korean_text, [(korean_term, vi_term), ...], expected_vi_terms)
SAMPLES = [
    (
        "대회에 나가면 도화지와 색칠 도구를 준비해 주세요",
        [("도화지", "giấy vẽ"), ("색칠 도구", "đồ dùng tô màu")],
        ["giấy vẽ", "đồ dùng tô màu"],
    ),
    (
        "유성매직과 사인펜을 준비해 주세요",
        [("유성매직", "bút dạ dầu"), ("사인펜", "bút lông")],
        ["bút dạ dầu", "bút lông"],
    ),
    (
        "풍선과 찰흙을 가져오세요",
        [("풍선", "bóng bay"), ("찰흙", "đất sét")],
        ["bóng bay", "đất sét"],
    ),
    (
        "실내화와 물통을 챙겨 주세요",
        [("실내화", "giày trong nhà"), ("물통", "bình nước")],
        ["giày trong nhà", "bình nước"],
    ),
    (
        "수채화 물감과 붓을 준비해 주세요",
        [("수채화 물감", "màu nước"), ("붓", "cọ vẽ")],
        ["màu nước", "cọ vẽ"],
    ),
    (
        "전교생은 체육복과 실내화를 지참해 주세요",
        [("전교생", "toàn thể học sinh"), ("실내화", "giày trong nhà")],
        ["toàn thể học sinh", "giày trong nhà"],
    ),
    (
        "받아쓰기 공책과 클리어 화일을 제출해 주세요",
        [("받아쓰기 공책", "vở chính tả"), ("클리어 화일", "túi đựng tài liệu")],
        ["vở chính tả", "túi đựng tài liệu"],
    ),
    (
        "물감과 붓, 도화지를 담임선생님께 제출해 주세요",
        [("물감", "màu vẽ"), ("붓", "cọ vẽ"), ("도화지", "giấy vẽ")],
        ["màu vẽ", "cọ vẽ", "giấy vẽ"],
    ),
]


# ── Injection strategies ───────────────────────────────────────────

def strategy_a_direct_replace(text: str, glossary: list[tuple[str, str]]) -> str:
    """A: Replace Korean term directly with vi term before NLLB."""
    result = text
    for ko, vi in sorted(glossary, key=lambda x: -len(x[0])):
        result = result.replace(ko, vi)
    return result


def strategy_b_prefix(text: str, glossary: list[tuple[str, str]]) -> str:
    """B: Prepend vocabulary hint as 'vocab: ko=vi' lines."""
    if not glossary:
        return text
    hints = " | ".join(f"{ko}={vi}" for ko, vi in glossary)
    return f"vocab: {hints}\n{text}"


def strategy_c_slot(text: str, glossary: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """C: Mask supply terms as __SLOTn__, return (masked_text, holders)."""
    holders: list[str] = []
    result = text
    for ko, vi in sorted(glossary, key=lambda x: -len(x[0])):
        if ko in result:
            token = f"__SLOT{len(holders)}__"
            holders.append(vi)
            result = result.replace(ko, token, 1)
    return result, holders


def restore_slots(text: str, holders: list[str]) -> str:
    for i, val in enumerate(holders):
        text = text.replace(f"__SLOT{i}__", val)
    return text


# ── NLLB inference ────────────────────────────────────────────────

def load_nllb(device: str):
    print(f"Loading {NLLB_MODEL} on {device}...")
    tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL, src_lang=NLLB_SOURCE_LANG)
    model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL).to(device)
    model.eval()
    return tokenizer, model


def translate_nllb(text: str, tokenizer, model, device: str, target_lang: str,
                   max_new_tokens: int = 160) -> tuple[str, float]:
    target_id = tokenizer.convert_tokens_to_ids(NLLB_LANG[target_lang])
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=384).to(device)
    t0 = time.perf_counter()
    with torch.no_grad():
        tokens = model.generate(
            **inputs,
            forced_bos_token_id=target_id,
            max_new_tokens=max_new_tokens,
            num_beams=1,
            repetition_penalty=1.3,
            no_repeat_ngram_size=3,
        )
    elapsed = time.perf_counter() - t0
    return tokenizer.batch_decode(tokens, skip_special_tokens=True)[0], elapsed


# ── Evaluation ────────────────────────────────────────────────────

def score(translation: str, expected: list[str]) -> tuple[int, int]:
    found = sum(1 for t in expected if t in translation)
    return found, len(expected)


# ── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="vi", choices=list(NLLB_LANG))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device

    tokenizer, model = load_nllb(device)
    samples = SAMPLES[:args.limit] if args.limit else SAMPLES

    totals = {"A": [0, 0], "B": [0, 0], "C": [0, 0]}
    times = {"A": [], "B": [], "C": []}

    print("\n" + "=" * 70)
    print("Glossary Injection Strategy Comparison")
    print("=" * 70)

    for idx, (text, glossary, expected) in enumerate(samples, 1):
        print(f"\n[{idx}/{len(samples)}] {text}")
        print(f"  용어: {glossary}")
        print(f"  기대: {expected}")

        # ── A: Direct replace ──
        input_a = strategy_a_direct_replace(text, glossary)
        out_a, t_a = translate_nllb(input_a, tokenizer, model, device, args.lang)
        found_a, total = score(out_a, expected)
        totals["A"][0] += found_a
        totals["A"][1] += total
        times["A"].append(t_a)
        print(f"\n  A [직접치환] ({t_a:.2f}s) [{found_a}/{total}]")
        print(f"    입력: {input_a}")
        print(f"    출력: {out_a}")

        # ── B: Prefix hint ──
        input_b = strategy_b_prefix(text, glossary)
        out_b, t_b = translate_nllb(input_b, tokenizer, model, device, args.lang)
        found_b, _ = score(out_b, expected)
        totals["B"][0] += found_b
        totals["B"][1] += total
        times["B"].append(t_b)
        print(f"\n  B [프리픽스] ({t_b:.2f}s) [{found_b}/{total}]")
        print(f"    입력: {input_b[:80]}{'...' if len(input_b) > 80 else ''}")
        print(f"    출력: {out_b}")

        # ── C: Slot masking ──
        input_c, holders_c = strategy_c_slot(text, glossary)
        raw_c, t_c = translate_nllb(input_c, tokenizer, model, device, args.lang)
        out_c = restore_slots(raw_c, holders_c)
        # slot survival check
        slot_survived = all(f"__SLOT{i}__" in raw_c or holders_c[i] in raw_c
                            for i in range(len(holders_c)))
        found_c, _ = score(out_c, expected)
        totals["C"][0] += found_c
        totals["C"][1] += total
        times["C"].append(t_c)
        slot_flag = "" if slot_survived else " [SLOT LOSS]"
        print(f"\n  C [슬롯마스킹] ({t_c:.2f}s) [{found_c}/{total}]{slot_flag}")
        print(f"    마스킹: {input_c}")
        print(f"    NLLB출력: {raw_c}")
        print(f"    복원: {out_c}")

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("최종 비교")
    print("=" * 70)
    for name, label in [("A", "직접치환"), ("B", "프리픽스"), ("C", "슬롯마스킹")]:
        found, total = totals[name]
        avg_t = sum(times[name]) / len(times[name]) if times[name] else 0
        pct = found / total * 100 if total else 0
        print(f"  {name} [{label}]  용어 보존율: {found}/{total} ({pct:.0f}%)  평균: {avg_t:.2f}s")
    print()


if __name__ == "__main__":
    main()
