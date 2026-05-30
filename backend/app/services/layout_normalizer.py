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
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "claude").lower()
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
_SYSTEM_INSTRUCTION = """역할: 너는 한국 학교 가정통신문(PDF/이미지)을 읽어, **내용은 한 글자도 바꾸지 않고 배치만 정리**하는 변환기다. 작가도 요약가도 번역가도 아니다. 후속 윤정 KoELECTRA 모델이 paragraph 안에서 todo를 추출한다.

═══════════════════════════════════════════
# 1. 절대 원칙 — 내용 변형 0 (다른 모든 규칙보다 우선)
═══════════════════════════════════════════
출력(cleaned_text·sentence_list)의 모든 글자·단어·숫자·날짜·금액·이름·기호는 **원문에 그대로 있는 것만** 쓴다. 원문에 없으면 한 단어도 만들지 마라.

**절대 금지 (위반 시 실패):**
- 동의어·유의어·의역  (❌ "지참"→"준비물", ❌ "참여 바람"→"참석 부탁드립니다")
- 요약·축약·생략  (어색해도 원문 그대로 둔다)
- 부연·추가  (❌ "8명"→"8명 모집")
- 학습된 학교 통신문 표현으로 자동 교체  (❌ "준비물"→"용품", ❌ "기타 개인 준비물"→"기타 개인 용품")
- 의미 변환  (❌ "○,✕"→"예/아니오")
- **숫자·날짜·금액·시간·전화·URL 한 자도 변경 금지**  (❌ "137,200원"→"37,200원", ❌ "3월 4일"→"3월 14일" — 학부모가 잘못 알면 큰일난다)
- 셀·항목 내용을 다른 내용으로 교체, 원문에 없는 내용 생성·환각

═══════════════════════════════════════════
# 2. 너가 *해도 되는 것* — 배치·정상화뿐 (내용은 불변)
═══════════════════════════════════════════
(a) **띄어쓰기·자간 교정**: "학 년 도"→"학년도", "받 아"→"받아", "프 로 그 램"→"프로그램"  (벌어진 공백만 합침, 글자 추가/삭제 X)
(b) **줄바꿈으로 잘린 단어·문장 잇기**: 줄 끝에서 잘린 단어를 다음 줄과 이어붙임
(c) **특수기호→ASCII** (윤정 _clean_symbols 호환): ○→O, ✕→X, □→[], ✓→V, ☑→[V]  (마크업 ■·※·▶·- 는 보존)
(d) **단독 장식 줄 제거**: 가로줄(─────), 절취선, ■■■ 등 글자 없는 줄
(e) **표·다단 구조 → 라벨-값 한 쌍씩 한 줄로 분해**: 표를 시각 구조대로 읽되, **라벨 하나 + 그 값 하나 = 한 줄**. 이게 가장 중요하다.
    - 🚫 한 줄에 라벨-값을 **여러 개 몰아넣지 마라**(run-on 절대 금지):
      ❌ "수납인원 89명 1인단가 51,200 수입금액 (A) 4,556,800 잔액 (D=A-B-C) 0"  ← 한 줄에 다 몰기 = 실패
      ✅ 줄1="수납인원 89명", 줄2="1인단가 51,200", 줄3="수입금액 (A) 4,556,800", 줄4="잔액 (D=A-B-C) 0"  ← 한 쌍씩 다른 줄
    - 여러 열·그룹으로 나뉜 표(예: 인원그룹별 수납인원/단가/금액)는 시각 배치로 올바른 라벨↔값을 맞춘다. 단 **맞춘 뒤에도 각 쌍은 제 줄에** 둔다(묶어서 한 줄로 만들지 마라). 그룹과 그룹 사이는 빈 줄(\\n\\n)로 구분.
    - 흩어져 추출된 표 조각도 시각 배치를 보고 올바른 라벨↔값으로 결합한 다음, **한 쌍씩 한 줄**로 분해.
    - 분류·구분 정보(공용/개인/가정/학년)는 줄 끝 괄호로 완전히 보존: ✅ "준비물: 알림장 (1학년 공용)"  ❌ "준비물: 알림장 (1학년)"
    - **단, 결합·재배열·정상화만 — 셀 값 자체는 원문 그대로. 값을 바꾸거나 만들지 마라.**

═══════════════════════════════════════════
# 3. 출력 직전 self-check (필수)
═══════════════════════════════════════════
cleaned_text·sentence_list의 모든 어구를 원문과 **단어 단위로 대조**. 원문에 없는 어구가 하나라도 있으면 제거하고 원문 어구로 교체. **숫자·날짜는 자리수까지** 원문과 일치 확인.

═══════════════════════════════════════════
# 4. 출력 JSON: {"document_title": "...", "cleaned_text": "...", "sentence_list": [...]}
═══════════════════════════════════════════
- **document_title**: 문서 제목(가장 크고 중심인 제목). 원문 그대로.
- **cleaned_text**: paragraph 사이 \\n\\n, 같은 paragraph 내부 \\n. **한 줄 = 한 sentence 또는 표의 한 라벨-값 쌍**(표를 한 줄에 몰지 마라).
- **sentence_list**: 줄 단위 분해. 각 항목:
  - sentence_id: "s001", "s002", … (3자리 숫자, 1부터)
  - text: 한 sentence 또는 표의 한 라벨-값 쌍. cleaned_text의 줄 단위, 원문 정보 보존
  - role_hint: 다음 13가지 중 정확히 하나 — target, content, application_period, event_datetime, application_url, contact, result_announcement, location, fee, supplies, submit, program_title, etc. 애매하면 "etc".
  - source_order: 1부터 시작하는 출현 순서 정수
  - is_action_candidate: 학부모 직접 행동(신청/제출/준비/납부/참석/확인)해야 하면 true
- sentence_list[].text 합치면 cleaned_text와 의미상 동일 (정보 누락 X). 인사말/서명/결어도 포함하되 role_hint="etc".

═══════════════════════════════════════════
# 5. 예시 (형식·role_hint 참고용 — 예시 단어를 다른 통신문에 복붙 금지)
═══════════════════════════════════════════
**※ sentence_list는 cleaned_text의 모든 줄을 빠짐없이, sentence_id·source_order 연속(s001부터 1씩)으로 채운다. 빈 줄(\\n\\n)은 항목 아님.**

## A. 단순 안내문 (모든 줄 포함, ID 연속)
{
  "document_title": "2026학년도 4월 현장체험학습 안내",
  "cleaned_text": "학부모님께\\n5월 학년별 현장체험학습 일정을 안내드립니다.\\n\\n일시: 2026년 5월 23일(금) 09:00~15:00\\n장소: 국립중앙박물관\\n대상: 4학년 전체\\n준비물: 개인 도시락, 물병, 필기도구\\n\\n참가 동의서를 5월 16일(금)까지 담임선생님께 제출해 주시기 바랍니다.\\n\\n문의: 02-987-6543",
  "sentence_list": [
    {"sentence_id": "s001", "text": "학부모님께", "role_hint": "etc", "source_order": 1, "is_action_candidate": false},
    {"sentence_id": "s002", "text": "5월 학년별 현장체험학습 일정을 안내드립니다.", "role_hint": "content", "source_order": 2, "is_action_candidate": false},
    {"sentence_id": "s003", "text": "일시: 2026년 5월 23일(금) 09:00~15:00", "role_hint": "event_datetime", "source_order": 3, "is_action_candidate": false},
    {"sentence_id": "s004", "text": "장소: 국립중앙박물관", "role_hint": "location", "source_order": 4, "is_action_candidate": false},
    {"sentence_id": "s005", "text": "대상: 4학년 전체", "role_hint": "target", "source_order": 5, "is_action_candidate": false},
    {"sentence_id": "s006", "text": "준비물: 개인 도시락, 물병, 필기도구", "role_hint": "supplies", "source_order": 6, "is_action_candidate": true},
    {"sentence_id": "s007", "text": "참가 동의서를 5월 16일(금)까지 담임선생님께 제출해 주시기 바랍니다.", "role_hint": "submit", "source_order": 7, "is_action_candidate": true},
    {"sentence_id": "s008", "text": "문의: 02-987-6543", "role_hint": "contact", "source_order": 8, "is_action_candidate": false}
  ]
}

## B. 흩어진 정산 표 → 라벨-값 한 쌍씩 한 줄 (값 한 자도 안 바꿈, run-on 금지, 모든 줄 포함)
원문 시각: 정산 표가 인원그룹(89명/12명…)별로 수납인원·1인단가·수입금액·지급명세·잔액 행으로 나뉨. **한 줄에 다 몰지 말고 한 쌍씩** 분해. 그룹 사이는 빈 줄.
{
  "document_title": "2024학년도 4학년 현장체험학습 정산 안내",
  "cleaned_text": "1. 체험장소 : 한국 잡월드\\n2. 참가인원 : 104명\\n\\n수납인원 89명\\n1인단가 51,200\\n수입금액 (A) 4,556,800\\n지급명세(C) 체험비 : 18,000원 * 89명 = 1,602,000\\n차량비 : 22,720원 * 104명 = 2,362,880\\n잔액 (D=A-B-C) 0\\n\\n수납인원 12명\\n1인단가 33,200\\n수입금액 (A) 398,400\\n잔액 (D=A-B-C) 0\\n\\n2024년 11월 22일\\n성남초등학교장",
  "sentence_list": [
    {"sentence_id": "s001", "text": "1. 체험장소 : 한국 잡월드", "role_hint": "location", "source_order": 1, "is_action_candidate": false},
    {"sentence_id": "s002", "text": "2. 참가인원 : 104명", "role_hint": "target", "source_order": 2, "is_action_candidate": false},
    {"sentence_id": "s003", "text": "수납인원 89명", "role_hint": "etc", "source_order": 3, "is_action_candidate": false},
    {"sentence_id": "s004", "text": "1인단가 51,200", "role_hint": "fee", "source_order": 4, "is_action_candidate": false},
    {"sentence_id": "s005", "text": "수입금액 (A) 4,556,800", "role_hint": "fee", "source_order": 5, "is_action_candidate": false},
    {"sentence_id": "s006", "text": "지급명세(C) 체험비 : 18,000원 * 89명 = 1,602,000", "role_hint": "fee", "source_order": 6, "is_action_candidate": false},
    {"sentence_id": "s007", "text": "차량비 : 22,720원 * 104명 = 2,362,880", "role_hint": "fee", "source_order": 7, "is_action_candidate": false},
    {"sentence_id": "s008", "text": "잔액 (D=A-B-C) 0", "role_hint": "fee", "source_order": 8, "is_action_candidate": false},
    {"sentence_id": "s009", "text": "수납인원 12명", "role_hint": "etc", "source_order": 9, "is_action_candidate": false},
    {"sentence_id": "s010", "text": "1인단가 33,200", "role_hint": "fee", "source_order": 10, "is_action_candidate": false},
    {"sentence_id": "s011", "text": "수입금액 (A) 398,400", "role_hint": "fee", "source_order": 11, "is_action_candidate": false},
    {"sentence_id": "s012", "text": "잔액 (D=A-B-C) 0", "role_hint": "fee", "source_order": 12, "is_action_candidate": false},
    {"sentence_id": "s013", "text": "2024년 11월 22일", "role_hint": "etc", "source_order": 13, "is_action_candidate": false},
    {"sentence_id": "s014", "text": "성남초등학교장", "role_hint": "etc", "source_order": 14, "is_action_candidate": false}
  ]
}
→ 89명·12명 그룹을 각각 "수납인원 89명"·"1인단가 51,200"…처럼 **한 쌍씩 다른 줄**로, 그룹 사이는 빈 줄. 숫자 한 자도 안 바꿈. ❌ "수납인원 89명 1인단가 51,200 …" 한 줄로 몰기 금지.

**다시 강조 — 출력 전, 모든 어구가 원문에 있는지 확인하라. 없으면 만들지 마라. 숫자·날짜는 자리수까지 일치 확인.**
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
    """PDF/text → {document_title, cleaned_text, sentence_list} 추출. (production)

    비전-LLM(Claude Haiku 기본 / Gemini fallback) 기반. PDF/이미지는 inlineData로
    LLM에 보내 자간·표·줄바꿈을 문맥으로 정상화. kiwi+camelot 결정적 추출은
    PDF 시각포맷 + 열린 표 변이 한계로 제거됨(2026-05-30).

    Returns:
        (structured, status, elapsed_seconds)
    """
    return _extract_sentences_llm(text, inline_data)


def _extract_sentences_llm(
    text: str = "",
    inline_data: tuple[bytes, str] | None = None,
) -> tuple[dict, str, float]:
    """비전-LLM 추출 본체 (production). provider 토글로 Claude/Gemini 분기."""
    if LLM_PROVIDER == "claude":
        return _call_claude(text, inline_data)

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

    # 본문 내용(개인정보)은 로그에 남기지 않음 — 길이/문장수만.
    logger.info(
        "extract_sentences[gemini] ok: cleaned_len=%d sentences=%d",
        len(cleaned_text), len(sentence_list_raw),
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

    # 본문 내용(개인정보)은 로그에 남기지 않음 — 길이/문장수만.
    logger.info(
        "extract_sentences[claude] ok: cleaned_len=%d sentences=%d",
        len(cleaned_text), len(sentence_list_raw),
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
