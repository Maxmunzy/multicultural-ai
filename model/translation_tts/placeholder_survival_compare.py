"""NLLB placeholder survival experiment for school-notice glossary terms.

Tests which placeholder token format NLLB passes through unchanged,
enabling reliable glossary restoration after translation.

Background:
    __SLOT0__ failed because M2M100 SentencePiece splits __ at word
    boundaries and drops sub-tokens under no_repeat_ngram_size.
    We need tokens NLLB treats as opaque codes/acronyms.

Run:
    python translation/placeholder_survival_compare.py
    python translation/placeholder_survival_compare.py --num-beams 4
    python translation/placeholder_survival_compare.py --device cuda

Output:
    outputs/glossary_placeholder_compare.csv
    outputs/glossary_placeholder_compare.md
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
HF_CACHE = ROOT / "models" / "huggingface"
os.environ.setdefault("HF_HOME", str(HF_CACHE))
os.environ.setdefault("TRANSFORMERS_CACHE", str(HF_CACHE / "hub"))

NLLB_MODEL = "facebook/nllb-200-distilled-600M"
NLLB_SRC = "kor_Hang"
NLLB_TGT = {"vi": "vie_Latn", "en": "eng_Latn"}

# ── Placeholder format candidates ─────────────────────────────────
# Each format provides tokens for slots 0/1/2 in a sentence.
# Format name → list of tokens (index = slot number)
PLACEHOLDER_FORMATS: dict[str, list[str]] = {
    "ITEMA/B/C":          ["ITEMA",        "ITEMB",        "ITEMC"],
    "AAAA/BBBB/CCCC":     ["AAAA",         "BBBB",         "CCCC"],
    "XITEMX/YITEMY/Z":    ["XITEMX",       "YITEMY",       "ZITEMZ"],
    "SUPPLYA/B/C":        ["SUPPLYA",       "SUPPLYB",      "SUPPLYC"],
    "MATERIALA/B/C":      ["MATERIALA",     "MATERIALB",    "MATERIALC"],
    "[ITEM_A]/[ITEM_B]":  ["[ITEM_A]",      "[ITEM_B]",     "[ITEM_C]"],
    "<ITEM_A>/<ITEM_B>":  ["<ITEM_A>",      "<ITEM_B>",     "<ITEM_C>"],
    "ITEM_A_TOKEN/...":   ["ITEM_A_TOKEN",  "ITEM_B_TOKEN", "ITEM_C_TOKEN"],
}

# ── Test samples ───────────────────────────────────────────────────
# (korean_text, [(ko_term, vi_term), ...])
SAMPLES: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "대회에 나가면 도화지와 색칠 도구를 준비해 주세요",
        [("도화지", "giấy vẽ"), ("색칠 도구", "đồ dùng tô màu")],
    ),
    (
        "유성매직과 사인펜을 준비해 주세요",
        [("유성매직", "bút dạ dầu"), ("사인펜", "bút lông")],
    ),
    (
        "풍선과 찰흙을 가져오세요",
        [("풍선", "bóng bay"), ("찰흙", "đất sét")],
    ),
    (
        "실내화와 물통을 챙겨 주세요",
        [("실내화", "giày trong nhà"), ("물통", "bình nước")],
    ),
    (
        "수채화 물감과 붓을 준비해 주세요",
        [("수채화 물감", "màu nước"), ("붓", "cọ vẽ")],
    ),
    (
        "전교생은 체육복과 실내화를 지참해 주세요",
        [("전교생", "toàn thể học sinh"), ("실내화", "giày trong nhà")],
    ),
    (
        "받아쓰기 공책과 클리어 화일을 제출해 주세요",
        [("받아쓰기 공책", "vở chính tả"), ("클리어 화일", "túi đựng tài liệu")],
    ),
    (
        "물감과 붓, 도화지를 담임선생님께 제출해 주세요",
        [("물감", "màu vẽ"), ("붓", "cọ vẽ"), ("도화지", "giấy vẽ")],
    ),
]


# ── Data structures ────────────────────────────────────────────────
@dataclass
class SampleResult:
    fmt_name: str
    sample_idx: int
    korean: str
    glossary: list[tuple[str, str]]
    masked_input: str
    nllb_output: str
    restored: str
    placeholders_used: list[str]
    placeholder_survived: list[bool]
    vi_terms_found: list[bool]
    elapsed: float
    failure_notes: list[str] = field(default_factory=list)

    @property
    def survival_rate(self) -> float:
        if not self.placeholders_used:
            return 0.0
        return sum(self.placeholder_survived) / len(self.placeholder_survived)

    @property
    def term_rate(self) -> float:
        if not self.vi_terms_found:
            return 0.0
        return sum(self.vi_terms_found) / len(self.vi_terms_found)


# ── Masking / restoration ──────────────────────────────────────────
def mask(text: str, glossary: list[tuple[str, str]], tokens: list[str]) -> tuple[str, list[str]]:
    """Replace Korean terms with placeholder tokens. Returns (masked, holders)."""
    result = text
    holders: list[str] = []
    for (ko, vi), token in zip(
        sorted(glossary, key=lambda x: -len(x[0])),
        tokens,
    ):
        if ko in result:
            result = result.replace(ko, token, 1)
            holders.append((token, vi))
    return result, holders


def restore(text: str, holders: list[tuple[str, str]]) -> str:
    for token, vi in holders:
        text = text.replace(token, vi)
    return text


# ── NLLB ──────────────────────────────────────────────────────────
def load_nllb(device: str):
    print(f"Loading {NLLB_MODEL} on {device} ...")
    tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL, src_lang=NLLB_SRC)
    model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL).to(device)
    model.eval()
    return tokenizer, model


def translate(text: str, tokenizer, model, device: str,
              target_lang: str, num_beams: int, rep_penalty: float, ngram: int) -> tuple[str, float]:
    tgt_id = tokenizer.convert_tokens_to_ids(NLLB_TGT[target_lang])
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=384).to(device)
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(
            **inputs,
            forced_bos_token_id=tgt_id,
            max_new_tokens=160,
            num_beams=num_beams,
            repetition_penalty=rep_penalty,
            no_repeat_ngram_size=ngram,
        )
    elapsed = time.perf_counter() - t0
    return tokenizer.batch_decode(out, skip_special_tokens=True)[0], elapsed


# ── Tokenizer inspection ───────────────────────────────────────────
def inspect_tokens(tokenizer, tokens: list[str]) -> dict[str, list[str]]:
    result = {}
    for token in tokens:
        ids = tokenizer(token, return_tensors="pt", add_special_tokens=False)["input_ids"][0]
        sub = [tokenizer.convert_ids_to_tokens([i.item()])[0] for i in ids]
        result[token] = sub
    return result


# ── Experiment ────────────────────────────────────────────────────
def run_format(
    fmt_name: str,
    token_pool: list[str],
    samples: list[tuple[str, list[tuple[str, str]]]],
    tokenizer,
    model,
    device: str,
    target_lang: str,
    num_beams: int,
    rep_penalty: float,
    ngram: int,
) -> list[SampleResult]:
    results = []
    for idx, (text, glossary) in enumerate(samples):
        tokens = token_pool[:len(glossary)]
        masked, holders = mask(text, glossary, tokens)
        nllb_out, elapsed = translate(masked, tokenizer, model, device,
                                       target_lang, num_beams, rep_penalty, ngram)
        restored = restore(nllb_out, holders)

        survived = [tok in nllb_out for tok, _ in holders]
        vi_terms = [vi.lower() in restored.lower() for _, vi in holders]

        notes = []
        for (tok, vi), s, v in zip(holders, survived, vi_terms):
            if not s:
                # Check partial survival
                partial = any(part in nllb_out for part in tok.split("_") if len(part) > 1)
                notes.append(f"'{tok}' {'partial' if partial else 'lost'} in NLLB output")
            elif not v:
                notes.append(f"'{vi}' not in restored (token survived but vi term missing)")

        results.append(SampleResult(
            fmt_name=fmt_name,
            sample_idx=idx,
            korean=text,
            glossary=glossary,
            masked_input=masked,
            nllb_output=nllb_out,
            restored=restored,
            placeholders_used=[tok for tok, _ in holders],
            placeholder_survived=survived,
            vi_terms_found=vi_terms,
            elapsed=elapsed,
            failure_notes=notes,
        ))
    return results


# ── Output ────────────────────────────────────────────────────────
def print_summary(all_results: dict[str, list[SampleResult]], token_info: dict):
    print("\n" + "=" * 72)
    print("Placeholder Survival Experiment — Summary")
    print("=" * 72)

    rows = []
    for fmt_name, results in all_results.items():
        survival = sum(r.survival_rate for r in results) / len(results) * 100
        term_rate = sum(r.term_rate for r in results) / len(results) * 100
        avg_t = sum(r.elapsed for r in results) / len(results)
        tokens = token_info.get(fmt_name, {})
        avg_subtoks = sum(len(v) for v in tokens.values()) / max(len(tokens), 1)
        rows.append((fmt_name, survival, term_rate, avg_t, avg_subtoks))

    rows.sort(key=lambda x: (-x[1], -x[2]))

    print(f"\n{'Format':<26} {'Survival%':>10} {'TermPres%':>10} {'AvgTime':>9} {'AvgSubTok':>10}")
    print("-" * 72)
    for fmt_name, survival, term_rate, avg_t, avg_sub in rows:
        best = " <-- BEST" if fmt_name == rows[0][0] else ""
        print(f"  {fmt_name:<24} {survival:>9.0f}% {term_rate:>9.0f}% {avg_t:>8.2f}s {avg_sub:>9.1f}{best}")

    print("\n-- Tokenizer sub-token counts --")
    for fmt_name, tokens in token_info.items():
        sub_counts = {k: len(v) for k, v in tokens.items()}
        print(f"  {fmt_name}: {sub_counts}")

    print("\n-- Failure patterns (worst cases) --")
    for fmt_name, results in all_results.items():
        fails = [r for r in results if r.failure_notes]
        if fails:
            print(f"\n  [{fmt_name}]")
            for r in fails[:3]:
                for note in r.failure_notes:
                    print(f"    sample{r.sample_idx+1}: {note}")


def write_csv(path: Path, all_results: dict[str, list[SampleResult]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "format", "sample_idx", "korean", "masked_input", "nllb_output",
        "restored", "placeholders", "survival_rate", "term_rate",
        "elapsed_sec", "failure_notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for fmt_name, results in all_results.items():
            for r in results:
                w.writerow({
                    "format": r.fmt_name,
                    "sample_idx": r.sample_idx + 1,
                    "korean": r.korean,
                    "masked_input": r.masked_input,
                    "nllb_output": r.nllb_output,
                    "restored": r.restored,
                    "placeholders": "|".join(r.placeholders_used),
                    "survival_rate": f"{r.survival_rate:.2f}",
                    "term_rate": f"{r.term_rate:.2f}",
                    "elapsed_sec": f"{r.elapsed:.3f}",
                    "failure_notes": "; ".join(r.failure_notes),
                })
    print(f"\nCSV saved: {path}")


def write_md(path: Path, all_results: dict[str, list[SampleResult]], token_info: dict, args):
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for fmt_name, results in all_results.items():
        survival = sum(r.survival_rate for r in results) / len(results) * 100
        term_rate = sum(r.term_rate for r in results) / len(results) * 100
        avg_t = sum(r.elapsed for r in results) / len(results)
        rows.append((fmt_name, survival, term_rate, avg_t))
    rows.sort(key=lambda x: (-x[1], -x[2]))
    best_fmt = rows[0][0]

    lines = [
        "# NLLB Placeholder Survival Experiment",
        "",
        f"**날짜**: 2026-05-06  ",
        f"**모델**: {NLLB_MODEL}  ",
        f"**설정**: num_beams={args.num_beams}, repetition_penalty={args.rep_penalty}, "
        f"no_repeat_ngram_size={args.ngram}  ",
        f"**샘플 수**: {len(SAMPLES)}개 문장 / {len(all_results)}개 형식",
        "",
        "## 결과 요약",
        "",
        "| Format | Placeholder 생존율 | 용어 보존율 | 평균속도 |",
        "|---|---|---|---|",
    ]
    for fmt_name, survival, term_rate, avg_t in rows:
        mark = " **<-- 최적**" if fmt_name == best_fmt else ""
        lines.append(f"| `{fmt_name}` | {survival:.0f}% | {term_rate:.0f}% | {avg_t:.2f}s |{mark}")

    lines += [
        "",
        "## Tokenizer Sub-token 분석",
        "",
        "| Format | Token | Sub-tokens | 개수 |",
        "|---|---|---|---|",
    ]
    for fmt_name, tokens in token_info.items():
        for tok, sub in tokens.items():
            lines.append(f"| `{fmt_name}` | `{tok}` | `{' '.join(sub)}` | {len(sub)} |")

    lines += [
        "",
        "## 샘플별 상세 결과 (Best format)",
        "",
    ]
    best_results = all_results.get(best_fmt, [])
    for r in best_results:
        survival_str = f"{sum(r.placeholder_survived)}/{len(r.placeholder_survived)}"
        term_str = f"{sum(r.vi_terms_found)}/{len(r.vi_terms_found)}"
        lines.append(f"**Sample {r.sample_idx+1}**: `{r.korean}`  ")
        lines.append(f"- 마스킹: `{r.masked_input}`  ")
        lines.append(f"- NLLB: `{r.nllb_output}`  ")
        lines.append(f"- 복원: `{r.restored}`  ")
        lines.append(f"- 생존: {survival_str} / 용어: {term_str}  ")
        if r.failure_notes:
            for note in r.failure_notes:
                lines.append(f"- 실패: {note}  ")
        lines.append("")

    lines += [
        "## 결론 및 권고",
        "",
        f"**최적 placeholder**: `{best_fmt}`  ",
        "",
        f"- Placeholder 생존율 {rows[0][1]:.0f}%, 용어 보존율 {rows[0][2]:.0f}%",
        "- 실패 패턴은 위 상세 결과 참조",
        "",
        "### 다음 단계",
        "- 최적 형식을 `run_mvp_pipeline.py` glossary injection에 적용",
        "- 서비스 적용 전 `backend/tests/test_translator_protection.py`에 회귀 테스트 추가",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"MD  saved: {path}")


# ── Main ──────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lang", default="vi", choices=list(NLLB_TGT))
    p.add_argument("--device", default="auto")
    p.add_argument("--num-beams", type=int, default=1)
    p.add_argument("--rep-penalty", type=float, default=1.3)
    p.add_argument("--ngram", type=int, default=3)
    return p.parse_args()


def main():
    args = parse_args()
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device

    tokenizer, model = load_nllb(device)

    # Tokenizer inspection — show how each format's tokens get split
    print("\n-- Tokenizer inspection --")
    token_info: dict[str, dict[str, list[str]]] = {}
    for fmt_name, token_pool in PLACEHOLDER_FORMATS.items():
        info = inspect_tokens(tokenizer, token_pool[:3])
        token_info[fmt_name] = info
        for tok, sub in info.items():
            print(f"  {tok:20} -> {sub}")

    print(f"\n-- Running {len(PLACEHOLDER_FORMATS)} formats × {len(SAMPLES)} samples --")
    print(f"   Settings: beams={args.num_beams} rep_penalty={args.rep_penalty} ngram={args.ngram}\n")

    all_results: dict[str, list[SampleResult]] = {}
    for fmt_name, token_pool in PLACEHOLDER_FORMATS.items():
        print(f"[{fmt_name}]")
        results = run_format(
            fmt_name, token_pool, SAMPLES,
            tokenizer, model, device, args.lang,
            args.num_beams, args.rep_penalty, args.ngram,
        )
        all_results[fmt_name] = results

        # Per-format quick stats
        surv = sum(r.survival_rate for r in results) / len(results) * 100
        term = sum(r.term_rate for r in results) / len(results) * 100
        avg_t = sum(r.elapsed for r in results) / len(results)
        print(f"  survival={surv:.0f}%  term_pres={term:.0f}%  avg={avg_t:.2f}s")

    print_summary(all_results, token_info)

    out_dir = ROOT / "outputs"
    write_csv(out_dir / "glossary_placeholder_compare.csv", all_results)
    write_md(out_dir / "glossary_placeholder_compare.md", all_results, token_info, args)


if __name__ == "__main__":
    main()
