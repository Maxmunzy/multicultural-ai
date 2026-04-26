"""모델 연결 전 mock 응답 데이터."""
from app.models.schemas import Category, TodoItem

MOCK_TODOS = [
    TodoItem(
        category=Category.submission,
        text_ko="현장체험학습 동의서를 내일까지 제출해주세요",
        text_vi="Nộp giấy đồng ý tham gia học trải nghiệm trước ngày mai",
        importance=1.0,
        due_date="내일",
    ),
    TodoItem(
        category=Category.supplies,
        text_ko="도시락, 개인 물병, 돗자리를 준비해주세요",
        text_vi="Chuẩn bị hộp cơm, bình nước cá nhân và chiếu",
        importance=0.95,
        due_date=None,
    ),
    TodoItem(
        category=Category.cost,
        text_ko="체험학습비 15,000원을 4월 22일까지 납부해주세요",
        text_vi="Nộp phí học trải nghiệm 15,000 won trước ngày 22 tháng 4",
        importance=0.85,
        due_date="4월 22일",
    ),
    TodoItem(
        category=Category.schedule,
        text_ko="4월 25일(금) 봄 소풍이 있습니다",
        text_vi="Ngày 25 tháng 4 (thứ Sáu) có chuyến dã ngoại mùa xuân",
        importance=0.9,
        due_date="4월 25일",
    ),
    TodoItem(
        category=Category.health,
        text_ko="미세먼지 심한 날에는 마스크를 착용해주세요",
        text_vi="Hãy đeo khẩu trang vào những ngày bụi mịn nặng",
        importance=0.7,
        due_date=None,
    ),
]

MOCK_EASY_KO = (
    "4월 25일 금요일에 봄 소풍을 갑니다.\n"
    "도시락, 물병, 돗자리를 준비해 주세요.\n"
    "체험학습비 15,000원을 4월 22일까지 내주세요.\n"
    "동의서를 내일까지 제출해 주세요."
)

MOCK_VI_TEXT = (
    "Ngày 25 tháng 4, thứ Sáu, sẽ có chuyến dã ngoại mùa xuân.\n"
    "Vui lòng chuẩn bị hộp cơm, bình nước và chiếu.\n"
    "Vui lòng nộp phí học trải nghiệm 15.000 won trước ngày 22 tháng 4.\n"
    "Vui lòng nộp giấy đồng ý trước ngày mai."
)

MOCK_QUALITY_NOTE = "ok: 권장 용어 모두 반영됨 (체험학습비, 동의서)"

MOCK_REVIEW_NEEDED = ""

MOCK_TTS_URL = ""  # 모델 연결 후 실제 URL 주입
