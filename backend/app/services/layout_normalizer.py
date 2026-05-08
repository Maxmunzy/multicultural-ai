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

# LLM provider 토글: "gemini" (기본) | "claude"
# Gemini 503 폭주 회피용 fallback. Anthropic Claude는 다른 인프라.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
CLAUDE_TIMEOUT_SECONDS = float(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "60"))


# 모듈 로드 시 활성 provider의 키 상태를 한 번 출력 — 키 누락 후 분석 요청까지 기다리지 않고
# 바로 발견할 수 있게. 키 없으면 extract_sentences가 status="skip:no_key"로 우회 fallback —
# 에러는 안 나지만 LLM 정제 효과 0이라 운영자가 즉시 인지해야 함.
if LLM_PROVIDER == "claude" and not ANTHROPIC_API_KEY:
    logger.warning(
        "[layout_normalizer] LLM_PROVIDER=claude but ANTHROPIC_API_KEY is empty — "
        "extract_sentences will fallback to skip:no_key (LLM 정제 비활성)."
    )
elif LLM_PROVIDER != "claude" and not GEMINI_API_KEY:
    logger.warning(
        "[layout_normalizer] LLM_PROVIDER=%s but GEMINI_API_KEY is empty — "
        "extract_sentences will fallback to skip:no_key (LLM 정제 비활성).",
        LLM_PROVIDER,
    )


