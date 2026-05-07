"""LLM 기반 통신문 텍스트 정리기 (PoC).

Ollama (Qwen 2.5 3B Q4_K_M)를 백엔드 컨테이너에서 호출해 윤정 모델 입력 전
텍스트를 정리한다. 표 행 분리, 자간 정상화, 노이즈 제거가 목적.

목표:
- 학년 표 등 정형 표를 자연어 sentence로 변환 → 윤정 모델 sentence 분리 보강
- "학 년 도" → "학년도" 자간 정상화
- 의미 없는 기호 줄 제거
- **의미 추가/축약 금지** — 원문 정보만 유지

기본값은 비활성화 (analyze 요청에서 `use_llm_normalizer=true`일 때만 호출).
실패/타임아웃/너무 짧은 출력은 원본 텍스트로 fallback해 회귀 방지.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


# Ollama는 NCP 호스트의 systemd로 떠있고 백엔드는 docker container.
# container → host 접근은 docker bridge gateway (172.17.0.1) 사용.
# 환경변수로 override 가능 (다른 NCP / 다른 모델 / 로컬 개발 등).
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://172.17.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
# Cold start (모델 로드) 포함이라 보수적. warm은 5~30s 정도.
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300"))


_NORMALIZE_PROMPT = """당신은 한국 학교 가정통신문을 정리하는 도우미입니다.

규칙:
- 표(헤더 + 데이터 행)는 행마다 자연 한국어 한 문장으로 변환
- 한 행에 헤더-값 짝이 있으면 "{{헤더}}: {{값}}" 또는 "{{헤더}}는 {{값}}입니다" 형식
- 자간 공백 정상화 ("학 년 도" → "학년도", "의 정 부 시" → "의정부시")
- 의미 없는 기호 줄 (■, □, ※, 가로줄 등 단독 기호)은 제거
- 원문에 없는 정보 추가 금지, 요약/축약 금지
- 시제 변경 금지 (미래 일정을 과거형으로 바꾸지 말 것)
- 출력은 정리된 한국어 텍스트만 (다른 메타 코멘트, 설명, 머리말 X)

[입력]
{text}

[출력]
"""


def normalize_text(text: str) -> tuple[str, str, float]:
    """Ollama로 통신문 텍스트 정리. 실패 시 원본 그대로.

    Returns:
        (cleaned_text, status, elapsed_seconds)
        - cleaned_text: 정리된 텍스트 (실패 시 원본)
        - status: "ok" | "skip:empty" | "skip:too_short" | "skip:error:..."
        - elapsed_seconds: Ollama 호출에 걸린 시간 (실패 시 -1)
    """
    if not text or not text.strip():
        return text, "skip:empty", 0.0

    prompt = _NORMALIZE_PROMPT.format(text=text)
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 4096,
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
        return text, f"skip:error:URLError", -1
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
        out = (data.get("response") or "").strip()
    except json.JSONDecodeError:
        logger.warning("layout_normalizer JSON decode failed (took %.2fs)", elapsed)
        return text, "skip:error:JSONDecode", elapsed

    # 가드: 출력이 너무 짧으면 모델이 요약/누락한 것으로 의심해 fallback.
    # 입력의 30% 미만이면 원본 그대로 사용.
    if len(out) < max(50, int(len(text) * 0.3)):
        logger.warning(
            "layout_normalizer output too short (%d < %d), fallback (took %.2fs)",
            len(out), len(text), elapsed,
        )
        return text, "skip:too_short", elapsed

    return out, "ok", elapsed
