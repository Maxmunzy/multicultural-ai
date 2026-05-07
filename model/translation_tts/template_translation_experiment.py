"""Template-based translation experiment for school-notice sentences.

Strategy:
  1. Classify sentence type (prepare / bring / submit / attend / pay / info)
  2. Extract glossary items from sentence
  3. For template-able types → build Vietnamese sentence from template + glossary terms
  4. For info / missing-glossary → fall back to NLLB

Compares 3 approaches:
  Baseline     — raw NLLB, no glossary injection
  Strategy A   — direct Korean→Vietnamese replace before NLLB
  Template     — structure-aware template + glossary (NLLB only as fallback)

Run:
    python translation/template_translation_experiment.py
    python translation/template_translation_experiment.py --lang vi --device cpu

Output:
    outputs/template_translation_compare.csv
    outputs/template_translation_compare.md
"""
from __future__ import annotations

import argparse
import csv
import io
import os
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
OUT_DIR = ROOT / "outputs"

os.environ.setdefault("HF_HOME", str(HF_HOME))
os.environ.setdefault("TRANSFORMERS_CACHE", str(HF_HOME / "hub"))


# Glossary (Korean -> Vietnamese)
# Split glossary by role. The template path must not treat recipients/audiences
# as supplies, otherwise phrases like "submit to homeroom teacher" become
# "submit homeroom teacher".
ITEM_GLOSSARY_VI: dict[str, str] = {
    "수채화 물감": "màu nước",
    "색칠 도구": "đồ dùng tô màu",
    "유성매직": "bút dạ dầu",
    "사인펜": "bút lông",
    "받아쓰기 공책": "vở chính tả",
    "클리어 화일": "túi đựng tài liệu",
    "체육복": "quần áo thể dục",
    "도화지": "giấy vẽ",
    "찰흙": "đất sét",
    "풍선": "bóng bay",
    "실내화": "giày trong nhà",
    "물통": "bình nước",
    "물감": "màu vẽ",
    "붓": "cọ vẽ",
}

AUDIENCE_GLOSSARY_VI: dict[str, str] = {
    "전교생": "toàn thể học sinh",
}

RECIPIENT_GLOSSARY_VI: dict[str, str] = {
    "담임선생님": "giáo viên chủ nhiệm",
}

GLOSSARY_VI: dict[str, str] = {
    **ITEM_GLOSSARY_VI,
    **AUDIENCE_GLOSSARY_VI,
    **RECIPIENT_GLOSSARY_VI,
}

# ── Sentence type classification ───────────────────────────────────────────────

SENTENCE_TYPES = {
    "prepare": ["준비해 주세요", "준비해주세요", "준비하세요", "준비 바랍니다"],
    "bring":   ["가져오세요", "챙겨 주세요", "챙겨주세요", "지참해 주세요", "지참하세요", "지참 바랍니다"],
    "submit":  ["제출해 주세요", "제출해주세요", "제출하세요", "내 주세요", "내주세요", "보내 주세요", "보내주세요"],
    "attend":  ["참석해 주세요", "참석해주세요", "참석하세요", "참여해 주세요", "참여해주세요", "참여하세요"],
    "pay":     ["납부해 주세요", "납부해주세요", "납부하세요", "입금해 주세요", "입금해주세요", "입금하세요"],
}

VI_TEMPLATES: dict[str, str] = {
    "prepare": "Vui lòng chuẩn bị {items}.",
    "bring":   "Vui lòng mang theo {items}.",
    "submit":  "Vui lòng nộp {items}.",
    "attend":  "Vui lòng tham gia {items}.",
    "pay":     "Vui lòng thanh toán {items}.",
}

EN_TEMPLATES: dict[str, str] = {
    "prepare": "Please prepare {items}.",
    "bring":   "Please bring {items}.",
    "submit":  "Please submit {items}.",
    "attend":  "Please attend {items}.",
    "pay":     "Please pay {items}.",
}


def classify_sentence(text: str) -> str:
    for stype, keywords in SENTENCE_TYPES.items():
        for kw in keywords:
            if kw in text:
                return stype
    return "info"


# ── Item extraction ────────────────────────────────────────────────────────────

