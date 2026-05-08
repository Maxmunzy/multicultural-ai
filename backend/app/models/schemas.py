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


class OcrCorrectionEntry(BaseModel):
    slot_type: str
    raw_text: str
    corrected_text: str
    reason: str
    review_required: bool = False


class Notice(BaseModel):
    notice_id: str
    teacher_id: str
    parent_id: str
    text: str
    todos: list[TodoItem] = []
    # 원본 파일 (선생님/학부모가 업로드한 PDF/이미지). text 직송이면 None.
    original_file_url: str | None = None       # 예: "/static/notices/abc123.pdf"
    original_filename: str | None = None       # 예: "5월 가정통신문.pdf"
    mime_type: str | None = None               # 예: "application/pdf"
    # OCR slot 보정 이력 — 업로드 시 적용, analyze 응답에 포함
    ocr_corrections: list[OcrCorrectionEntry] = []
    layout_json: Any | None = None


class NoticeSendRequest(BaseModel):
    teacher_id: str
    parent_id: str
    text: str


class NoticeAnalyzeRequest(BaseModel):
    target_language: str   # vi/en/ru/ms/mn/zh/th/ja/ko_easy — 필수, default 없음
    # OCR/PDF layout — Android ML Kit OCR JSON 또는 backend pdfplumber probe JSON.
    # 있으면 highlight_mapper가 카드 ↔ bbox 매칭해 highlights[]를 채운다.
    # 없으면 highlights는 빈 리스트로 남고 안드는 텍스트 카드만 표시.
    layout_json: Any | None = None
    # LLM(Ollama) preprocessor — 윤정 모델 입력 전 텍스트 정리.
    # 표 행 분리, 자간 정상화, 헤더 추출, "표" 같은 노이즈 제거.
    # 실패/타임아웃 시 휴리스틱(parser.py 학년 행 분리)으로 fallback.
    # 기본 true — 일반 통신문 처리에 유리, 휴리스틱은 fallback 안전망.
    use_llm_normalizer: bool = True


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
    """카테고리별 할 일 — YunjeongTodo + 경이님 카테고리 결합 결과.

    deprecated — SlotCard로 대체 예정 (안드 마이그레이션 완료 후 폐기).
    """
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


class ChecklistItem(BaseModel):
    """행동 항목 — 학부모가 챙김/제출/납부/신청 후 체크할 단위.

    SlotCard.checklist에 들어가서 안드 UI 체크박스로 렌더링.
    영속 상태(checked)는 별도 메모리 dict — 시연용. (parent_id, notice_id, card_idx, item_idx)
    """
    ko: str                              # 예: "샤프식 색연필 12색"
    note: str = ""                       # 예: "(연필식 색연필 불가)" — 괄호 부연
    translated: str = ""                 # NLLB 번역 (mode=translated 표시용)
    checked: bool = False                # 메모리 dict에서 채워줌


class SlotCard(BaseModel):
    """슬롯 카드 — 헤더 + 값 + 카테고리 칩.

    강사님 처방 "지저분한 줄글 X, 슬롯 위주로 가공" 대응.
    한 카드 = 한 의미 단위 (운영시간 / 신청기간 / 운영방법 ...).
    todos 헤더 분해 + regex 슬롯 컨텍스트 매칭 둘 다 카드로 통합.
    """
    header_ko: str                       # 예: "운영시간"
    header_translated: str = ""          # 예: "Thời gian hoạt động"
    value_ko: str                        # 예: "오전 10:00 ~ 12:00 (2시간)"
    value_easy_ko: str = ""              # 세종님 to_easy_korean() 결과 — 미구현 시 value_ko 그대로
    value_translated: str = ""           # NLLB 번역 결과
    chip: str | None = None              # category 값 — None이면 칩 미표시
    importance: float = 0.5              # 정렬용 (높은 순)
    checklist: list[ChecklistItem] = []  # 행동 항목 — 비어있으면 안드 UI 체크박스 영역 미표시


class HighlightBBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class HighlightPageSize(BaseModel):
    width: float
    height: float


class NoticeHighlight(BaseModel):
    """원본 문서 overlay 하이라이트 후보.

    bbox/page_size는 같은 좌표계여야 한다. Android는 page_size 기준으로
    렌더링 크기에 맞춰 bbox를 scale한다.
    """
    highlight_id: str = ""
    page: int = 1
    source: str = ""                     # mlkit_line | pdfplumber_line | pdfplumber_table
    bbox: HighlightBBox
    page_size: HighlightPageSize
    text: str
    category: Category | None = None
    importance: float = 0.5
    translated: str = ""
    easy_ko: str = ""


class NoticeAnalyzeResponse(BaseModel):
    notice_id: str
    raw_text: str
    target_language: str
    page_count: int = 1
    # 통신문 제목 (윤정님 PR #90 extract_title heuristic) — 못 찾으면 ""
    title: str = ""
    title_translated: str = ""
    # 원본 PDF/이미지 위 overlay 하이라이트 후보 (OCR/PDF bbox 피벗 트랙)
    highlights: list[NoticeHighlight] = []
    # 신규 — 안드 슬롯 카드 UI 대상 (단계적 마이그레이션, 본 필드가 메인)
    cards: list[SlotCard] = []
    # Must-check information from slot preservation.  This stays separate from
    # action cards so dates, event times, URLs, contacts, and targets survive
    # even when model A does not classify them as todos.
    info_cards: list[SlotCard] = []
    # deprecated — 안드 마이그레이션 완료 후 다음 PR에서 폐기 예정
    summary: SummarySlots
    items: list[AnalyzeItem] = []
    tts_text: str = ""                   # 음성 변환 직전 텍스트 — 시연·디버그용 가시화
    tts_url: str = ""                    # 번역 합본 TTS (안드 기존 버튼)
    tts_url_easy_ko: str = ""            # 쉬운 한국어 합본 TTS (세종님 별도 버튼 요청)
    quality_note: str = ""
    review_needed: str = ""
    # OCR slot 보정 요약 — has_review_required=True면 프론트에서 "사람 확인 필요" 표시
    ocr_corrections: list[OcrCorrectionEntry] = []
    has_review_required: bool = False


class ChecklistUpdateRequest(BaseModel):
    """체크박스 토글 — 안드가 카드별 항목 체크/해제 시 호출.

    card_idx, item_idx는 analyze 응답 안 SlotCard 위치 (안드가 받은 그대로 인덱싱).
    card_kind는 응답 필드명("cards" | "info_cards")의 단축형.
    """
    card_kind: str   # "card" | "info"
    card_idx: int
    item_idx: int
    checked: bool


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
