"""
A/B 번역 품질 평가 — Gemini-as-Judge
run_ab_compare.py 결과(N*.md)를 읽어 A/B 번역 품질을 점수화

사용법:
    python run_ab_quality_eval.py
    python run_ab_quality_eval.py --lang vi --notices N01 N02 N08
"""
import argparse
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

AB_DIR = Path(__file__).parent / "outputs" / "ab_compare"
OUT_DIR = Path(__file__).parent / "outputs" / "ab_quality_eval"

MAX_RETRIES = 3
CALL_DELAY = 3.0


# ── 데이터 로딩 ────────────────────────────────────────────────

def load_from_json(lang: str) -> list[dict]:
    """run_ab_compare.py가 저장한 results.json 로딩."""
    json_path = AB_DIR / lang / "results.json"
    if not json_path.exists():
        return []
    return json.loads(json_path.read_text(encoding="utf-8"))


def parse_md(path: Path) -> dict | None:
    """N*.md 파일에서 A/B 입력·번역 추출 (fallback)."""
    text = path.read_text(encoding="utf-8")

    title_m = re.search(r"^# (\w+) — (.+)$", text, re.MULTILINE)
    if not title_m:
        return None
    notice_id = title_m.group(1)
    title = title_m.group(2).strip()

    blocks = re.findall(r"```\n([\s\S]+?)\n```", text)
    if len(blocks) < 4:
        return None

    return {
        "notice_id": notice_id,
        "title": title,
        "a_input": blocks[0].strip(),
        "a_translation": blocks[1].strip(),
        "b_input": blocks[2].strip(),
        "b_translation": blocks[3].strip(),
    }


def load_notices(lang: str, notice_filter: list[str] | None) -> list[dict]:
    # JSON 우선
    data = load_from_json(lang)
    if data:
        if notice_filter:
            data = [r for r in data if r["notice_id"] in notice_filter]
        return data

    # fallback: .md 파싱
    md_dir = AB_DIR / lang
    if not md_dir.exists():
        return []
    results = []
    for md_path in sorted(md_dir.glob("N*.md")):
        if notice_filter and md_path.stem not in notice_filter:
            continue
        r = parse_md(md_path)
        if r:
            results.append(r)
    return results


# ── Gemini 평가 ────────────────────────────────────────────────

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
                    print("  일일 quota 소진 — 종료")
                    return ""
                print(f"  429 — {wait:.0f}초 대기...")
                time.sleep(wait)
            else:
                print(f"  API 오류: {err[:120]}")
                time.sleep(CALL_DELAY)
    return ""