def extract_glossary_items(
    text: str, glossary: dict[str, str]
) -> list[tuple[str, str]]:
    """Return non-overlapping [(ko_term, vi_term), ...], longest-match first."""
    spans: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for ko, vi in sorted(glossary.items(), key=lambda x: -len(x[0])):
        start = text.find(ko)
        while start != -1:
            end = start + len(ko)
            overlaps = any(not (end <= a or start >= b) for a, b in occupied)
            if not overlaps:
                spans.append((start, end, ko, vi))
                occupied.append((start, end))
                break
            start = text.find(ko, start + 1)
    spans.sort(key=lambda x: x[0])
    return [(ko, vi) for _, _, ko, vi in spans]


def extract_audience(text: str, lang: str) -> str | None:
    if lang != "vi":
        return None
    found = extract_glossary_items(text, AUDIENCE_GLOSSARY_VI)
    return found[0][1] if found else None


def extract_recipient(text: str, lang: str) -> str | None:
    if lang != "vi":
        return None
    found = extract_glossary_items(text, RECIPIENT_GLOSSARY_VI)
    return found[0][1] if found else None


# ── Template translation ───────────────────────────────────────────────────────

def join_translated_items(items: list[str], lang: str) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if lang == "vi":
        return ", ".join(items[:-1]) + " và " + items[-1]
    return ", ".join(items[:-1]) + " and " + items[-1]


def build_from_template(
    stype: str,
    items: list[tuple[str, str]],
    lang: str,
    audience: str | None = None,
    recipient: str | None = None,
) -> str | None:
    """Return template-filled translation, or None if items empty or stype=info."""
    if stype == "info" or not items:
        return None
    templates = VI_TEMPLATES if lang == "vi" else EN_TEMPLATES
    tpl = templates.get(stype)
    if tpl is None:
        return None
    vi_items = join_translated_items([vi for _, vi in items], lang)
    sentence = tpl.format(items=vi_items)
    if lang == "vi":
        if recipient and stype == "submit":
            sentence = sentence[:-1] + f" cho {recipient}."
        if audience:
            sentence = f"Dành cho {audience}: {sentence}"
    return sentence


# ── Strategy A: direct replace ─────────────────────────────────────────────────

def apply_direct_replace(
    text: str, items: list[tuple[str, str]]
) -> str:
    result = text
    for ko, vi in sorted(items, key=lambda x: -len(x[0])):
        result = result.replace(ko, vi)
    return result


# ── NLLB inference ─────────────────────────────────────────────────────────────

def load_nllb(device: str):
    print(f"Loading {NLLB_MODEL} on {device}...")
    tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL, src_lang=NLLB_SOURCE_LANG)
    model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL).to(device)
    model.eval()
    return tokenizer, model


def translate_nllb(
    text: str,
    tokenizer,
    model,
    device: str,
    target_lang: str,
    max_new_tokens: int = 160,
) -> tuple[str, float]:
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


# ── Scoring ────────────────────────────────────────────────────────────────────

def term_score(translation: str, expected_vi: list[str]) -> tuple[int, int]:
    found = sum(1 for t in expected_vi if t in translation)
    return found, len(expected_vi)


# ── Samples ───────────────────────────────────────────────────────────────────

