"""LLM(Gemini) 기반 통신문 본문 정제기.

Google Gemini (gemini-2.5-flash 기본)에 통신문 텍스트/PDF/이미지를 보내 후속
자체 모델(윤정 KoELECTRA)이 받을 **정제된 paragraph 본문**을 추출.

2026-05-07 변경: sentence_list 분해 → cleaned_text(paragraph) 전환.
- 이유: 윤정 KoELECTRA는 paragraph 흐름에 학습됨. sentence별 분해 후 \n join은
  학습 데이터에 없는 형태라 윤정의 sentence boundary 인식이 헷갈림 (잘림 발생).
- 자체 휴리스틱(text fallback) 시점은 원본 paragraph 그대로 윤정에 입력 →
  잘림 없이 cards 정상 추출.
- Gemini Vision의 정제 효과(자간 제거, 표 풀어쓰기, 노이즈 제거)는 살리되
  paragraph 흐름은 그대로 유지.

목적:
- Gemini가 "최종 답변" 만들지 않음 (요약·번역 X)
- 후속 윤정 모델이 받을 paragraph 본문만 정제
- 신청기간 ↔ 운영일시 혼합, "대 상" 자간 오역, 표 행 미분리 차단

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


# Text 모드 프롬프트 — 원본 텍스트가 input. paragraph 흐름 유지하며 정제만.
_EXTRACT_PROMPT = """다음 한국 학교 가정통신문 텍스트를 후속 자체 모델(윤정 KoELECTRA) 입력용으로 정제합니다.

**목적**: 원본 통신문의 paragraph 흐름과 문장 구조를 그대로 유지한 채 정제. 후속 모델이 자연스러운 paragraph 안에서 todo 추출.

**규칙** (절대 어기지 말 것):
- **paragraph 흐름 유지** — 원문의 자연스러운 줄과 단락 구조 그대로. sentence별 분해 X
- **자간 공백만 정상화** ("학 년 도" → "학년도", "의 정 부 시" → "의정부시"), 글자 변경 X
- **표 행은 한 줄에 자연 sentence로** 풀어쓰기 ("1학년 공용 준비물: 알림장, 클리어 화일, ...")
- **종결어미는 원문 흐름 그대로** ("입니다"/"바랍니다"/"주세요" 자연 사용)
- **의미 없는 단독 기호 줄(■, □, ※, 가로줄)만 제거**
- **요약·번역·축약 금지** — 원문 표현 그대로
- **날짜·시간·금액·URL·전화번호 원문 그대로 보존**
- **고유명사·학교명·지명 그대로**
- **원문에 없는 정보 추측·추가 금지**

출력 형식 — JSON 두 필드:
- document_title: 통신문 제목 (없으면 빈 문자열)
- cleaned_text: 정제된 통신문 본문 한 덩어리 (paragraph 사이 \\n\\n, 같은 paragraph 내부는 \\n)

[입력]
{text}
"""


# Vision 모드 프롬프트 — PDF/이미지가 첨부 input. 같은 정제 규칙.
_EXTRACT_PROMPT_VISION = """첨부된 한국 학교 가정통신문(PDF/이미지)을 후속 자체 모델(윤정 KoELECTRA) 입력용으로 정제합니다.

**목적**: 원본 통신문의 paragraph 흐름과 문장 구조를 그대로 유지한 채 정제. 후속 모델이 자연스러운 paragraph 안에서 todo 추출.

**규칙** (절대 어기지 말 것):
- **paragraph 흐름 유지** — 원문의 자연스러운 줄과 단락 구조 그대로. sentence별 분해 X
- **자간 공백만 정상화** ("학 년 도" → "학년도", "의 정 부 시" → "의정부시"), 글자 변경 X
- **표 행은 한 줄에 자연 sentence로** 풀어쓰기:
    "1학년 공용 준비물: 알림장, 클리어 화일, 유성매직, ..."
    "1학년 가정 준비물: 줄 없는 종합장 1권, 천으로 된 필통, ..."
    학년별 공용/개인 두 줄로 분리 (한 줄에 합치지 말 것)
- **종결어미는 원문 흐름 그대로** ("입니다"/"바랍니다"/"주세요" 자연 사용)
- **의미 없는 단독 기호 줄(■, □, ※, 가로줄)만 제거**
- **요약·번역·축약 금지** — 원문 표현 그대로
- **날짜·시간·금액·URL·전화번호 원문 그대로 보존**
- **고유명사·학교명·지명 그대로**
- **원문에 없는 정보 추측·추가 금지**

