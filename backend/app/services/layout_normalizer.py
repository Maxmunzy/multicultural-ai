"""LLM(Gemini) 기반 통신문 본문 정제기.

Google Gemini (gemini-2.5-flash 기본)에 통신문 텍스트/PDF/이미지를 보내 후속
자체 모델(윤정 KoELECTRA)이 받을 **정제된 paragraph 본문**을 추출.

2026-05-07 변경: Gemini systemInstruction 분리 + few-shot 강화.
- preview 모델(gemini-3-flash-preview)이 instruction following 약함
- systemInstruction 분리 + temperature 0 + 윤정 split 헷갈리는 패턴 명시 금지로
  preview 모델도 강제 따르게 만듦
- few-shot 3개로 우리 실제 통신문 패턴 명시

목적:
- Gemini 출력이 자체 PDF 파서(pdfplumber) raw 텍스트 형태로
- 윤정이 학습 데이터에서 본 적 없는 패턴 안 만들도록 명시 금지
- Vision 강점(자간 정상화, 표 풀어쓰기)만 추가

기본값 활성 (use_llm_normalizer=True). 실패/타임아웃/JSON 파싱 실패는
원본 텍스트로 fallback해 회귀 방지.
"""
from __future__ import annotations

import base64
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


# 모든 모드(Vision/text) 공통 — Gemini systemInstruction.
# user contents와 분리해서 instruction 강도 ↑ (Gemini API systemInstruction은
# 지속 규칙으로 더 강하게 적용됨). preview 모델도 강제 따르게 만들기 위함.
_SYSTEM_INSTRUCTION = """한국 학교 가정통신문을 자체 PDF 파서가 만들 raw 텍스트 형태로 정제. 후속 윤정 KoELECTRA 모델이 paragraph 안에서 todo 추출.

**규칙**:
1. 한 줄 = 한 sentence (헤더-값을 두 줄로 분리하지 말 것 — "준비물:\\n알림장" X. "준비물: 알림장" O)
2. 헤더는 콜론(:) — "신청방법은" X, "신청방법:" O
3. 한 sentence에 같은 헤더 키워드 두 번 금지 — "준비: ...개인 준비물 등입니다" X
4. 표 행은 헤더가 "준비물:"로 시작 + 학년/공용·개인 정보는 sentence 끝 괄호로
   (윤정 모델 학습 패턴 정합 — 학년 prefix는 sentence 시작이면 todo 인식 ↓)
   ✅ "준비물: 알림장, 클리어 화일, 유성매직, ... (1학년 공용)"
   ✅ "준비물: 줄 없는 종합장 1권, 천으로 된 필통, ... (1학년 가정)"
   ❌ "1학년 공용 준비물: 알림장, ..." — 학년 prefix 시작 금지
5. **특수기호 → 알파벳 변환** (윤정 모델 _clean_symbols 호환):
   ○ → O, ✕ → X, □ → [], ✓ → V, ☑ → [V]
   (다른 마크업 ■, ※, ▶ 등은 그대로 보존 — 윤정이 sentence boundary 신호로 사용)
6. 자간 공백 정상화 ("학 년 도" → "학년도", "의 정 부 시" → "의정부시")
7. 종결어미 강제 X. 요약·번역·축약 금지. 원문 그대로
8. 날짜/시간/금액/URL/전화번호/고유명사 원문 그대로

**출력**: {"document_title": "...", "cleaned_text": "..."} (paragraph 사이 \\n\\n, 같은 paragraph 내부 \\n)

**예시 1 — 학년별 학습준비물**:
{
  "document_title": "2026학년도 1분기 학습준비물 안내",
  "cleaned_text": "학부모님, 안녕하십니까?\\n본교에서는 학생들에게 학습준비물을 지원하고 있습니다.\\n\\n■ 운영 시기\\n1분기: 3월\\n2분기: 9월\\n\\n■ 학교 지원 공용 학습준비물\\n준비물: 알림장, 클리어 화일, 유성매직, 받아쓰기 공책, 색종이, 천사점토, 풍선 (1학년 공용)\\n준비물: 흰도화지, 색종이, 받아쓰기 공책, 아이클레이, 포스트잇 (2학년 공용)\\n\\n■ 가정 구매 개인 학습준비물\\n준비물: 줄 없는 종합장 1권, 천으로 된 필통, 샤프식 색연필 12색 (1학년 가정)\\n준비물: 알림장 1권, 줄공책 1권, 종합장 1권, 필통, 연필 (2학년 가정)\\n\\n※ 학급 안내에 따라 달라질 수 있습니다.\\n\\n문의: 031-877-0292\\n2026. 3. 10. 의정부서초등학교장"
}

**예시 2 — 체험학습 동의서 (○✕ 변환 케이스)**:
{
  "document_title": "2026 해조류박람회 체험학습 안내",
  "cleaned_text": "학부모님, 안녕하십니까?\\n\\n■ 일시: 2026년 5월 6일(목) 8:50~14:40\\n■ 장소: 해조류박람회 및 빙그레 시네마\\n■ 대상: 유치원생, 1-6학년 전교생\\n■ 준비물: 간편한 복장, 물, 기타 개인 용품\\n\\n※ 참가 동의서는 4월 28일(화)까지 담임선생님께 제출 바랍니다.\\n※ 참가 여부를 O,X로 표시하여 주시기 바랍니다.\\n\\n2026. 신지초등학교장"
}
"""


