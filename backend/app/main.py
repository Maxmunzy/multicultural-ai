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


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_demo_users()
    yield


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
