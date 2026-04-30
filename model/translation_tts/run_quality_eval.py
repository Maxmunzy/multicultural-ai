"""
NLLB 번역 품질 평가 — Gemini-as-Judge
용어사전 적용 전/후 정확도 비교

사용법:
    python run_quality_eval.py
    python run_quality_eval.py --lang vi en zh
"""
import argparse
import csv
import io
import json
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

from gemini_helper import GEMINI_API_KEY, GEMINI_MODEL, _get_client

GLOSSARY_CSV = Path(__file__).parent / "outputs" / "glossary_compare" / "glossary_compare.csv"
OUT_DIR = Path(__file__).parent / "outputs" / "quality_eval"

LANG_LABEL = {
    "vi": "베트남어", "en": "영어", "zh": "중국어",
    "th": "태국어", "ja": "일본어", "ru": "러시아어",
    "ms": "말레이시아어", "mn": "몽골어",
}

MAX_RETRIES = 3
CALL_DELAY = 3.0


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def call_gemini(prompt: str) -> str:
    client = _get_client()
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            return resp.text.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                m = re.search(r"retry in ([\d.]+)s", err)
                wait = float(m.group(1)) if m else CALL_DELAY * (attempt + 2)
                if wait > 90:
                    print(f"  일일 quota 소진 — 종료", flush=True)
                    return ""
                print(f"  429 — {wait:.0f}초 대기...", flush=True)
                time.sleep(wait)
            else:
                print(f"  API 오류: {err[:120]}", flush=True)
                time.sleep(CALL_DELAY)
    return ""


