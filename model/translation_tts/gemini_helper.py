"""Gemini API를 이용한 glossary 신규 용어 번역 초안 생성."""

import json
import os
import re
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3-flash-preview"
BATCH_SIZE = 150  # 전체를 1번에 처리 (Gemini 컨텍스트 충분)
BATCH_DELAY = 5.0
MAX_RETRIES = 3

LANG_LABEL = {
    "en": "영어",
    "vi": "베트남어",
    "zh": "중국어(간체)",
    "th": "태국어",
    "ms": "말레이시아어",
    "mn": "몽골어",
    "ru": "러시아어",
    "ja": "일본어",
}


def _get_client():
    from google import genai
    return genai.Client(api_key=GEMINI_API_KEY)


def suggest_terms_batch(korean_terms: list[str], target_lang: str) -> dict[str, str]:
    """
    여러 용어를 한 번의 API 호출로 번역 요청.
    반환: {korean_term: suggested_translation}
    실패한 항목은 딕셔너리에서 누락됨.
    """
    if not GEMINI_API_KEY or not korean_terms:
        return {}

    lang_label = LANG_LABEL.get(target_lang, target_lang)
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(korean_terms))
    prompt = (
        f"한국 어린이집·유치원·초등학교 가정통신문을 {lang_label}를 모국어로 쓰는 학부모에게 전달하는 상황입니다.\n"
        f"아래 용어를 {lang_label}로 번역하세요.\n\n"
        f"반드시 지켜야 할 조건:\n"
        f"1. 어린이집·유치원·초등학교 학부모가 일상에서 자주 쓰는 친근하고 부드러운 표현을 사용하세요.\n"
        f"2. 뉴스·논문·교과서 같은 딱딱한 공식 표현은 피하세요.\n"
        f"3. 고유명사·앱 이름(키즈노트, 하이클래스, 스쿨뱅킹 등)과 통화 단위(원=won, ₩)는 번역하지 말고 그대로 쓰세요.\n"
        f"4. JSON 객체로만 답하세요. 코드블록·설명 없이.\n"
        f"5. 키는 반드시 원래 한국어 용어 그대로 사용하세요.\n\n"
        f"예시:\n"
        f'{{"앞치마": "tạp dề", "도화지": "giấy vẽ"}}\n\n'
        f"번역할 용어:\n{numbered}"
    )

    for attempt in range(MAX_RETRIES):
        try:
            client = _get_client()
            response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            text = response.text.strip()

            # 마크다운 코드블록 제거 후 JSON 추출
            text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
            match = re.search(r"\{[\s\S]+\}", text)
            if not match:
                return {}
            return json.loads(match.group())

        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                m = re.search(r"retry in ([\d.]+)s", err)
                wait = float(m.group(1)) if m else BATCH_DELAY * (attempt + 2)
                if wait > 90:
                    print(f"\n  일일 quota 소진 ({wait:.0f}s) — 자정 UTC(오전 9시 KST) 후 재시도", flush=True)
                    return {}
                print(f"\n  429 — {wait:.0f}초 대기...", flush=True)
                time.sleep(wait)
            elif "503" in err or "UNAVAILABLE" in err:
                time.sleep(BATCH_DELAY)
            else:
                print(f"\n  API 오류: {err[:200]}", flush=True)
                return {}

    return {}


def suggest_term(korean_term: str, target_lang: str, context: str = "") -> str | None:
    """단일 용어 번역 (파이프라인 missing_term 처리용). 실패 시 None."""
    result = suggest_terms_batch([korean_term], target_lang)
    return result.get(korean_term) or None


def suggest_missing_terms(
    missing_terms: list[dict], target_lang: str, easy_ko_text: str = ""
) -> list[dict]:
    """
    missing_term 목록에 대해 Gemini 초안을 추가해 반환한다.
    각 항목: {"korean_term": ..., "preferred_term": ..., "gemini_suggestion": ...}
    """
    if not missing_terms:
        return []

    korean_list = [item.get("korean_term", "") for item in missing_terms]
    suggestions = suggest_terms_batch(korean_list, target_lang)

    return [
        {**item, "gemini_suggestion": suggestions.get(item.get("korean_term", ""), "")}
        for item in missing_terms
    ]


def fill_glossary_column(
    korean_terms: list[str], target_lang: str, on_progress=None
) -> dict[str, str]:
    """
    144개 등 대량 용어를 BATCH_SIZE씩 나눠 번역.
    on_progress(done, total): 진행 콜백 (선택).
    반환: {korean_term: suggested_translation}
    """
    results = {}
    total = len(korean_terms)

    for i in range(0, total, BATCH_SIZE):
        batch = korean_terms[i:i + BATCH_SIZE]
        batch_result = suggest_terms_batch(batch, target_lang)
        results.update(batch_result)

        done = min(i + BATCH_SIZE, total)
        if on_progress:
            on_progress(done, total)

        if i + BATCH_SIZE < total:
            time.sleep(BATCH_DELAY)

    return results


def _find_sentence(text: str, term: str) -> str:
    if not term or not text:
        return ""
    for sentence in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", text):
        if term in sentence:
            return sentence.strip()
    return ""
