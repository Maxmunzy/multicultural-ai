"""
학교 가정통신문 코퍼스에서 신규 도메인 용어를 추출하고
Gemini API로 9개 언어 번역 초안을 생성해 term_glossary.csv에 추가할 후보를 출력합니다.

사용법:
    python scripts/expand_glossary.py \
        --corpus data/processed/todo_labeled_draft.jsonl \
        --glossary model/translation_tts/term_glossary.csv \
        --output model/translation_tts/glossary_candidates.csv \
        --top 80

결과 파일(glossary_candidates.csv)을 검수 후
term_glossary.csv에 복붙하면 됩니다.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter

import requests

# ── 설정 ──────────────────────────────────────────────────────────────
GEMINI_MODEL   = "gemini-1.5-flash"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)
BATCH_SIZE = 30   # 한 번 Gemini 호출에 보낼 단어 수
MIN_FREQ   = 3    # 최소 등장 횟수
MIN_LEN    = 2    # 최소 글자 수 (한글 기준)
MAX_LEN    = 10   # 최대 글자 수

# 걸러낼 일반 어미·조사·불용어 (형태소 분석기 없이 간단히 처리)
STOPWORDS = {
    "학부모", "학생", "안내", "합니다", "있습니다", "해주세요", "바랍니다",
    "위하여", "위해", "관련", "경우", "이후", "이상", "이하", "관하여",
    "통하여", "통해", "대하여", "대해", "따라", "따른", "있으며", "하며",
    "하여", "하고", "하는", "하기", "하여야", "해야", "됩니다", "됩니다",
    "것입니다", "것이며", "것으로", "것을", "것에", "것은", "것이",
    "주시기", "주시면", "주시길", "주십시오", "주세요", "드립니다",
    "알려드립니다", "알립니다", "감사합니다", "부탁드립니다",
    "선생님", "어린이", "자녀", "우리", "아이들", "여러분",
}


def load_existing_terms(glossary_path: str) -> set[str]:
    terms: set[str] = set()
    if not os.path.exists(glossary_path):
        return terms
    with open(glossary_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ko = row.get("korean", "").strip()
            if ko:
                terms.add(ko)
    return terms


def extract_texts(corpus_path: str) -> list[str]:
    texts: list[str] = []
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                text = obj.get("text", "") or obj.get("original_text", "")
                if text:
                    texts.append(text)
            except json.JSONDecodeError:
                continue
    return texts


def extract_candidates(texts: list[str], existing: set[str], top_n: int) -> list[str]:
    """연속 한글 시퀀스를 추출해 빈도 상위 후보를 반환."""
    pattern = re.compile(r"[가-힣]{%d,%d}" % (MIN_LEN, MAX_LEN))
    counter: Counter = Counter()
    for text in texts:
        for word in pattern.findall(text):
            if word not in STOPWORDS and word not in existing:
                counter[word] += 1

    candidates = [w for w, c in counter.most_common() if c >= MIN_FREQ]
    return candidates[:top_n]


def gemini_translate(terms: list[str], api_key: str) -> list[dict]:
    """Gemini에 단어 목록을 보내 9개 언어 번역을 받아온다."""
    term_list = "\n".join(f"- {t}" for t in terms)
    prompt = f"""다음은 한국 초등학교 가정통신문에서 추출한 도메인 특화 용어 목록입니다.
각 용어를 아래 9개 언어로 번역해 JSON 배열로 출력하세요.
번역은 학교·교육 맥락에서 자연스러운 표현을 사용하세요.

용어 목록:
{term_list}

출력 형식 (JSON 배열, 설명 없이 배열만):
[
  {{
    "korean": "용어",
    "vi": "베트남어",
    "en": "영어",
    "zh": "중국어",
    "th": "태국어",
    "ms": "말레이어",
    "mn": "몽골어",
    "ru": "러시아어",
    "ja": "일본어",
    "note": "한 줄 설명 (예: 준비물, 일정, 제출 등)"
  }}
]"""

    url = GEMINI_API_URL.format(model=GEMINI_MODEL, key=api_key)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()

    raw = resp.json()
    text = raw["candidates"][0]["content"]["parts"][0]["text"]

    # JSON 블록 추출
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        raise ValueError(f"JSON 파싱 실패:\n{text}")
    return json.loads(match.group())


def save_candidates(rows: list[dict], output_path: str) -> None:
    fieldnames = [
        "korean", "preferred_vi", "preferred_en", "preferred_zh",
        "preferred_th", "preferred_ms", "preferred_mn", "preferred_ru",
        "preferred_ja", "note",
    ]
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "korean":       row.get("korean", ""),
                "preferred_vi": row.get("vi", ""),
                "preferred_en": row.get("en", ""),
                "preferred_zh": row.get("zh", ""),
                "preferred_th": row.get("th", ""),
                "preferred_ms": row.get("ms", ""),
                "preferred_mn": row.get("mn", ""),
                "preferred_ru": row.get("ru", ""),
                "preferred_ja": row.get("ja", ""),
                "note":         row.get("note", ""),
            })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus",   default="data/processed/todo_labeled_draft.jsonl")
    parser.add_argument("--glossary", default="model/translation_tts/term_glossary.csv")
    parser.add_argument("--output",   default="model/translation_tts/glossary_candidates.csv")
    parser.add_argument("--top",      type=int, default=80)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not api_key:
        print("❌ GEMINI_API_KEY 환경변수가 없습니다. .env에 설정 후 실행하세요.", file=sys.stderr)
        sys.exit(1)

    print(f"📂 코퍼스 로드: {args.corpus}")
    texts = extract_texts(args.corpus)
    print(f"   → {len(texts):,}행")

    print(f"📖 기존 사전 로드: {args.glossary}")
    existing = load_existing_terms(args.glossary)
    print(f"   → 기존 {len(existing)}개 용어")

    print(f"🔍 신규 후보 추출 (상위 {args.top}개, 최소 등장 {MIN_FREQ}회)")
    candidates = extract_candidates(texts, existing, args.top)
    print(f"   → {len(candidates)}개 후보")

    if not candidates:
        print("후보 없음 — 완료")
        return

    all_rows: list[dict] = []
    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i : i + BATCH_SIZE]
        print(f"🤖 Gemini 번역 중... ({i+1}~{i+len(batch)}/{len(candidates)})")
        try:
            rows = gemini_translate(batch, api_key)
            all_rows.extend(rows)
        except Exception as e:
            print(f"   ⚠️ 배치 실패: {e}")
        if i + BATCH_SIZE < len(candidates):
            time.sleep(1)

    save_candidates(all_rows, args.output)
    print(f"\n✅ 완료: {args.output} ({len(all_rows)}개)")
    print("검수 후 term_glossary.csv에 복붙하세요.")


if __name__ == "__main__":
    main()
