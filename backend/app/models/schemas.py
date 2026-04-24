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
