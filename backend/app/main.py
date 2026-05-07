from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import seed_demo_users
from app.routers import notice, tts, user

STATIC_DIR = Path("/app/static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "tts").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "notices").mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_demo_users()
    _warmup_nllb()
    _warmup_ollama()
    yield


def _warmup_nllb() -> None:
    """NLLB 모델을 startup 시 로드 + dummy 번역 1회로 그래프 워밍.

    첫 /notice/analyze 호출이 5~10초 cold start 페널티를 안 먹게 하기 위함.
    실패해도 서버 부팅은 막지 않음 — 분석 호출 시 lazy load fallback.
    """
    try:
        from app.services.translator import _translate
        _translate("안녕하세요", "vie_Latn", max_length=32)
        print("[startup] NLLB warmup 완료")
    except Exception as error:
        print(f"[startup] NLLB warmup 실패 (lazy load fallback): {error}")


def _warmup_ollama() -> None:
    """Ollama LLM normalizer를 짧은 dummy 요청으로 미리 메모리에 로드.

    첫 /notice/analyze 호출이 2~3분 cold start 페널티 안 먹게 하기 위함.
    Ollama 서비스 자체가 다운/네트워크 문제면 무시 (분석 호출 시 fallback).
    """
    try:
        from app.services.layout_normalizer import normalize_text
        # 짧은 더미 입력 — 응답 길이도 짧아서 30초 내 끝남
        out, status, elapsed = normalize_text("학부모님 안녕하세요. 오늘은 5월 7일입니다.")
        print(f"[startup] Ollama warmup: status={status} elapsed={elapsed:.2f}s out_len={len(out)}")
    except Exception as error:
        print(f"[startup] Ollama warmup 실패 (analyze 호출 시 fallback): {error}")


app = FastAPI(
    title="가정통신문 AI 도우미 API",
    description="베트남 결혼이민 학부모를 위한 가정통신문 할 일 요약 + TTS 서비스",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(notice.router, prefix="/notice", tags=["notice"])
app.include_router(tts.router, prefix="/tts", tags=["tts"])
app.include_router(user.router, prefix="/user", tags=["user"])


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
