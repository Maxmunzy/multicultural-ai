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


class NoticeAnalyzeRequest(BaseModel):
    target_language: str   # vi/en/ru/ms/mn/zh/th/ja/ko_easy — 필수, default 없음


# ── 슬롯 기반 응답 (강사 처방 1·3 대응) ──────────────────────────
# source: "regex" | "model" | "model+regex" — 신뢰도 추적용
# 정규식이 잡은 항목은 LLM 의존 없이 확보됐음을 안드/검수에서 표시 가능.
class SlotEntry(BaseModel):
    ko: str
    translated: str = ""
    source: str = "model"
    conditional: bool = False  # "흐릴 경우 우산" 같은 조건부 항목


class SummarySlots(BaseModel):
    dates: list[SlotEntry] = []
    times: list[SlotEntry] = []
    places: list[SlotEntry] = []
    supplies: list[SlotEntry] = []   # ⚠️ 강사 강조: 누락 금지
    amounts: list[SlotEntry] = []    # ⚠️ 강사 강조: 누락 금지
    deadlines: list[SlotEntry] = []


class AnalyzeItem(BaseModel):
    """카테고리별 할 일 — TodoItem(추출기 출력)을 슬롯 분해한 결과."""
    category: Category
    title_ko: str
    title_translated: str = ""
    when: str | None = None
    where: str | None = None
    what: list[str] = []
    amount: str | None = None
    deadline: str | None = None
    importance: float = 0.5
    note_ko: str | None = None         # 조건부 메모 (예: "날씨가 흐릴 경우")
    note_translated: str | None = None


class NoticeAnalyzeResponse(BaseModel):
    notice_id: str
    raw_text: str
    target_language: str
    summary: SummarySlots
    items: list[AnalyzeItem] = []
    tts_url: str = ""
    quality_note: str = ""
    review_needed: str = ""


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