# Vision mode user prompt — 짧게. 모든 규칙은 systemInstruction에 있음.
_USER_PROMPT_VISION = "첨부된 한국 학교 가정통신문(PDF/이미지)을 systemInstruction의 형식·규칙·예시대로 분석해서 JSON 두 필드(document_title, cleaned_text)로 출력하세요."


# Text mode user prompt — 짧게. 본문은 [입력] 안에.
_USER_PROMPT_TEXT = """다음 가정통신문 텍스트를 systemInstruction의 형식·규칙·예시대로 정제해서 JSON 두 필드(document_title, cleaned_text)로 출력하세요.

[입력]
{text}"""


# Gemini Vision API가 inlineData로 직접 받을 수 있는 mime types.
# (HWP/HWPX는 직접 X — _save_original이 PDF로 변환해서 저장하므로 그 PDF를 보냄)
VISION_SUPPORTED_MIMES = frozenset({
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/heic",
    "image/heif",
})


# Gemini가 JSON 강제 출력하도록 schema 정의 (responseSchema).
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_title": {"type": "string"},
        "cleaned_text": {"type": "string"},
    },
    "required": ["document_title", "cleaned_text"],
}


def _empty_structured() -> dict:
    return {"document_title": "", "cleaned_text": ""}


def extract_sentences(
    text: str = "",
    inline_data: tuple[bytes, str] | None = None,
) -> tuple[dict, str, float]:
    """Gemini로 통신문 본문 정제 → {document_title, cleaned_text} 반환.

    함수 이름은 호환성 위해 그대로 유지. 내부적으론 sentence_list 분해 안 함.

    두 가지 모드:
    - **text 모드** (기본): text 인자 사용, inline_data=None.
    - **Vision 모드**: inline_data=(raw_bytes, mime_type) 전달. PDF/이미지 첨부.

    Gemini API의 systemInstruction을 사용해 지속 규칙을 분리 — preview 모델도
    강제 따르게 함. user contents는 짧게 (PDF 첨부 또는 텍스트 본문만).

    실패 시 빈 dict({"document_title":"", "cleaned_text":""}) + status 반환.

    Returns:
        (structured, status, elapsed_seconds)
        - structured: dict (document_title + cleaned_text)
        - status: "ok" | "skip:empty" | "skip:no_key" | "skip:unsupported_mime:..." |
                  "skip:invalid_format" | "skip:empty_text" | "skip:error:..."
        - elapsed_seconds: API 호출 시간 (실패 시 -1)
    """
    if not GEMINI_API_KEY:
        return _empty_structured(), "skip:no_key", 0.0

    if inline_data is not None:
        raw_bytes, mime_type = inline_data
        if not raw_bytes:
            return _empty_structured(), "skip:empty", 0.0
        if mime_type not in VISION_SUPPORTED_MIMES:
            logger.warning(
                "extract_sentences unsupported mime_type for Vision: %s", mime_type,
            )
            return _empty_structured(), f"skip:unsupported_mime:{mime_type}", 0.0
        encoded = base64.b64encode(raw_bytes).decode("utf-8")
        parts = [
            {"text": _USER_PROMPT_VISION},
            {"inlineData": {"mimeType": mime_type, "data": encoded}},
        ]
        # paragraph 정제 출력 cap — 통신문 길이 모름 + few-shot 영향으로 길어질 수 있어
        # 절단 방지 차원에서 32768. 짧은 통신문은 빠르게 끝남 (실제 출력 토큰만 과금).
        max_output_tokens = 32768
    else:
        if not text or not text.strip():
            return _empty_structured(), "skip:empty", 0.0
        parts = [{"text": _USER_PROMPT_TEXT.format(text=text)}]
        # 입력 길이 + 2배 cap. 절단 방지.
        max_output_tokens = min(32768, max(2048, int(len(text) * 2.0)))

    payload = json.dumps({
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
        "contents": [{"parts": parts}],
        "generationConfig": {
            # temperature 0 — 결정적 출력 (사실 추출이라 다양성 X 좋음)
            "temperature": 0.0,
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

    # 5xx (Gemini 일시 폭주) 또는 Timeout/URLError는 backoff 재시도.
    # 4xx (키 오류/quota 등)는 즉시 실패 — retry 무의미.
    backoffs = [0, 2, 5]  # 0=즉시, 2초, 5초 — 총 최대 3회 시도
    started = time.monotonic()
    body = None
    last_status = "skip:error:Unknown"
    last_attempt_log = ""
    for attempt, delay in enumerate(backoffs):
        if delay > 0:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode("utf-8")
            break  # 성공 → loop 빠져나옴
        except urllib.error.HTTPError as error:
            try:
                err_body = error.read().decode("utf-8")[:200]
            except Exception:
                err_body = ""
            last_attempt_log = f"HTTP {error.code}: {error.reason} | {err_body}"
            last_status = f"skip:error:HTTP{error.code}"
            if 400 <= error.code < 500:
                # 4xx는 retry 무의미 — 즉시 종료
                logger.warning(
                    "extract_sentences Gemini %s (no retry, attempt %d/%d)",
                    last_attempt_log, attempt + 1, len(backoffs),
                )
                elapsed = time.monotonic() - started
                return _empty_structured(), last_status, -1
            logger.warning(
                "extract_sentences Gemini %s (attempt %d/%d, retrying)",
                last_attempt_log, attempt + 1, len(backoffs),
            )
        except (urllib.error.URLError, TimeoutError) as error:
            last_attempt_log = f"{type(error).__name__}: {error}"
            last_status = "skip:error:URLError" if isinstance(error, urllib.error.URLError) else "skip:error:Timeout"
            logger.warning(
                "extract_sentences Gemini %s (attempt %d/%d, retrying)",
                last_attempt_log, attempt + 1, len(backoffs),
            )
        except Exception as error:
            last_attempt_log = f"{type(error).__name__}: {error}"
            last_status = f"skip:error:{type(error).__name__}"
            logger.warning(
                "extract_sentences Gemini %s (attempt %d/%d, no retry — unknown)",
                last_attempt_log, attempt + 1, len(backoffs),
            )
            elapsed = time.monotonic() - started
            return _empty_structured(), last_status, -1

    if body is None:
        # 모든 retry 실패
        elapsed = time.monotonic() - started
        logger.warning(
            "extract_sentences Gemini all %d retries failed after %.2fs: %s",
            len(backoffs), elapsed, last_attempt_log,
        )
        return _empty_structured(), last_status, -1

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

    cleaned_text = parsed.get("cleaned_text", "")
    if not isinstance(cleaned_text, str) or not cleaned_text.strip():
        logger.warning(
            "extract_sentences 'cleaned_text' empty/invalid (took %.2fs, type=%s)",
            elapsed, type(cleaned_text).__name__,
        )
        return _empty_structured(), "skip:empty_text", elapsed

    document_title = parsed.get("document_title", "") or ""

    # DEBUG (임시): Gemini가 만든 cleaned_text head/tail docker logs에 dump.
    # paragraph 정제 결과 확인용. 튜닝 끝나면 제거.
    head = cleaned_text[:300].replace("\n", " / ")
    tail = cleaned_text[-200:].replace("\n", " / ") if len(cleaned_text) > 300 else ""
    logger.warning(
        "extract_sentences DEBUG cleaned_text len=%d title=%r head=%r tail=%r",
        len(cleaned_text), document_title[:60], head, tail,
    )

    return (
        {"document_title": document_title, "cleaned_text": cleaned_text},
        "ok",
        elapsed,
    )


def normalize_text(text: str) -> tuple[str, str, float]:
    """기존 호환 — extract_sentences로 정제된 cleaned_text 반환.

    윤정 모델 입력으로 그대로 들어가는 흐름.

    Returns:
        (cleaned_text, status, elapsed_seconds)
        - cleaned_text: Gemini가 정제한 paragraph. 실패 시 원본 텍스트.
        - status: extract_sentences와 동일
        - elapsed_seconds: extract_sentences와 동일
    """
    structured, status, elapsed = extract_sentences(text)
    if status != "ok":
        # 회귀 방지 — 실패 시 원본 텍스트 반환
        return text, status, elapsed
    cleaned = structured.get("cleaned_text", "")
    if not cleaned:
        return text, "skip:empty_text", elapsed
    return cleaned, "ok", elapsed
