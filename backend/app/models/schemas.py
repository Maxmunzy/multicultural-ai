from enum import Enum
from typing import Any
from pydantic import BaseModel


class KoreanLevel(str, Enum):
    beginner = "beginner"          # 초급: 베트남어 TTS
    intermediate = "intermediate"  # 중급: 한국어 TTS + 용어 설명


class Category(str, Enum):
    schedule = "일정"
    supplies = "준비물"
    submission = "제출"
    cost = "비용"
    health = "건강·안전"
    other = "기타"


class TodoItem(BaseModel):
    category: Category
    text_ko: str
    text_vi: str
    importance: float  # 0.0 ~ 1.0
    due_date: str | None = None


class Notice(BaseModel):
    notice_id: str
    teacher_id: str
    parent_id: str
    text: str
    todos: list[TodoItem] = []


class NoticeSendRequest(BaseModel):
    teacher_id: str
    parent_id: str
    text: str


class NoticeAnalyzeResponse(BaseModel):
    notice_id: str
    raw_text: str
    todos: list[TodoItem]
    easy_ko_text: str = ""        # 쉬운 한국어 (세종 파이프라인 산출물)
    vi_text: str = ""             # 베트남어 번역
    quality_note: str = ""        # 용어 검수 결과 (ok / missing_term / review_needed)
    review_needed: str = ""       # 검수 필요 항목 상세
    tts_url: str = ""             # TTS 음성 파일 URL


class TTSRequest(BaseModel):
    user_id: str
    todo_items: list[TodoItem]
    level: KoreanLevel


class UserProfile(BaseModel):
    user_id: str
    role: str = "parent"   # "teacher" | "parent"
    child_grade: int = 1   # 1~6학년 (부모만 해당)
    level: KoreanLevel = KoreanLevel.beginner
    tts_speed: float = 1.0


class ApiResponse(BaseModel):
    status: str   # "success" | "error"
    data: Any = None
    message: str = ""

    @classmethod
    def success(cls, data: Any = None, message: str = "") -> "ApiResponse":
        return cls(status="success", data=data, message=message)

    @classmethod
    def error(cls, message: str) -> "ApiResponse":
        return cls(status="error", data=None, message=message)
