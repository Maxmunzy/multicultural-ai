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


class YunjeongTodo(BaseModel):
    """윤정님 v2 추출 모델 출력 — 통신문 1개에서 문장 단위로 뽑힌 할일.

    내부에 정규식 due_date/amount 추출 + binary 분류(BINARY_THRESHOLD=0.5) 포함.
    confidence < 0.5 항목은 모델이 자동 필터링해 출력에 포함 안 됨.
    """
    text: str                       # 원문 문장
    source: str | None = None       # 파일명 (같은 통신문 묶음용)
    due_date: str | None = None     # YYYY-MM-DD 또는 상대표현 ("다음 주 금요일")
    amount: int | None = None       # 원 단위
    confidence: float               # binary 확률 (0.0 ~ 1.0)
    action_hint: str | None = None  # 신청 / 제출 / 납부 / 준비 / 참여 / 확인


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
    urls: list[SlotEntry] = []       # NLLB가 깨먹지 않게 ko 그대로 노출
    phones: list[SlotEntry] = []     # 같은 이유


class AnalyzeItem(BaseModel):
    """카테고리별 할 일 — YunjeongTodo + 경이님 카테고리 결합 결과."""
    category: Category                  # 경이님 (주제: 일정/준비물/제출/비용/건강·안전/기타)
    action_hint: str | None = None      # 윤정님 (행동: 신청/제출/납부/준비/참여/확인)
    title_ko: str
    title_translated: str = ""
    when: str | None = None
    where: str | None = None
    what: list[str] = []
    amount: str | None = None
    deadline: str | None = None
    importance: float = 0.5
    note_ko: str | None = None          # 조건부 메모 (예: "날씨가 흐릴 경우")
    note_translated: str | None = None


class NoticeAnalyzeResponse(BaseModel):
    notice_id: str
    raw_text: str
    target_language: str
    summary: SummarySlots
    items: list[AnalyzeItem] = []
    tts_text: str = ""        # 음성 변환 직전 텍스트 — 시연·디버그용 가시화
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