# 모든 모드(Vision/text) 공통 — Gemini systemInstruction.
# user contents와 분리해서 instruction 강도 ↑ (Gemini API systemInstruction은
# 지속 규칙으로 더 강하게 적용됨). preview 모델도 강제 따르게 만들기 위함.
_SYSTEM_INSTRUCTION = """한국 학교 가정통신문을 자체 PDF 파서가 만들 raw 텍스트 형태로 정제. 후속 윤정 KoELECTRA 모델이 paragraph 안에서 todo 추출.

**규칙** (모든 가정통신문 공통 — 특정 통신문 패턴 학습 X):
1. **한 줄 = 한 sentence** — 한 문장을 두 줄에 걸치지 말 것. 줄바꿈은 sentence 사이에만
2. **헤더-값은 콜론(:) 형식** — 조사("은/는") 사용 X
   ❌ "신청방법은 ..." / "비용은 ..." → ✅ "신청방법: ..." / "비용: ..."
3. **헤더 키워드 표준 통일** — 변형은 표준으로 정규화:
   - "준비/지참물/지참/준비사항" → **"준비물:"**
   - "시간/날짜" → **"일시:"**
   - "위치/주소" → **"장소:"**
   - "회비/참가비/수강료/급식비" → **"비용:"**
   - "연락처/문의처" → **"문의:"**
4. **헤더 키워드와 값에 같은 단어 등장 X** (윤정 split 트리거 회피):
   같은 sentence에 같은 키워드 두 번 나오면 값의 단어를 동의어로 교체
   ❌ "준비물: 간편한 복장, 물, 기타 개인 준비물 등" — "준비물" 두 번
   ✅ "준비물: 간편한 복장, 물, 기타 개인 용품 등" — 값의 "준비물" → "용품"
   동의어 가이드:
   - 준비물 → 용품/물품/물건
   - 일시 → 때/시각
   - 대상 → 사람/인원
   - 비용 → 금액/요금
5. **표 행은 한 줄 sentence** — 분류·구분 정보는 sentence 끝 괄호로 **완전히** 보존:
   - 학년 + 분류(공용/개인/가정/학교) 둘 다 있으면 **둘 다 명시**:
     ✅ "준비물: 알림장, 클리어 화일 (1학년 공용)"  ← 공용 명시
     ✅ "준비물: 줄 없는 종합장 1권 (1학년 가정)"  ← 가정 명시
     ❌ "준비물: 알림장 (1학년)"  ← 공용/가정 빠뜨리지 말 것
   - 다른 분류 정보(대상/구간 등)도 동일:
     ✅ "운영시간: 오전 10시 (1-3학년)"
     ✅ "비용: 35,000원 (4학년 학부모)"
   - prefix 시작 금지: ❌ "1학년 공용 준비물: ..."
6. **특수기호 → 알파벳 변환** (윤정 모델 _clean_symbols 호환):
   ○ → O, ✕ → X, □ → [], ✓ → V, ☑ → [V]
   (마크업 ■, ※, ▶ 등은 그대로 보존)
7. **자간 공백만 정상화** ("학 년 도" → "학년도"), 다른 글자 변경 X
8. **종결어미 강제 X** — 원문 그대로
9. **요약·축약 금지** — 의미 보존 (단 규칙 4 동의어 변환은 허용)
10. **날짜·시간·금액·URL·전화번호·고유명사·학교명·지명 원문 그대로**
11. **단독 기호 줄(■■■, 가로줄)만 제거** — 텍스트와 같이 있는 마크업은 보존
12. **원문에 없는 정보 추측·추가 금지**

**출력 JSON**: {"document_title": "...", "cleaned_text": "...", "sentence_list": [...]}

**cleaned_text** — paragraph 사이 \\n\\n, 같은 paragraph 내부 \\n. 윤정 KoELECTRA가 paragraph 흐름에서 todo 추출.

**sentence_list** — info_cards 빌드용 sentence 단위 분해. 각 항목:
- sentence_id: "s001", "s002", ... (3자리 숫자, 1부터)
- text: 한 sentence 또는 한 줄(헤더+값). cleaned_text 안의 줄을 단위로 쪼개되 원문 정보 보존
- role_hint: 다음 13가지 중 정확히 하나
  * "target" — 대상 (전교생, 1-3학년, 신청자 등)
  * "content" — 행사 내용 / 운영 내용 본문
  * "application_period" — 신청기간 (특정 날짜 범위 + "신청")
  * "event_datetime" — 운영일시 / 행사 일시 (날짜+시간)
  * "application_url" — URL 포함 줄
  * "contact" — 문의/연락처/전화번호
  * "result_announcement" — 결과 발표 안내
  * "location" — 장소/위치
  * "fee" — 비용/회비/금액
  * "supplies" — 준비물
  * "submit" — 제출/회신/동의서
  * "program_title" — 프로그램 명 / 헤더
  * "etc" — 그 외 (인사말, 결어, 일반 안내)
- source_order: 1부터 시작하는 출현 순서 정수
- is_action_candidate: 학부모 직접 행동(신청/제출/준비/납부/참석/확인)해야 하면 true

**규칙**:
- sentence_list[].text 합치면 cleaned_text와 의미상 동일해야 함 (정보 누락 X)
- role_hint는 위 13개 외 값 X. 애매하면 "etc"
- 인사말/서명/결어도 sentence_list에 포함하되 role_hint="etc"

**예시 — 학부모 공개수업 + 상담주간 (가상 합성)**:
{
  "document_title": "2026 학부모 공개수업 및 상담주간 안내",
  "cleaned_text": "학부모님, 안녕하십니까?\\n학교 교육에 대한 학부모님의 이해를 돕고자 다음과 같이 학부모 공개수업 및 상담주간을 운영합니다.\\n\\n■ 공개수업\\n일시: 2026년 5월 9일(금) 10:00~11:40\\n장소: 각 학년 교실\\n대상: 1-6학년 전교생 학부모\\n\\n■ 상담주간\\n기간: 2026년 5월 12일(월) ~ 5월 16일(금)\\n신청방법: 학교 홈페이지에서 온라인 신청 (선착순)\\n준비물: 간편한 복장, 물, 기타 개인 용품 (1-3학년 학부모)\\n비용: 무료\\n\\n■ 참가 동의서\\n참가 여부를 O,X로 표시하여 5월 7일(수)까지 담임선생님께 제출 바랍니다.\\n\\n※ 우천 시 일정 변경 안내는 학교 홈페이지 공지사항을 참고해 주십시오.\\n\\n문의: 02-1234-5678\\n2026. 5. 1. 서울갈산초등학교장",
  "sentence_list": [
    {"sentence_id": "s001", "text": "학부모님, 안녕하십니까?", "role_hint": "etc", "source_order": 1, "is_action_candidate": false},
    {"sentence_id": "s002", "text": "학교 교육에 대한 학부모님의 이해를 돕고자 다음과 같이 학부모 공개수업 및 상담주간을 운영합니다.", "role_hint": "content", "source_order": 2, "is_action_candidate": false},
    {"sentence_id": "s003", "text": "■ 공개수업", "role_hint": "program_title", "source_order": 3, "is_action_candidate": false},
    {"sentence_id": "s004", "text": "일시: 2026년 5월 9일(금) 10:00~11:40", "role_hint": "event_datetime", "source_order": 4, "is_action_candidate": false},
    {"sentence_id": "s005", "text": "장소: 각 학년 교실", "role_hint": "location", "source_order": 5, "is_action_candidate": false},
    {"sentence_id": "s006", "text": "대상: 1-6학년 전교생 학부모", "role_hint": "target", "source_order": 6, "is_action_candidate": false},
    {"sentence_id": "s007", "text": "■ 상담주간", "role_hint": "program_title", "source_order": 7, "is_action_candidate": false},
    {"sentence_id": "s008", "text": "기간: 2026년 5월 12일(월) ~ 5월 16일(금)", "role_hint": "application_period", "source_order": 8, "is_action_candidate": false},
    {"sentence_id": "s009", "text": "신청방법: 학교 홈페이지에서 온라인 신청 (선착순)", "role_hint": "application_period", "source_order": 9, "is_action_candidate": true},
    {"sentence_id": "s010", "text": "준비물: 간편한 복장, 물, 기타 개인 용품 (1-3학년 학부모)", "role_hint": "supplies", "source_order": 10, "is_action_candidate": true},
    {"sentence_id": "s011", "text": "비용: 무료", "role_hint": "fee", "source_order": 11, "is_action_candidate": false},
    {"sentence_id": "s012", "text": "■ 참가 동의서", "role_hint": "program_title", "source_order": 12, "is_action_candidate": false},
    {"sentence_id": "s013", "text": "참가 여부를 O,X로 표시하여 5월 7일(수)까지 담임선생님께 제출 바랍니다.", "role_hint": "submit", "source_order": 13, "is_action_candidate": true},
    {"sentence_id": "s014", "text": "※ 우천 시 일정 변경 안내는 학교 홈페이지 공지사항을 참고해 주십시오.", "role_hint": "etc", "source_order": 14, "is_action_candidate": false},
    {"sentence_id": "s015", "text": "문의: 02-1234-5678", "role_hint": "contact", "source_order": 15, "is_action_candidate": false},
    {"sentence_id": "s016", "text": "2026. 5. 1. 서울갈산초등학교장", "role_hint": "etc", "source_order": 16, "is_action_candidate": false}
  ]
}

원본의 "준비: 간편한 복장, 물, 기타 개인 준비물 등" 같은 케이스 → 헤더 통일("준비물:") + 값의 "준비물" → "용품"으로 변환해서 cleaned_text와 sentence_list에 동일하게 출력.
"""


