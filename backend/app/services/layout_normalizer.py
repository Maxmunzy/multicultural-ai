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
# paid tier 활성화된 GCP project ID. set 되면 X-Goog-User-Project 헤더에 실어
# 명시적 quota 부과 — API key가 default project로 흘러가는 케이스 방어.
GEMINI_QUOTA_PROJECT = os.environ.get("GEMINI_QUOTA_PROJECT", "")


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


# Vision 모드(inlineData로 PDF/이미지를 직접 전달)용 프롬프트.
# 텍스트 본문은 첨부 파일에 있으므로 [입력]/{text} placeholder 없음.
#
# **중요** — 이 프롬프트는 후속 자체 모델 (윤정 KoELECTRA / 경이 KcELECTRA / NLLB +
# card_builder) 입력 형식을 강제한다. 자체 모델이 sentence boundary를 종결어미로
# 인식하므로 Vision이 종결어미 없이 raw 추출하면 후속 흐름이 깨진다.
_EXTRACT_PROMPT_VISION = """당신은 한국 학교 가정통신문에서 후속 자체 모델이 사용할 sentence list를 추출하는 도우미입니다.

목적: 최종 답변/요약/번역이 아니라, 후속 모델(추출/분류/번역) 입력용 구조화된 sentence list 생성

**우리 sentence 형식 규칙 (절대 어기지 말 것)**:
1. **모든 sentence는 종결어미로 끝남** — "입니다" / "합니다" / "주세요" / "바랍니다" / "됩니다"
   (후속 모델이 sentence boundary 인식하려면 종결어미 필수)

2. **헤더-값 패턴은 콜론 형식**:
   - 통신문에 "대상: 초등 3학년" / "일시 2026.5.6" 같은 헤더-값 있으면
     → "{헤더}: {값}입니다." 형식 sentence로
   - 예: "대상: 초등학생 3·4학년 8명입니다.", "일시: 2026년 5월 6일(목) 8:50~14:40입니다."

3. **학년별 표 (1~6학년 행)는 각 행을 별도 sentence로**:
   - 형식: "{N}학년 준비물: 알림장, 클리어 화일, ... 입니다."
   - 또는 "{N}학년 가정 준비물: 줄 없는 종합장 1권, 천으로 된 필통, ... 입니다."
   - 학년이 두 종류(공용/개인)로 나뉘면 prefix에 명시 ("{N}학년 공용 준비물:", "{N}학년 개인 준비물:")

4. **표 셀이 헤더 행 + 데이터 행이면**, 데이터 행마다 한 sentence:
   - "{날짜}: {내용}, {시간}, {장소}입니다."
   - 또는 "{날짜} {내용}을(를) {시간} {장소}에서 진행합니다."

다른 절대 규칙:
- **요약/번역 금지** — 원문 표현 그대로
- **날짜, 시간, 금액, URL, 전화번호는 원문 그대로 보존** — 형식 변환·교정 금지
- **신청기간과 운영일시는 반드시 구분** — 같은 sentence에 섞지 말 것
- **프로그램이 여러 개면 section으로 분리** — 각 sentence의 section/section_type 명시
- **고유명사 원문 그대로** — 학교명/지명/사람 이름/시설명/행사명 임의 변환 금지 ("빙그레" → "빙그레")
- **자간 공백만 제거** ("학 년 도" → "학년도", "의 정 부 시" → "의정부시"), 글자 변경 X
- **원문에 없는 정보 추측 금지**
- 의미 없는 단독 기호 줄(■, □, ※, 가로줄)만 제거

각 sentence 필드:
- sentence_id: "s001", "s002" 형식 순차 ID
- text: 위 규칙대로 변환된 sentence (종결어미 + 헤더-값 콜론 형식)
- section: 프로그램명/섹션명 (예: "토요영어체험교실", "신청 및 운영안내", "문의")
- section_type: program | application_info | contact | notice | footer | unknown
- role_hint: target | content | application_period | event_datetime | application_url | contact | result_announcement | location | fee | supplies | submit | etc
- is_action_candidate: 학부모 행동 필요 여부 (제출/신청/준비/납부 등) → true/false
- contains_slots: ["date", "time", "url", "phone", "amount", "target", "location"] 중 해당
- source_order: 원문 순서 (1부터)

document_title: 통신문 제목 (없으면 "")

첨부된 가정통신문(PDF 또는 이미지)을 분석해서 위 contract의 JSON으로만 출력하세요.
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


def extract_sentences(
    text: str = "",
    inline_data: tuple[bytes, str] | None = None,
) -> tuple[dict, str, float]:
    """세종님 contract: {document_title, sentence_list[...]} 구조화 출력.

    두 가지 모드:
    - **text 모드** (기본): text 인자 사용, inline_data=None. 프롬프트에 본문 포함.
    - **Vision 모드**: inline_data=(raw_bytes, mime_type) 전달. PDF/이미지가
      Gemini Vision에 직접 전송. text 인자는 무시. 표/자간 등 구조 자연 처리.

    실패 시 빈 contract({"document_title":"", "sentence_list":[]}) + status 반환.

    Returns:
        (structured, status, elapsed_seconds)
        - structured: dict (document_title + sentence_list)
        - status: "ok" | "skip:empty" | "skip:no_key" | "skip:unsupported_mime:..." |
                  "skip:invalid_format" | "skip:empty_sentences" | "skip:error:..."
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
        # 출력은 입력의 2~3배까지 늘어남. cap 32768로 절단 방지.
        max_output_tokens = min(32768, max(2048, int(len(text) * 3.0)))
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
    if GEMINI_QUOTA_PROJECT:
        req.add_header("X-Goog-User-Project", GEMINI_QUOTA_PROJECT)

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