def parse_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
    m = re.search(r"\{[\s\S]+\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group())
    except Exception:
        return {}


def clamp_score(value) -> int:
    try:
        score = int(round(float(value)))
    except Exception:
        return 0
    return max(0, min(score, 100))


def evaluate_ab(notice: dict, lang_label: str) -> dict | None:
    a_in = notice.get("a_input", "")
    a_tr = notice.get("a_translation", "")
    b_in = notice.get("b_input", "")
    b_tr = notice.get("b_translation", "")

    if not a_tr or not b_tr:
        return None

    prompt = f"""학교 가정통신문 번역 품질을 평가합니다.

[A] 원문 전체 번역 ({lang_label})
입력: {a_in}
번역: {a_tr}

[B] 필수 행동(TODO)만 번역 ({lang_label})
입력: {b_in}
번역: {b_tr}

평가 기준:
- 의미 전달 정확도 (학부모가 해야 할 일을 파악할 수 있는가)
- 실제 {lang_label}권 학부모 안내문에서 자주 쓰이는 자연스러운 표현인가
- 학교/유치원 문맥의 상용어를 썼는가. 단어가 맞아도 현지에서 잘 안 쓰는 직역체면 감점
- 핵심 정보 누락 없음
- 날짜, 시간, 금액, 준비물, 제출처, 마감일, 주의사항 보존
- 번역문이 중간에 끊기지 않았는가
- Round-trip 검사: 번역문을 다시 한국어로 의미 역번역했을 때 원문 입력의 핵심 행동/숫자/날짜/준비물이 유지되는가

엄격한 채점 가이드:
- 핵심 행동을 알 수 없거나 문장이 잘리면 60점 이하.
- 날짜/시간/금액/준비물 중 중요한 정보가 하나라도 빠지면 75점 이하.
- 현지에서 어색한 직역체나 학교 문맥에 맞지 않는 단어가 반복되면 80점 이하.
- 의미 역번역 결과가 원문과 다르거나, 없는 행동/대상이 생기면 80점 이하.
- 90점 이상은 실제 해당 언어권 학부모에게 바로 보내도 되는 수준일 때만 부여.
- A/B가 서로 목적이 다름을 고려하되, B는 TODO 요약 목적상 "필수 행동 정보"가 남아있으면 좋은 평가를 받을 수 있음.

JSON으로만 답하세요:
{{
  "a_score": 숫자(0~100),
  "b_score": 숫자(0~100),
  "a_back_translation_ko": "A 번역문을 한국어로 의미 역번역한 내용",
  "b_back_translation_ko": "B 번역문을 한국어로 의미 역번역한 내용",
  "roundtrip_issues": "역번역 기준으로 확인한 의미 누락/왜곡/환각 한 줄 (한국어)",
  "a_issues": "A 번역의 주요 문제점 한 줄 (한국어)",
  "b_issues": "B 번역의 주요 문제점 한 줄 (한국어)",
  "verdict": "A와 B 중 학부모 전달 목적에 더 적합한 번역은? 이유 포함 (한국어 2~3문장)"
}}"""

    raw = call_gemini(prompt)
    if not raw:
        return None

    parsed = parse_json(raw)
    if not parsed:
        print(f"  [파싱 실패] {raw[:80]}")
        return None

    return {
        "notice_id": notice["notice_id"],
        "title": notice.get("title", ""),
        "a_chars": len(a_in),
        "b_chars": len(b_in),
        "a_score": clamp_score(parsed.get("a_score", 0)),
        "b_score": clamp_score(parsed.get("b_score", 0)),
        "a_back_translation_ko": parsed.get("a_back_translation_ko", ""),
        "b_back_translation_ko": parsed.get("b_back_translation_ko", ""),
        "roundtrip_issues": parsed.get("roundtrip_issues", ""),
        "a_issues": parsed.get("a_issues", ""),
        "b_issues": parsed.get("b_issues", ""),
        "verdict": parsed.get("verdict", ""),
        "a_input": a_in,
        "a_translation": a_tr,
        "b_input": b_in,
        "b_translation": b_tr,
    }


# ── 저장 ──────────────────────────────────────────────────────

def save_results(results: list[dict], lang: str):
    out_dir = OUT_DIR / lang
    out_dir.mkdir(parents=True, exist_ok=True)

    # 개별 .md 업데이트 (Gemini 평가 섹션 추가)
    for r in results:
        detail_path = out_dir / f"{r['notice_id']}.md"
        detail_path.write_text(
            f"# {r['notice_id']} — {r['title']}\n\n"
            f"## 요약\n\n"
            f"| 항목 | A (원문 전체) | B (TODO만) |\n"
            f"|---|---|---|\n"
            f"| 입력 글자수 | {r['a_chars']}자 | {r['b_chars']}자 |\n"
            f"| **Gemini 점수** | **{r['a_score']}점** | **{r['b_score']}점** |\n"
            f"| 주요 문제 | {r['a_issues']} | {r['b_issues']} |\n\n"
            f"**Round-trip 이슈:** {r['roundtrip_issues']}\n\n"
            f"**종합 평가:** {r['verdict']}\n\n"
            f"---\n\n"
            f"## A: 원문 전체 ({r['a_chars']}자)\n\n"
            f"**입력:**\n```\n{r['a_input']}\n```\n\n"
            f"**번역:**\n```\n{r['a_translation']}\n```\n\n"
            f"**한국어 역번역:**\n```\n{r['a_back_translation_ko']}\n```\n\n"
            f"## B: TODO만 ({r['b_chars']}자)\n\n"
            f"**입력:**\n```\n{r['b_input']}\n```\n\n"
            f"**번역:**\n```\n{r['b_translation']}\n```\n"
            f"**한국어 역번역:**\n```\n{r['b_back_translation_ko']}\n```\n",
            encoding="utf-8",
        )

    # 통합 summary
    avg_a = round(sum(r["a_score"] for r in results) / len(results), 1) if results else 0
    avg_b = round(sum(r["b_score"] for r in results) / len(results), 1) if results else 0

    md = [
        "# A/B 번역 품질 평가 결과",
        "",
        f"언어: {lang}  |  평가 모델: `{GEMINI_MODEL}`",
        "",
        f"**A 평균: {avg_a}점  |  B 평균: {avg_b}점  |  차이: {round(avg_b - avg_a, 1):+.1f}점**",
        "",
        "| 공지 | 제목 | A점수 | B점수 | 차이 | 판정 |",
        "|---|---|---|---|---|---|",
    ]

    for r in results:
        delta = r["b_score"] - r["a_score"]
        winner = "B 우세" if delta > 5 else ("A 우세" if delta < -5 else "동등")
        title_short = r["title"][:18] + ("..." if len(r["title"]) > 18 else "")
        md.append(
            f"| {r['notice_id']} | {title_short} "
            f"| {r['a_score']}점 | {r['b_score']}점 "
            f"| {delta:+d}점 | {winner} |"
        )

    md += ["", "---", "", "## 공지별 종합 평가", ""]
    for r in results:
        md += [f"### {r['notice_id']} — {r['title']}", "", r["verdict"], ""]

    summary_path = out_dir / "summary.md"
    summary_path.write_text("\n".join(md), encoding="utf-8")

    print(f"\n[저장 완료] {out_dir}")
    print(f"  요약: {summary_path}")
    print(f"  공지별 상세: {out_dir}/N*.md")


# ── 메인 ──────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lang", default="vi")
    p.add_argument("--notices", nargs="*", help="특정 공지만 (예: N01 N02). 없으면 전체")
    return p.parse_args()


def main():
    args = parse_args()

    if not GEMINI_API_KEY:
        print("[오류] GEMINI_API_KEY 없음. .env 파일 확인하세요.")
        return

    notices = load_notices(args.lang, args.notices)
    if not notices:
        print(f"[오류] {AB_DIR / args.lang} 에 데이터 없음. run_ab_compare.py 먼저 실행하세요.")
        return

    lang_labels = {
        "vi": "베트남어", "en": "영어", "zh": "중국어",
        "th": "태국어", "ja": "일본어", "ru": "러시아어",
        "ms": "말레이시아어", "mn": "몽골어",
    }
    lang_label = lang_labels.get(args.lang, args.lang)

    print(f"평가 대상: {len(notices)}개 공지  |  언어: {args.lang} ({lang_label})\n")

    results = []
    for i, notice in enumerate(notices, 1):
        nid = notice["notice_id"]
        title = notice.get("title", "")[:20]
        print(f"[{i}/{len(notices)}] {nid} {title} ...", end=" ", flush=True)
        r = evaluate_ab(notice, lang_label)
        if r:
            results.append(r)
            print(f"A:{r['a_score']}점 / B:{r['b_score']}점")
        else:
            print("스킵")
        time.sleep(CALL_DELAY)

    if not results:
        print("결과 없음.")
        return

    save_results(results, args.lang)

    avg_a = round(sum(r["a_score"] for r in results) / len(results), 1)
    avg_b = round(sum(r["b_score"] for r in results) / len(results), 1)
    print(f"\n[전체 평균] A: {avg_a}점 | B: {avg_b}점 | 차이: {avg_b - avg_a:+.1f}점")


if __name__ == "__main__":
    main()