# Vision mode user prompt — 짧게. 모든 규칙은 systemInstruction에 있음.
_USER_PROMPT_VISION = "첨부된 한국 학교 가정통신문(PDF/이미지)을 systemInstruction의 형식·규칙·예시대로 분석해서 JSON 세 필드(document_title, cleaned_text, sentence_list)로 출력하세요."


# Text mode user prompt — 짧게. 본문은 [입력] 안에.
_USER_PROMPT_TEXT = """다음 가정통신문 텍스트를 systemInstruction의 형식·규칙·예시대로 정제해서 JSON 세 필드(document_title, cleaned_text, sentence_list)로 출력하세요.

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
# sentence_list는 옵션(추가 정보) — 없어도 cleaned_text 기반 fallback이 동작.
_SENTENCE_LIST_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence_id": {"type": "string"},
        "text": {"type": "string"},
        "role_hint": {"type": "string"},
        "source_order": {"type": "integer"},
        "is_action_candidate": {"type": "boolean"},
    },
    "required": ["sentence_id", "text", "role_hint", "source_order"],
}

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_title": {"type": "string"},
        "cleaned_text": {"type": "string"},
        "sentence_list": {
            "type": "array",
            "items": _SENTENCE_LIST_ITEM_SCHEMA,
        },
    },
    "required": ["document_title", "cleaned_text"],
}


def _empty_structured() -> dict:
    return {"document_title": "", "cleaned_text": "", "sentence_list": []}


def extract_sentences(
    text: str = "",
    inline_data: tuple[bytes, str] | None = None,
) -> tuple[dict, str, float]:
    """LLM(Gemini/Claude)으로 통신문 본문 정제 → {document_title, cleaned_text} 반환.

    Provider 토글: LLM_PROVIDER=gemini (기본) | claude
    Gemini 503 폭주 시 Claude로 전환 가능 (다른 인프라).

    함수 이름은 호환성 위해 그대로 유지. 내부적으론 sentence_list 분해 안 함.

    두 가지 모드:
    - **text 모드** (기본): text 인자 사용, inline_data=None.
    - **Vision 모드**: inline_data=(raw_bytes, mime_type) 전달. PDF/이미지 첨부.

    실패 시 빈 dict({"document_title":"", "cleaned_text":""}) + status 반환.

    Returns:
        (structured, status, elapsed_seconds)
    """
    # Provider 분기 — Claude 우선
    if LLM_PROVIDER == "claude":
        return _call_claude(text, inline_data)

    # 기본 Gemini 분기
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
    sentence_list_raw = parsed.get("sentence_list") or []
    if not isinstance(sentence_list_raw, list):
        sentence_list_raw = []

    # DEBUG (임시): Gemini가 만든 cleaned_text head/tail docker logs에 dump.
    # paragraph 정제 결과 확인용. 튜닝 끝나면 제거.
    head = cleaned_text[:300].replace("\n", " / ")
    tail = cleaned_text[-200:].replace("\n", " / ") if len(cleaned_text) > 300 else ""
    logger.warning(
        "extract_sentences DEBUG cleaned_text len=%d sentences=%d title=%r head=%r tail=%r",
        len(cleaned_text), len(sentence_list_raw), document_title[:60], head, tail,
    )

    return (
        {
            "document_title": document_title,
            "cleaned_text": cleaned_text,
            "sentence_list": sentence_list_raw,
        },
        "ok",
        elapsed,
    )


def _call_claude(
    text: str = "",
    inline_data: tuple[bytes, str] | None = None,
) -> tuple[dict, str, float]:
    """Anthropic Claude API로 통신문 정제.

    Gemini systemInstruction과 동일한 규칙을 Claude system parameter로 전달.
    PDF는 "document" content block, 이미지는 "image" content block 사용.
    """
    if not ANTHROPIC_API_KEY:
        return _empty_structured(), "skip:no_key", 0.0

    if inline_data is not None:
        raw_bytes, mime_type = inline_data
        if not raw_bytes:
            return _empty_structured(), "skip:empty", 0.0
        if mime_type not in VISION_SUPPORTED_MIMES:
            logger.warning("Claude unsupported mime: %s", mime_type)
            return _empty_structured(), f"skip:unsupported_mime:{mime_type}", 0.0
        encoded = base64.b64encode(raw_bytes).decode("utf-8")
        # PDF는 document, 이미지는 image
        if mime_type == "application/pdf":
            block = {
                "type": "document",
                "source": {"type": "base64", "media_type": mime_type, "data": encoded},
            }
        else:
            block = {
                "type": "image",
                "source": {"type": "base64", "media_type": mime_type, "data": encoded},
            }
        user_content = [block, {"type": "text", "text": _USER_PROMPT_VISION}]
    else:
        if not text or not text.strip():
            return _empty_structured(), "skip:empty", 0.0
        user_content = [{"type": "text", "text": _USER_PROMPT_TEXT.format(text=text)}]

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        # 긴 통신문(특히 HWP 변환 결과 + sentence_list) 절단 방지 — Gemini의 32768과 일치.
        # 모델 자체 한계 이상은 무시되니 안전. 짧은 통신문은 출력 토큰만큼만 과금.
        "max_tokens": 32768,
        "system": _SYSTEM_INSTRUCTION + "\n\n출력은 JSON만 (다른 설명·머리말·코드펜스 X).",
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0.0,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    backoffs = [0, 2, 5]
    started = time.monotonic()
    body = None
    last_status = "skip:error:Unknown"
    last_attempt_log = ""
    for attempt, delay in enumerate(backoffs):
        if delay > 0:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=CLAUDE_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as error:
            try:
                err_body = error.read().decode("utf-8")[:200]
            except Exception:
                err_body = ""
            last_attempt_log = f"HTTP {error.code}: {error.reason} | {err_body}"
            last_status = f"skip:error:HTTP{error.code}"
            if 400 <= error.code < 500:
                logger.warning(
                    "Claude %s (no retry, attempt %d/%d)",
                    last_attempt_log, attempt + 1, len(backoffs),
                )
                return _empty_structured(), last_status, -1
            logger.warning(
                "Claude %s (attempt %d/%d, retrying)",
                last_attempt_log, attempt + 1, len(backoffs),
            )
        except (urllib.error.URLError, TimeoutError) as error:
            last_attempt_log = f"{type(error).__name__}: {error}"
            last_status = (
                "skip:error:URLError"
                if isinstance(error, urllib.error.URLError)
                else "skip:error:Timeout"
            )
            logger.warning(
                "Claude %s (attempt %d/%d, retrying)",
                last_attempt_log, attempt + 1, len(backoffs),
            )
        except Exception as error:
            last_status = f"skip:error:{type(error).__name__}"
            logger.warning("Claude %s: %s", type(error).__name__, error)
            return _empty_structured(), last_status, -1

    if body is None:
        elapsed = time.monotonic() - started
        logger.warning(
            "Claude all retries failed after %.2fs: %s", elapsed, last_attempt_log,
        )
        return _empty_structured(), last_status, -1

    elapsed = time.monotonic() - started
    try:
        data = json.loads(body)
        content = data.get("content", [])
        if not content:
            return _empty_structured(), "skip:no_content", elapsed
        raw_out = (content[0].get("text") or "").strip()
    except Exception as error:
        logger.warning("Claude response parse failed: %s", error)
        return _empty_structured(), "skip:error:ResponseParse", elapsed

    if not raw_out:
        return _empty_structured(), "skip:empty_response", elapsed

    # JSON 추출 — Claude는 raw text. 코드펜스/머리말 가능성 대비.
    s = raw_out
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or start >= end:
        logger.warning("Claude no JSON block in output: %r", raw_out[:150])
        return _empty_structured(), "skip:no_json", elapsed

    try:
        parsed = json.loads(s[start:end + 1])
    except json.JSONDecodeError as error:
        logger.warning(
            "Claude JSON parse failed (took %.2fs, error=%s, head=%r)",
            elapsed, error, raw_out[:150],
        )
        return _empty_structured(), "skip:error:JSONParse", elapsed

    if not isinstance(parsed, dict):
        return _empty_structured(), "skip:invalid_format", elapsed

    cleaned_text = parsed.get("cleaned_text", "")
    if not isinstance(cleaned_text, str) or not cleaned_text.strip():
        return _empty_structured(), "skip:empty_text", elapsed

    document_title = parsed.get("document_title", "") or ""
    sentence_list_raw = parsed.get("sentence_list") or []
    if not isinstance(sentence_list_raw, list):
        sentence_list_raw = []

    head = cleaned_text[:300].replace("\n", " / ")
    tail = cleaned_text[-200:].replace("\n", " / ") if len(cleaned_text) > 300 else ""
    logger.warning(
        "extract_sentences[claude] DEBUG cleaned_text len=%d sentences=%d title=%r head=%r tail=%r",
        len(cleaned_text), len(sentence_list_raw), document_title[:60], head, tail,
    )

    return (
        {
            "document_title": document_title,
            "cleaned_text": cleaned_text,
            "sentence_list": sentence_list_raw,
        },
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
