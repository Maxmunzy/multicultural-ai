"""LLM 기반 통신문 sentence 추출기 (PoC).

Ollama (Qwen 2.5 3B Q4_K_M)를 백엔드 컨테이너에서 호출해 윤정 모델 입력 전
sentence list를 추출한다.

목표 (방향 전환 — "정리"가 아니라 "추출"):
- 통신문에서 학부모에게 필요한 sentence만 list로 뽑음 → 출력 토큰 1/3로 감소
- 표 행 / 일정 / 마감일 / 연락처 / 메타정보 각각 한 sentence로
- "절대 제거 금지" 항목 명시 (전화번호/URL/날짜/금액/학년·반/담당자)
- 출력 JSON 형식 — 짧고 파싱 안전, mid-sentence 절단 위험 ↓

이전 "정리" 프롬프트는 출력 4096토큰 한도 다 채워 6분+ 소요 + 정보 손실 발생.
"추출" 방향이 동일 인프라(CPU)에서 시간 50%+ 단축 + 핵심 정보 보존.

기본값 활성 (analyze 요청에서 use_llm_normalizer=true가 기본).
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


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://172.17.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300"))


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

출력 형식 — JSON만 (다른 코멘트, 설명, 머리말 X):
{{"sentences": ["...", "...", ...]}}

[입력]
{text}

[출력]
"""


def _extract_json_block(raw: str) -> str | None:
    """LLM 출력에서 JSON 블록 추출. markdown code fence ```json ... ``` 도 처리."""
    s = raw.strip()
    # ```json...``` 또는 ```...``` 제거
    if s.startswith("```"):
        # 첫 줄 제거 (```json or ```)
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        # 끝 ``` 제거
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    # 첫 { 와 마지막 } 사이를 JSON으로 가정
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    return s[start:end + 1]


def normalize_text(text: str) -> tuple[str, str, float]:
    """Ollama에 통신문을 보내 sentence list 추출. 실패 시 원본 그대로.

    Returns:
        (cleaned_text, status, elapsed_seconds)
        - cleaned_text: sentence list를 \n으로 join한 텍스트 (실패 시 원본)
        - status: "ok" | "skip:empty" | "skip:no_json" | "skip:invalid_format" |
                  "skip:empty_sentences" | "skip:error:..."
        - elapsed_seconds: Ollama 호출 시간 (실패 시 -1)
    """
    if not text or not text.strip():
        return text, "skip:empty", 0.0

    prompt = _EXTRACT_PROMPT.format(text=text)
    # num_predict 동적 — sentence 추출이라 보통 입력보다 짧음. 2048 cap으로 절단 위험 차단.
    # 한국어 1글자 ≈ 1.5~2 토큰. 입력 1300자 → 2000토큰. 출력은 보통 60~80% 수준.
    num_predict = min(2048, max(512, int(len(text) * 1.0)))

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",  # Ollama가 JSON 출력 강제 — 모델이 코드펜스/수식어 안 붙임
        "options": {
            "num_predict": num_predict,
            "temperature": 0.2,
            "top_p": 0.9,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.URLError as error:
        elapsed = time.monotonic() - started
        logger.warning("layout_normalizer URL error after %.2fs: %s", elapsed, error)
        return text, "skip:error:URLError", -1
    except TimeoutError as error:
        elapsed = time.monotonic() - started
        logger.warning("layout_normalizer timeout after %.2fs: %s", elapsed, error)
        return text, "skip:error:Timeout", -1
    except Exception as error:
        elapsed = time.monotonic() - started
        logger.warning("layout_normalizer failed after %.2fs: %s", elapsed, error)
        return text, f"skip:error:{type(error).__name__}", -1

    elapsed = time.monotonic() - started
    try:
        data = json.loads(body)
        raw_out = (data.get("response") or "").strip()
    except json.JSONDecodeError:
        logger.warning("layout_normalizer Ollama response decode failed (took %.2fs)", elapsed)
        return text, "skip:error:OllamaResponseDecode", elapsed

    # LLM이 형식 어긴 경우 코드펜스 등 제거 후 JSON 블록만 추출
    json_block = _extract_json_block(raw_out)
    if json_block is None:
        logger.warning(
            "layout_normalizer no JSON block in output (took %.2fs, raw_head=%r)",
            elapsed, raw_out[:150],
        )
        return text, "skip:no_json", elapsed

    try:
        parsed = json.loads(json_block)
    except json.JSONDecodeError as error:
        logger.warning(
            "layout_normalizer JSON parse failed (took %.2fs, error=%s, head=%r)",
            elapsed, error, json_block[:150],
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
