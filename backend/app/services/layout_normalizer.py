"""LLM 기반 통신문 sentence 추출기 (Gemini API).

Google Gemini (gemini-2.5-flash 기본)를 호출해 윤정 모델 입력 전 sentence list를 추출.

방향: "정리"가 아니라 "추출".
- 학부모에게 필요한 sentence만 list로 뽑음 → 출력 토큰 1/3로 감소
- 표 행 / 일정 / 마감일 / 연락처 / 메타정보 각각 한 sentence로
- "절대 제거 금지" 항목 명시 (전화번호/URL/날짜/금액/학년·반/담당자)
- 출력 JSON 강제 (`responseMimeType=application/json` + `responseSchema`)

이전 Ollama(qwen2.5:3b) 트랙은 CPU에서 6분+ + mid-sentence 절단 + 정보 손실로 폐기.
Gemini는 동일 task에서 5~10초 응답 + 정확도 ↑.

기본값 활성 (analyze 요청 use_llm_normalizer=true가 기본).
실패/타임아웃/JSON 파싱 실패는 원본 텍스트로 fallback해 회귀 방지.
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
# Gemini Flash는 보통 5~10s. 통신문 길이 따라 변동. 60s safety.
GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "60"))


_EXTRACT_PROMPT = """당신은 한국 학교 가정통신문에서 학부모에게 필요한 정보를 sentence 단위로 추출하는 도우미입니다.

규칙:
- 각 sentence는 한 의미 단위 (학년별 준비물 한 행 / 일정 / 마감일 / 연락처 / 비용 / 메타정보 등)
- 표 행은 한 sentence로 변환: "1학년 준비물: 알림장, 클리어 화일, ..." 같은 헤더-값 형식
- 자간 공백 정상화는 **공백 제거만** ("학 년 도" → "학년도", "의 정 부 시" → "의정부시").
  글자 자체는 절대 바꾸지 말 것 ("빙그레" → "빈그레" 같은 한 글자 교정 금지)
- **고유명사는 원문 그대로 보존** — 학교명, 사람 이름, 영화관/시설명, 회사명, 지명, 행사명. 임의 교정/변환 금지
- **절대 제거 금지** — 전화번호, URL, 이메일, 날짜, 금액, 학년·반 표기, 담당자/발신자 정보, 학교명
- 메타데이터(담당부서, 작성일, 학교명)도 sentence list에 포함
- 의미 없는 단독 기호 줄(■, □, ※, 가로줄)만 제거
- 원문에 없는 정보 추가 금지, 요약·축약·시제 변경 금지

출력은 sentences 배열 한 필드만 갖는 JSON.

[입력]
{text}
"""


# Gemini가 JSON을 반환하도록 강제하는 스키마
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["sentences"],
}


def normalize_text(text: str) -> tuple[str, str, float]:
    """Gemini에 통신문을 보내 sentence list 추출. 실패 시 원본 그대로.

    Returns:
        (cleaned_text, status, elapsed_seconds)
        - cleaned_text: sentence list를 \\n으로 join한 텍스트 (실패 시 원본)
        - status: "ok" | "skip:empty" | "skip:no_key" | "skip:invalid_format" |
                  "skip:empty_sentences" | "skip:error:..."
        - elapsed_seconds: API 호출 시간 (실패 시 -1)
    """
    if not text or not text.strip():
        return text, "skip:empty", 0.0

    if not GEMINI_API_KEY:
        # 키 미설정 시 호출 자체 X — 회귀 방지 위해 원본 반환
        return text, "skip:no_key", 0.0

    prompt = _EXTRACT_PROMPT.format(text=text)
    # num_predict 동적 — 한국어 1글자 ≈ 1.5~2 토큰. 출력은 보통 입력의 60~80%.
    max_output_tokens = min(8192, max(512, int(len(text) * 1.0)))

    payload = json.dumps({
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
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
        # HTTP 4xx/5xx — 키 오류 / quota 초과 / 모델 이름 오타 등
        try:
            err_body = error.read().decode("utf-8")[:300]
        except Exception:
            err_body = ""
        logger.warning(
            "layout_normalizer Gemini HTTP %d after %.2fs: %s | %s",
            error.code, elapsed, error.reason, err_body,
        )
        return text, f"skip:error:HTTP{error.code}", -1
    except urllib.error.URLError as error:
        elapsed = time.monotonic() - started
        logger.warning("layout_normalizer Gemini URL error after %.2fs: %s", elapsed, error)
        return text, "skip:error:URLError", -1
    except TimeoutError as error:
        elapsed = time.monotonic() - started
        logger.warning("layout_normalizer Gemini timeout after %.2fs: %s", elapsed, error)
        return text, "skip:error:Timeout", -1
    except Exception as error:
        elapsed = time.monotonic() - started
        logger.warning("layout_normalizer Gemini failed after %.2fs: %s", elapsed, error)
        return text, f"skip:error:{type(error).__name__}", -1

    elapsed = time.monotonic() - started
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("layout_normalizer Gemini response decode failed (took %.2fs)", elapsed)
        return text, "skip:error:GeminiResponseDecode", elapsed

    # Gemini 응답: candidates[0].content.parts[0].text 안에 JSON string
    try:
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning(
                "layout_normalizer Gemini no candidates (took %.2fs, prompt_feedback=%r)",
                elapsed, data.get("promptFeedback"),
            )
            return text, "skip:no_candidates", elapsed
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            logger.warning("layout_normalizer Gemini no parts (took %.2fs)", elapsed)
            return text, "skip:no_parts", elapsed
        raw_out = (parts[0].get("text") or "").strip()
    except Exception as error:
        logger.warning(
            "layout_normalizer Gemini response shape unexpected (took %.2fs): %s",
            elapsed, error,
        )
        return text, "skip:error:ResponseShape", elapsed

    if not raw_out:
        return text, "skip:empty_response", elapsed

    try:
        parsed = json.loads(raw_out)
    except json.JSONDecodeError as error:
        logger.warning(
            "layout_normalizer JSON parse failed (took %.2fs, error=%s, head=%r)",
            elapsed, error, raw_out[:150],
        )
        return text, "skip:error:JSONParse", elapsed

    sentences = parsed.get("sentences")
    if not isinstance(sentences, list):
        logger.warning(
            "layout_normalizer 'sentences' not a list (took %.2fs, type=%s)",
            elapsed, type(sentences).__name__,
        )
        return text, "skip:invalid_format", elapsed

    cleaned_lines = [s.strip() for s in sentences if isinstance(s, str) and s.strip()]
    if not cleaned_lines:
        logger.warning("layout_normalizer empty sentences list (took %.2fs)", elapsed)
        return text, "skip:empty_sentences", elapsed

    cleaned = "\n".join(cleaned_lines)
    return cleaned, "ok", elapsed