출력 형식 — JSON 두 필드:
- document_title: 통신문 제목 (없으면 빈 문자열)
- cleaned_text: 정제된 통신문 본문 한 덩어리 (paragraph 사이 \\n\\n, 같은 paragraph 내부는 \\n)

**예시 1 — 학년별 학습준비물 통신문**
{
  "document_title": "2026학년도 1분기 학습준비물 안내",
  "cleaned_text": "학부모님, 안녕하십니까?\\n본교에서는 학생들이 다양한 학습활동에 집중하며, 학부모님의 부담을 경감하고자 학생들에게 학습준비물을 지원하고 있습니다. 학습준비물 지원은 연간 총 2분기로 지원되며 이번 1분기에 지원되는 학습준비물은 아래와 같습니다.\\n\\n1분기 운영 시기: 3월\\n2분기 운영 시기: 9월\\n\\n학교에서 지원되는 공용 학습준비물\\n1학년 공용 준비물: 알림장, 클리어 화일, 유성매직, 받아쓰기 공책, 색종이, 천사점토, 풍선\\n2학년 공용 준비물: 흰도화지, 색종이, 받아쓰기 공책, 아이클레이, 포스트잇\\n3학년 공용 준비물: 마커, 유성 매직, 수채화 물감, 붓, 물통, 먹, A4 용지, 도화지\\n\\n가정에서 구매가 필요한 개인 학습준비물\\n1학년 가정 준비물: 줄 없는 종합장 1권, 천으로 된 필통, 샤프식 색연필 12색\\n2학년 가정 준비물: 알림장 1권, 줄공책 1권, 종합장 1권, 필통, 연필, 15cm 자\\n\\n학급 안내에 따라 개인학습준비물은 달라질 수 있습니다.\\n\\n문의: 031-877-0292\\n2026. 3. 10. 의정부서초등학교장"
}

**예시 2 — 현장체험학습 통신문**
{
  "document_title": "2026 해조류박람회 체험학습 안내",
  "cleaned_text": "학부모님, 안녕하십니까?\\n늘 건강하시고 웃음꽃이 피어나는 행복한 가정의 달 5월 맞이하시기를 기원합니다.\\n\\n일시: 2026년 5월 6일(목) 8:50~14:40\\n장소: 해조류박람회 및 빙그레 시네마\\n대상: 유치원생, 1-6학년 전교생\\n교통: 통학버스 2대\\n준비물: 간편한 복장, 물, 기타 개인 준비물\\n\\n참가 동의서는 4월 28일(화)까지 담임선생님께 제출 바랍니다. 당일 점심은 학교에서 제공되니 별도 도시락은 필요 없습니다.\\n\\n문의: 신지초등학교 강동재 교사"
}

첨부된 PDF/이미지 분석해서 위 두 필드 JSON으로만 출력.
"""


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
# 2026-05-07 변경: sentence_list → cleaned_text. 윤정 모델이 paragraph 흐름에
# 학습됐기에 sentence_list 분해보다 paragraph 정제가 친화적 (자체 휴리스틱
# 시점 형태와 동등). sentence_list metadata는 사용처 없어 제거.
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
    윤정 KoELECTRA가 paragraph 흐름에 학습됐기에 paragraph 그대로 입력하는 것이
    sentence별 분해 후 \\n join보다 친화적 (자체 휴리스틱 시점 형태와 동등).

    두 가지 모드:
    - **text 모드** (기본): text 인자 사용, inline_data=None. 프롬프트에 본문 포함.
    - **Vision 모드**: inline_data=(raw_bytes, mime_type) 전달. PDF/이미지가
      Gemini Vision에 직접 전송. text 인자는 무시. 표/자간 등 구조 자연 처리.

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
        # Vision 입력 토큰은 PDF 페이지/이미지 크기 따라 다름. 출력 cap은 보수적으로 32768.
        max_output_tokens = 32768
        encoded = base64.b64encode(raw_bytes).decode("utf-8")
        parts = [
            {"text": _EXTRACT_PROMPT_VISION},
            {"inlineData": {"mimeType": mime_type, "data": encoded}},
        ]
    else:
        if not text or not text.strip():
            return _empty_structured(), "skip:empty", 0.0
        prompt = _EXTRACT_PROMPT.format(text=text)
        # 출력은 입력의 1.5~2배 정도 (paragraph 정제). cap 32768로 절단 방지.
        max_output_tokens = min(32768, max(2048, int(len(text) * 2.0)))
        parts = [{"text": prompt}]

    payload = json.dumps({
        "contents": [{"parts": parts}],
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
