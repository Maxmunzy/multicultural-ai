"""LLM(Gemini) 기반 통신문 sentence 추출기.

Google Gemini (gemini-2.5-flash 기본)에 통신문 텍스트를 보내 후속 모델(윤정/경이/
세종 슬롯) 입력용 **구조화된 sentence list**를 추출.

세종님 정의 contract (2026-05-07):
    {
      "document_title": "...",
      "sentence_list": [
        {
          "sentence_id": "s001",
          "text": "...",                      # 원문 기반, 요약/의역 금지
          "section": "...",                    # 프로그램명/섹션명
          "section_type": "program | application_info | contact | notice | footer | unknown",
          "role_hint": "target | content | application_period | event_datetime |
                        application_url | contact | result_announcement |
                        location | fee | supplies | submit | etc",
          "is_action_candidate": false,        # 모델 A todo 후보 여부
          "contains_slots": [],                # date/time/url/phone/amount/target/location
          "source_order": 1
        },
        ...
      ]
    }

목적:
- Gemini가 "최종 답변" 만들지 않음 (요약·번역 X)
- 후속 자체 모델(윤정 KoELECTRA / 경이 KcELECTRA / NLLB+vi 템플릿) 입력 정제만
- 신청기간 ↔ 운영일시 혼합, "대 상" 자간 오역, 날짜 fragment 번역 오류 차단

기본값 활성 (use_llm_normalizer=True). 실패/타임아웃/JSON 파싱 실패는
원본 텍스트로 fallback해 회귀 방지.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "60"))


# 세종님 contract 기반 프롬프트 — 후속 모델 입력용 sentence list 생성.
# Gemini는 정답을 만들지 않음 — 우리 파이프라인이 사용할 뼈대만.
_EXTRACT_PROMPT = """당신은 한국 학교 가정통신문에서 후속 자체 모델이 사용할 sentence list를 추출하는 도우미입니다.

목적: 최종 답변/요약/번역이 아니라, 후속 모델(추출/분류/번역) 입력용 구조화된 sentence list 생성

규칙 (반드시 지킬 것):
- **요약하지 말 것** — 원문 표현 가능한 그대로 유지
- **번역하지 말 것** — 한국어 그대로
- **날짜, 시간, 금액, URL, 전화번호는 원문 그대로 보존** — 형식 변환 금지
- **신청기간과 운영일시는 반드시 구분** — 같은 sentence에 섞지 말 것
- **프로그램이 여러 개면 section으로 분리** — 각 sentence의 section/section_type 명시
- **대상/내용/운영일시/신청기간/문의/URL/장소/비용/준비물/제출** 같은 의미는 role_hint로 태깅
- **원문에 없는 정보는 추측 금지**
- **고유명사 원문 그대로** — 학교명/지명/사람 이름/시설명/행사명 임의 변환 금지
- 자간 공백 정상화는 공백 제거만 ("학 년 도" → "학년도"), 글자 변경 X
- 의미 없는 단독 기호 줄(■, □, ※, 가로줄)만 제거

각 sentence 필드:
- sentence_id: "s001", "s002" 형식 순차 ID
- text: 원문 sentence
- section: 프로그램명/섹션명 (예: "토요영어체험교실", "신청 및 운영안내", "문의")
- section_type: program | application_info | contact | notice | footer | unknown
- role_hint: target | content | application_period | event_datetime | application_url | contact | result_announcement | location | fee | supplies | submit | etc
- is_action_candidate: 학부모 행동 필요 여부 (제출/신청/준비/납부 등) → true/false
- contains_slots: ["date", "time", "url", "phone", "amount", "target", "location"] 중 해당
- source_order: 원문 순서 (1부터)

document_title: 통신문 제목 (없으면 "")

출력은 다음 schema의 JSON만:
{{
  "document_title": "...",
  "sentence_list": [{{...}}, {{...}}, ...]
}}

