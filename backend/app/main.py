from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import notice, tts, user

app = FastAPI(
    title="가정통신문 AI 도우미 API",
    description="베트남 결혼이민 학부모를 위한 가정통신문 할 일 요약 + TTS 서비스",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(notice.router, prefix="/notice", tags=["notice"])
app.include_router(tts.router, prefix="/tts", tags=["tts"])
app.include_router(user.router, prefix="/user", tags=["user"])


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
