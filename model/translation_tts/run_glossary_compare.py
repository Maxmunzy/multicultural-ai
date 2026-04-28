"""
용어사전 전/후 번역 비교 스크립트
NLLB 원번역에 용어사전 권장어가 반영됐는지 검증

사용법:
    python run_glossary_compare.py --lang vi en zh th ja ru ms mn
"""
import argparse
import csv
import io
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from languages import LANGUAGES

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TRANSLATION_MODEL = "facebook/nllb-200-distilled-600M"
SOURCE_LANG = "kor_Hang"
GLOSSARY_PATH = Path(__file__).parent / "term_glossary.csv"

# 대표 학교 용어 8개 — 각 용어가 자연스럽게 포함된 문장
TERM_SENTENCES = [
    ("알림장",      "알림장을 매일 담임교사에게 제출해 주세요."),
    ("담임교사",    "담임교사에게 결석 사유를 알려 주세요."),
    ("방과후 신청서", "방과후 신청서를 이번 주 금요일까지 내 주세요."),
    ("수업비",      "수업비 40,000원을 다음 주까지 납부해 주세요."),
    ("체험학습",    "체험학습 신청서를 3일 전에 제출해 주세요."),
    ("결석계",      "결석계를 5일 이내에 담임교사에게 제출합니다."),
    ("준비물",      "내일 준비물은 색종이, 풀, 가위입니다."),
    ("공개수업",    "공개수업은 4월 23일 3교시에 실시됩니다."),
]


def load_glossary(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("korean", "").strip()]


def load_model(device: str):
    print(f"[모델 로딩] {TRANSLATION_MODEL} ({device}) ...")
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(TRANSLATION_MODEL, src_lang=SOURCE_LANG)
    model = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATION_MODEL).to(device)
    model.eval()
    print(f"[완료] {time.time() - t0:.1f}초\n")
    return tokenizer, model


def translate(text: str, tokenizer, model, device: str, nllb_code: str,
              max_input_tokens: int = 384, max_output_tokens: int = 512) -> str:
    target_id = tokenizer.convert_tokens_to_ids(nllb_code)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_input_tokens).to(device)
    with torch.no_grad():
        tokens = model.generate(
            **inputs,
            forced_bos_token_id=target_id,
            max_new_tokens=max_output_tokens,
            num_beams=4,
        )
    return tokenizer.batch_decode(tokens, skip_special_tokens=True)[0]


def run_lang(lang: str, glossary: list[dict], tokenizer, model, device: str) -> list[dict]:
    nllb_code = LANGUAGES[lang]["nllb_code"]
    label = LANGUAGES[lang]["label"]
    preferred_col = f"preferred_{lang}"

    # 용어사전에서 해당 언어 preferred 조회용 dict
    gloss_map = {r["korean"]: r.get(preferred_col, "").strip() for r in glossary}

    print(f"\n{'='*60}")
    print(f"[{lang}] {label}  |  NLLB: {nllb_code}")
    print("="*60)

    results = []
    for korean_term, sentence in TERM_SENTENCES:
        preferred = gloss_map.get(korean_term, "")
        nllb_out = translate(sentence, tokenizer, model, device, nllb_code)

        hit = preferred.lower() in nllb_out.lower() if preferred else False
        status = "✅ 반영" if hit else ("❌ 누락" if preferred else "—  미등록")

        print(f"\n  [{status}] {korean_term}")
        print(f"  원문: {sentence}")
        print(f"  NLLB: {nllb_out}")
        if preferred:
            print(f"  사전: {preferred}")

        results.append({
            "lang": lang,
            "label": label,
            "korean_term": korean_term,
            "sentence": sentence,
            "nllb_translation": nllb_out,
            "glossary_preferred": preferred,
            "reflected": "Y" if hit else "N",
            "status": status,
        })
    return results


def save_results(all_results: list[dict], langs: list[str]):
    out_dir = Path(__file__).parent / "outputs" / "glossary_compare"
    out_dir.mkdir(parents=True, exist_ok=True)

    # CSV
    csv_path = out_dir / "glossary_compare.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "lang", "label", "korean_term", "sentence",
            "nllb_translation", "glossary_preferred", "reflected", "status"
        ])
        writer.writeheader()
        writer.writerows(all_results)

    # 마크다운 요약
    md = ["# 용어사전 전/후 번역 비교", "", f"모델: `{TRANSLATION_MODEL}`  |  대상 언어: {', '.join(langs)}", ""]

    # 언어별 반영률 테이블
    md += ["## 언어별 반영률 요약", "", "| 언어 | 반영 | 누락 | 반영률 |", "|---|---|---|---|"]
    from itertools import groupby
    for lang, rows in groupby(all_results, key=lambda r: r["lang"]):
        rows = list(rows)
        reflected = sum(1 for r in rows if r["reflected"] == "Y")
        total = sum(1 for r in rows if r["glossary_preferred"])
        rate = f"{reflected/total*100:.0f}%" if total else "—"
        label = rows[0]["label"]
        md.append(f"| {lang} ({label}) | {reflected} | {total - reflected} | **{rate}** |")

    md += ["", "---", ""]

    # 용어별 상세 (vi 기준 before/after 강조)
    md += ["## 용어별 상세 비교", ""]
    terms = list(dict.fromkeys(r["korean_term"] for r in all_results))
    for term in terms:
        term_rows = [r for r in all_results if r["korean_term"] == term]
        md += [f"### {term}", "", "| 언어 | NLLB 원번역 | 용어사전 권장어 | 반영 |", "|---|---|---|---|"]
        for r in term_rows:
            md.append(
                f"| {r['lang']} ({r['label']}) | {r['nllb_translation'][:40]}... "
                f"| {r['glossary_preferred'] or '—'} | {r['status']} |"
            )
        md.append("")

    md_path = out_dir / "summary.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"\n[저장] {out_dir}")
    print(f"  요약: {md_path}")
    print(f"  CSV:  {csv_path}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lang", nargs="+", default=["vi"], choices=list(LANGUAGES.keys()))
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    return p.parse_args()


def main():
    args = parse_args()
    langs = [l for l in args.lang if LANGUAGES[l]["nllb_code"] is not None]
    if not langs:
        print("번역 가능한 언어 없음. ko_easy 제외 필요.")
        return

    device = args.device
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"

    glossary = load_glossary(GLOSSARY_PATH)
    print(f"용어사전: {len(glossary)}개 항목")

    tokenizer, model = load_model(device)

    all_results = []
    for lang in langs:
        all_results.extend(run_lang(lang, glossary, tokenizer, model, device))

    save_results(all_results, langs)

    # 전체 요약
    reflected = sum(1 for r in all_results if r["reflected"] == "Y")
    total = sum(1 for r in all_results if r["glossary_preferred"])
    print(f"\n[전체] 용어사전 반영률: {reflected}/{total} ({reflected/total*100:.0f}%)")


if __name__ == "__main__":
    main()