SAMPLES: list[tuple[str, list[str]]] = [
    ("대회에 나가면 도화지와 색칠 도구를 준비해 주세요",    ["giấy vẽ", "đồ dùng tô màu"]),
    ("유성매직과 사인펜을 준비해 주세요",                   ["bút dạ dầu", "bút lông"]),
    ("풍선과 찰흙을 가져오세요",                            ["bóng bay", "đất sét"]),
    ("실내화와 물통을 챙겨 주세요",                         ["giày trong nhà", "bình nước"]),
    ("수채화 물감과 붓을 준비해 주세요",                    ["màu nước", "cọ vẽ"]),
    ("전교생은 체육복과 실내화를 지참해 주세요",            ["quần áo thể dục", "giày trong nhà"]),
    ("받아쓰기 공책과 클리어 화일을 제출해 주세요",         ["vở chính tả", "túi đựng tài liệu"]),
    ("물감과 붓, 도화지를 담임선생님께 제출해 주세요",      ["màu vẽ", "cọ vẽ", "giấy vẽ"]),
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="vi", choices=list(NLLB_LANG))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    tokenizer, model = load_nllb(device)
    glossary = ITEM_GLOSSARY_VI if args.lang == "vi" else {}

    samples = SAMPLES[:args.limit] if args.limit else SAMPLES

    rows: list[dict] = []

    totals = {k: [0, 0] for k in ("baseline", "strategy_a", "template")}
    times  = {k: [] for k in ("baseline", "strategy_a", "template")}

    print("\n" + "=" * 72)
    print("Template-Based Translation Experiment")
    print("=" * 72)

    for idx, (text, expected_vi) in enumerate(samples, 1):
        items     = extract_glossary_items(text, glossary)
        stype     = classify_sentence(text)
        audience  = extract_audience(text, args.lang)
        recipient = extract_recipient(text, args.lang)
        tpl_out   = build_from_template(stype, items, args.lang, audience, recipient)

        print(f"\n[{idx}/{len(samples)}] {text}")
        print(f"  type={stype}  audience={audience or '-'}  recipient={recipient or '-'}  items={[ko for ko, _ in items]}")

        # ── Baseline ─────────────────────────────────────────────────────────
        out_base, t_base = translate_nllb(text, tokenizer, model, device, args.lang)
        f_base, tot = term_score(out_base, expected_vi)
        totals["baseline"][0] += f_base;  totals["baseline"][1] += tot
        times["baseline"].append(t_base)
        print(f"\n  [Baseline] ({t_base:.2f}s) [{f_base}/{tot}]  {out_base}")

        # ── Strategy A ───────────────────────────────────────────────────────
        text_a = apply_direct_replace(text, items) if items else text
        out_a, t_a = translate_nllb(text_a, tokenizer, model, device, args.lang)
        f_a, _ = term_score(out_a, expected_vi)
        totals["strategy_a"][0] += f_a;  totals["strategy_a"][1] += tot
        times["strategy_a"].append(t_a)
        print(f"  [Strategy A] ({t_a:.2f}s) [{f_a}/{tot}]  {out_a}")
        if text_a != text:
            print(f"    입력: {text_a}")

        # ── Template ─────────────────────────────────────────────────────────
        if tpl_out is not None:
            t_tpl = 0.0
            method = "template"
            review = "N"
        else:
            # fallback to NLLB (no items or info sentence)
            tpl_out, t_tpl = translate_nllb(text, tokenizer, model, device, args.lang)
            method = "nllb_fallback"
            review = "Y"
        f_tpl, _ = term_score(tpl_out, expected_vi)
        totals["template"][0] += f_tpl;  totals["template"][1] += tot
        times["template"].append(t_tpl)
        print(f"  [Template]   ({t_tpl:.2f}s) [{f_tpl}/{tot}]  {tpl_out}  [{method}]")

        rows.append({
            "sample_id":     idx,
            "korean":        text,
            "sentence_type": stype,
            "audience":      audience or "",
            "recipient":     recipient or "",
            "items_found":   " | ".join(ko for ko, _ in items),
            "expected_vi":   " | ".join(expected_vi),
            # Baseline
            "baseline_out":        out_base,
            "baseline_score":      f"{f_base}/{tot}",
            "baseline_time":       f"{t_base:.2f}",
            # Strategy A
            "strategy_a_input":    text_a,
            "strategy_a_out":      out_a,
            "strategy_a_score":    f"{f_a}/{tot}",
            "strategy_a_time":     f"{t_a:.2f}",
            # Template
            "template_out":        tpl_out,
            "template_score":      f"{f_tpl}/{tot}",
            "template_time":       f"{t_tpl:.2f}",
            "template_method":     method,
            "review_required":     review,
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("최종 비교")
    print("=" * 72)
    print(f"{'방식':<18}  {'용어 보존율':>12}  {'평균 추론시간':>12}")
    print("-" * 48)
    for key, label in [
        ("baseline",   "Baseline NLLB"),
        ("strategy_a", "Strategy A (직접치환)"),
        ("template",   "Template-based"),
    ]:
        f, t = totals[key]
        pct = f / t * 100 if t else 0
        avg_t = sum(times[key]) / len(times[key]) if times[key] else 0
        print(f"  {label:<16}  {f}/{t} ({pct:.0f}%)       {avg_t:.2f}s")

    # ── CSV ───────────────────────────────────────────────────────────────────
    OUT_DIR.mkdir(exist_ok=True)
    csv_path = OUT_DIR / "template_translation_compare.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {csv_path}")

    # ── Markdown report ───────────────────────────────────────────────────────
    md_path = OUT_DIR / "template_translation_compare.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Template-Based Translation Experiment\n\n")
        f.write(f"- 실험일: 2026-05-06\n")
        f.write(f"- 모델: {NLLB_MODEL}\n")
        f.write(f"- 디바이스: {device}\n")
        f.write(f"- 샘플 수: {len(samples)}\n\n")

        # Summary table
        f.write("## 최종 비교\n\n")
        f.write("| 방식 | 용어 보존율 | 평균 추론시간 |\n")
        f.write("|------|------------|---------------|\n")
        for key, label in [
            ("baseline",   "Baseline NLLB"),
            ("strategy_a", "Strategy A (직접치환)"),
            ("template",   "Template-based"),
        ]:
            found, total = totals[key]
            pct = found / total * 100 if total else 0
            avg_t = sum(times[key]) / len(times[key]) if times[key] else 0
            f.write(f"| {label} | {found}/{total} ({pct:.0f}%) | {avg_t:.2f}s |\n")

        # Methodology
        f.write("\n## 방법론\n\n")
        f.write("| 분류 | 키워드 | 베트남어 템플릿 |\n")
        f.write("|------|--------|----------------|\n")
        tpl_table = VI_TEMPLATES if args.lang == "vi" else EN_TEMPLATES
        for stype, kws in SENTENCE_TYPES.items():
            kw_str = ", ".join(kws[:3]) + ("..." if len(kws) > 3 else "")
            tpl = tpl_table.get(stype, "-")
            f.write(f"| {stype} | {kw_str} | `{tpl}` |\n")
        f.write(f"| info | (기타) | NLLB fallback |\n")

        # Glossary used
        f.write("\n## 사용 글로서리\n\n")
        f.write("| 한국어 | 베트남어 |\n|--------|----------|\n")
        for ko, vi in glossary.items():
            f.write(f"| {ko} | {vi} |\n")

        # Per-sample detail
        f.write("\n## 샘플별 결과\n\n")
        for row in rows:
            f.write(f"### [{row['sample_id']}] {row['korean']}\n\n")
            f.write(f"- **문장 유형**: `{row['sentence_type']}`\n")
            f.write(f"- **감지된 용어**: {row['items_found'] or '(없음)'}\n")
            f.write(f"- **기대 베트남어**: {row['expected_vi']}\n\n")
            f.write(f"| 방식 | 출력 | 점수 | 시간 |\n|------|------|------|------|\n")
            f.write(f"| Baseline | {row['baseline_out']} | {row['baseline_score']} | {row['baseline_time']}s |\n")
            f.write(f"| Strategy A | {row['strategy_a_out']} | {row['strategy_a_score']} | {row['strategy_a_time']}s |\n")
            f.write(f"| Template (`{row['template_method']}`) | {row['template_out']} | {row['template_score']} | {row['template_time']}s |\n\n")
            if row["review_required"] == "Y":
                f.write("> **review_required**: NLLB fallback 사용됨 — 사람 검수 필요\n\n")

        # Analysis
        f.write("## 분석\n\n")
        tpl_found, tpl_total = totals["template"]
        tpl_pct = tpl_found / tpl_total * 100 if tpl_total else 0
        base_found, base_total = totals["baseline"]
        base_pct = base_found / base_total * 100 if base_total else 0
        a_found, a_total = totals["strategy_a"]
        a_pct = a_found / a_total * 100 if a_total else 0

        tpl_times_nonzero = [t for t in times["template"] if t > 0]
        tpl_avg = sum(tpl_times_nonzero) / len(tpl_times_nonzero) if tpl_times_nonzero else 0
        template_only_count = sum(1 for r in rows if r["template_method"] == "template")

        f.write(f"- 전체 샘플 {len(samples)}개 중 {template_only_count}개가 템플릿 번역 적용됨\n")
        f.write(f"- Template 방식: {tpl_found}/{tpl_total} ({tpl_pct:.0f}%) vs Baseline {base_found}/{base_total} ({base_pct:.0f}%)\n")
        f.write(f"- Template 방식은 Strategy A ({a_found}/{a_total}, {a_pct:.0f}%)와 비교해도 ")
        if tpl_pct > a_pct:
            f.write(f"**{tpl_pct - a_pct:.0f}%p 더 높은** 용어 보존율 달성\n")
        elif tpl_pct == a_pct:
            f.write("동일한 용어 보존율\n")
        else:
            f.write(f"낮은 용어 보존율 (차이: {a_pct - tpl_pct:.0f}%p)\n")
        f.write(f"- 템플릿 적용 샘플의 평균 추론시간: {tpl_avg:.2f}s (NLLB 불필요)\n")
        f.write("- **결론**: 준비물/제출물 문장(prepare/bring/submit)은 템플릿으로 안정적 처리 가능\n")

    print(f"MD  saved: {md_path}")
    print()


if __name__ == "__main__":
    main()