def parse_json_response(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
    m = re.search(r"\{[\s\S]+\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group())
    except Exception:
        return {}


def clamp_score(value, max_score: int = 95) -> int:
    try:
        score = int(round(float(value)))
    except Exception:
        return 0
    return max(0, min(score, max_score))


def evaluate_row(row: dict) -> dict | None:
    """NLLB 번역 전/후를 Gemini로 평가. preferred 없으면 None."""
    preferred = row["glossary_preferred"].strip()
    if not preferred:
        return None

    lang = row["lang"]
    lang_label = LANG_LABEL.get(lang, lang)
    sentence = row["sentence"]
    nllb_out = row["nllb_translation"]
    korean_term = row["korean_term"]

    prompt = f"""학교 가정통신문 번역 품질 평가입니다. 아래 내용을 바탕으로 JSON으로만 답하세요.

원문 (한국어): {sentence}
핵심 용어: "{korean_term}" → 올바른 {lang_label} 번역: "{preferred}"
NLLB 자동번역 ({lang_label}): {nllb_out}

평가 지시:
1. before_score: NLLB 자동번역이 얼마나 정확한지 0~100점.
2. after_translation: NLLB 자동번역을 완전히 새로 쓰지 말고, 핵심 용어 "{korean_term}" 관련 표현을 "{preferred}" 중심으로 최소 보정한 번역문.
3. after_score: "용어사전 보정만 적용된 번역"의 정확도 0~100점. NLLB의 다른 오류가 남아 있으면 반드시 감점.
4. reason: 전/후 점수 차이 이유 한 줄 (한국어로).

엄격한 채점 기준:
- 핵심 용어가 들어가도 현지에서 잘 안 쓰는 직역체, 어색한 조합, 학교 문맥에 맞지 않는 표현이면 80점 이하.
- 날짜, 금액, 시간, 제출/준비/참석 같은 행동 정보가 하나라도 빠지면 85점 이하.
- 문장이 중간에 끊기거나 의미가 불완전하면 60점 이하.
- after_translation은 "전체 재번역"이 아니라 "용어사전 기반 최소 보정"이어야 함.
- 핵심 용어만 고쳐지고 나머지 번역 오류가 남아 있으면 70~85점.
- 핵심 용어, 숫자/날짜/행동 정보, 자연스러운 현지 표현이 모두 맞을 때만 90점 이상.
- after_translation은 평가자가 만든 후보이므로 100점은 주지 말고, 거의 완벽해도 최대 95점.
- 90점 이상은 "실제 해당 언어권 학부모에게 바로 보내도 되는 수준"일 때만 부여.
- Round-trip 검사: after_translation을 다시 한국어로 의미 역번역했을 때 원문 핵심 용어/행동/숫자/날짜가 유지되는지 확인.
- 역번역 결과에 원문에 없는 행동/대상이 생기거나 핵심 정보가 사라지면 80점 이하.
- reason에는 반드시 현지 자연스러움/상용 표현 여부와 정보 보존 여부를 함께 언급.

JSON 형식:
{{"before_score": 숫자, "after_translation": "번역문", "after_back_translation_ko": "after_translation을 한국어로 의미 역번역한 내용", "roundtrip_issue": "역번역 기준 의미 누락/왜곡/환각", "after_score": 숫자, "reason": "이유"}}"""

    raw = call_gemini(prompt)
    if not raw:
        return None

    parsed = parse_json_response(raw)
    if not parsed:
        print(f"  [파싱 실패] {korean_term}/{lang}: {raw[:80]}", flush=True)
        return None

    return {
        "lang": lang,
        "lang_label": lang_label,
        "korean_term": korean_term,
        "sentence": sentence,
        "nllb_translation": nllb_out,
        "glossary_preferred": preferred,
        "before_score": clamp_score(parsed.get("before_score", 0), 100),
        "after_translation": parsed.get("after_translation", ""),
        "after_back_translation_ko": parsed.get("after_back_translation_ko", ""),
        "roundtrip_issue": parsed.get("roundtrip_issue", ""),
        "after_score": clamp_score(parsed.get("after_score", 0), 95),
        "reason": parsed.get("reason", ""),
    }


def save_results(results: list[dict]):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUT_DIR / "quality_eval.csv"
    fields = [
        "lang", "lang_label", "korean_term", "sentence",
        "nllb_translation", "glossary_preferred",
        "before_score", "after_translation", "after_back_translation_ko",
        "roundtrip_issue", "after_score", "reason",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    # 마크다운 요약
    md = [
        "# NLLB 번역 품질 평가 — 용어사전 전/후 비교",
        "",
        f"평가 모델: `{GEMINI_MODEL}`  |  번역 모델: `facebook/nllb-200-distilled-600M`",
        "",
        "## 언어별 평균 점수",
        "",
        "| 언어 | 전(NLLB) 평균 | 후(용어사전 적용) 평균 | 향상폭 |",
        "|---|---|---|---|",
    ]

    from itertools import groupby
    for lang, rows in groupby(results, key=lambda r: r["lang"]):
        rows = list(rows)
        avg_before = round(sum(r["before_score"] for r in rows) / len(rows), 1)
        avg_after = round(sum(r["after_score"] for r in rows) / len(rows), 1)
        delta = round(avg_after - avg_before, 1)
        label = rows[0]["lang_label"]
        md.append(f"| {lang} ({label}) | {avg_before}점 | {avg_after}점 | **+{delta}점** |")

    md += ["", "---", "", "## 용어별 상세 점수", ""]

    terms = list(dict.fromkeys(r["korean_term"] for r in results))
    for term in terms:
        term_rows = [r for r in results if r["korean_term"] == term]
        md += [
            f"### {term}",
            "",
        "| 언어 | NLLB 번역 | 전 점수 | 수정 번역 | 역번역 이슈 | 후 점수 | 이유 |",
        "|---|---|---|---|---|---|---|",
        ]
        for r in term_rows:
            nllb_short = r["nllb_translation"][:35] + "..." if len(r["nllb_translation"]) > 35 else r["nllb_translation"]
            after_short = r["after_translation"][:35] + "..." if len(r["after_translation"]) > 35 else r["after_translation"]
            md.append(
                f"| {r['lang']} ({r['lang_label']}) "
                f"| {nllb_short} | **{r['before_score']}점** "
                f"| {after_short} | {r['roundtrip_issue']} | **{r['after_score']}점** "
                f"| {r['reason']} |"
            )
        md.append("")

    md_path = OUT_DIR / "summary.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print(f"\n[저장 완료] {OUT_DIR}")
    print(f"  요약: {md_path}")
    print(f"  CSV:  {csv_path}")


def print_summary(results: list[dict]):
    print(f"\n{'='*60}")
    print("전체 요약 — 언어별 평균")
    print(f"{'='*60}")
    from itertools import groupby
    total_before, total_after, total_n = 0, 0, 0
    for lang, rows in groupby(results, key=lambda r: r["lang"]):
        rows = list(rows)
        avg_b = round(sum(r["before_score"] for r in rows) / len(rows), 1)
        avg_a = round(sum(r["after_score"] for r in rows) / len(rows), 1)
        label = rows[0]["lang_label"]
        print(f"  {lang:3} ({label:8}) | 전: {avg_b:5.1f}점 → 후: {avg_a:5.1f}점 | +{avg_a-avg_b:.1f}점")
        total_before += avg_b
        total_after += avg_a
        total_n += 1
    if total_n:
        print(f"\n  전체 평균 | 전: {total_before/total_n:.1f}점 → 후: {total_after/total_n:.1f}점 | +{(total_after-total_before)/total_n:.1f}점")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lang", nargs="+", default=list(LANG_LABEL.keys()),
                   choices=list(LANG_LABEL.keys()))
    return p.parse_args()


def main():
    args = parse_args()

    if not GEMINI_API_KEY:
        print("[오류] GEMINI_API_KEY 없음. .env 파일 확인하세요.")
        return

    if not GLOSSARY_CSV.exists():
        print(f"[오류] {GLOSSARY_CSV} 없음. run_glossary_compare.py 먼저 실행하세요.")
        return

    all_rows = load_csv(GLOSSARY_CSV)
    target_rows = [r for r in all_rows if r["lang"] in args.lang and r["glossary_preferred"].strip()]

    print(f"평가 대상: {len(target_rows)}건 (용어사전 등록 항목만)")
    print(f"언어: {', '.join(args.lang)}\n")

    results = []
    for i, row in enumerate(target_rows, 1):
        term = row["korean_term"]
        lang = row["lang"]
        print(f"[{i}/{len(target_rows)}] {term} / {lang} ...", end=" ", flush=True)
        r = evaluate_row(row)
        if r:
            results.append(r)
            print(f"전:{r['before_score']}점 → 후:{r['after_score']}점")
        else:
            print("스킵")
        time.sleep(CALL_DELAY)

    if not results:
        print("결과 없음.")
        return

    save_results(results)
    print_summary(results)


if __name__ == "__main__":
    main()