[입력]
{text}
"""


# Gemini가 JSON 강제 출력하도록 schema 정의 (responseSchema)
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_title": {"type": "string"},
        "sentence_list": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence_id": {"type": "string"},
                    "text": {"type": "string"},
                    "section": {"type": "string"},
                    "section_type": {"type": "string"},
                    "role_hint": {"type": "string"},
                    "is_action_candidate": {"type": "boolean"},
                    "contains_slots": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "source_order": {"type": "integer"},
                },
                "required": ["sentence_id", "text", "source_order"],
            },
        },
    },
    "required": ["document_title", "sentence_list"],
}


def _empty_structured() -> dict:
    return {"document_title": "", "sentence_list": []}


def extract_sentences(text: str) -> tuple[dict, str, float]:
    """세종님 contract: {document_title, sentence_list[...]} 구조화 출력.

    실패 시 빈 contract({"document_title":"", "sentence_list":[]}) + status 반환.

    Returns:
        (structured, status, elapsed_seconds)
        - structured: dict (document_title + sentence_list)
        - status: "ok" | "skip:empty" | "skip:no_key" | "skip:invalid_format" |
                  "skip:empty_sentences" | "skip:error:..."
        - elapsed_seconds: API 호출 시간 (실패 시 -1)
    """
    if not text or not text.strip():
        return _empty_structured(), "skip:empty", 0.0

    if not GEMINI_API_KEY:
        return _empty_structured(), "skip:no_key", 0.0

    prompt = _EXTRACT_PROMPT.format(text=text)
    max_output_tokens = min(8192, max(1024, int(len(text) * 1.5)))

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }).encode("utf-8")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        elapsed = time.monotonic() - started
        try:
            err_body = error.read().decode("utf-8")[:300]
        except Exception:
            err_body = ""
        logger.warning(
            "extract_sentences Gemini HTTP %d after %.2fs: %s | %s",
            error.code, elapsed, error.reason, err_body,
        )
        return _empty_structured(), f"skip:error:HTTP{error.code}", -1
    except urllib.error.URLError as error:
        elapsed = time.monotonic() - started
        logger.warning("extract_sentences Gemini URL error after %.2fs: %s", elapsed, error)
        return _empty_structured(), "skip:error:URLError", -1
    except TimeoutError as error:
        elapsed = time.monotonic() - started
        logger.warning("extract_sentences Gemini timeout after %.2fs: %s", elapsed, error)
        return _empty_structured(), "skip:error:Timeout", -1
    except Exception as error:
        elapsed = time.monotonic() - started
        logger.warning("extract_sentences Gemini failed after %.2fs: %s", elapsed, error)
        return _empty_structured(), f"skip:error:{type(error).__name__}", -1

    elapsed = time.monotonic() - started
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("extract_sentences Gemini response decode failed (took %.2fs)", elapsed)
        return _empty_structured(), "skip:error:GeminiResponseDecode", elapsed

    try:
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning(
                "extract_sentences Gemini no candidates (took %.2fs, prompt_feedback=%r)",
                elapsed, data.get("promptFeedback"),
            )
            return _empty_structured(), "skip:no_candidates", elapsed
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            logger.warning("extract_sentences Gemini no parts (took %.2fs)", elapsed)
            return _empty_structured(), "skip:no_parts", elapsed
        raw_out = (parts[0].get("text") or "").strip()
    except Exception as error:
        logger.warning(
            "extract_sentences Gemini response shape unexpected (took %.2fs): %s",
            elapsed, error,
        )
        return _empty_structured(), "skip:error:ResponseShape", elapsed

    if not raw_out:
        return _empty_structured(), "skip:empty_response", elapsed

    try:
        parsed = json.loads(raw_out)
    except json.JSONDecodeError as error:
        logger.warning(
            "extract_sentences JSON parse failed (took %.2fs, error=%s, head=%r)",
            elapsed, error, raw_out[:150],
        )
        return _empty_structured(), "skip:error:JSONParse", elapsed

    if not isinstance(parsed, dict):
        return _empty_structured(), "skip:invalid_format", elapsed

    sentence_list = parsed.get("sentence_list")
    if not isinstance(sentence_list, list):
        logger.warning(
            "extract_sentences 'sentence_list' not a list (took %.2fs, type=%s)",
            elapsed, type(sentence_list).__name__,
        )
        return _empty_structured(), "skip:invalid_format", elapsed

    if not sentence_list:
        logger.warning("extract_sentences empty sentence_list (took %.2fs)", elapsed)
        return _empty_structured(), "skip:empty_sentences", elapsed

    # text 비어있는 항목은 제외 (정제). 다른 필드 누락은 그대로 통과(세종 adapter가 내성 처리).
    cleaned_list = [
        s for s in sentence_list
        if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip()
    ]
    if not cleaned_list:
        return _empty_structured(), "skip:empty_sentences", elapsed

    return (
        {
            "document_title": parsed.get("document_title", "") or "",
            "sentence_list": cleaned_list,
        },
        "ok",
        elapsed,
    )


def normalize_text(text: str) -> tuple[str, str, float]:
    """기존 호환 — extract_sentences 결과를 \\n joined string으로 변환.

    윤정 모델 입력으로 그대로 들어가는 흐름. 세종님 adapter는 extract_sentences 직접 사용.

    Returns:
        (cleaned_text, status, elapsed_seconds)
        - cleaned_text: sentence list의 text를 \\n으로 join. 실패 시 원본 텍스트.
        - status: extract_sentences와 동일
        - elapsed_seconds: extract_sentences와 동일
    """
    structured, status, elapsed = extract_sentences(text)
    if status != "ok":
        # 회귀 방지 — 실패 시 원본 텍스트 반환
        return text, status, elapsed
    cleaned = "\n".join(s["text"].strip() for s in structured["sentence_list"])
    if not cleaned:
        return text, "skip:empty_sentences", elapsed
    return cleaned, "ok", elapsed
