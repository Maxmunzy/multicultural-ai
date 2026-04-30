"""모델 연결 전 mock 응답 데이터.

extract_todos 실패/빈결과 시 fallback. 슬롯 파이프라인에서는 이 mock 도
[3] YunjeongTodo → [4] 경이님 분류 → [6] AnalyzeItem 흐름을 그대로 통과한다.
"""
from app.models.schemas import YunjeongTodo

MOCK_TODOS: list[YunjeongTodo] = [
    YunjeongTodo(
        text="현장체험학습 동의서를 내일까지 제출해주세요",
        due_date="내일",
        amount=None,
        confidence=0.95,
        action_hint="제출",
    ),
    YunjeongTodo(
        text="도시락, 개인 물병, 돗자리를 준비해주세요",
        due_date=None,
        amount=None,
        confidence=0.9,
        action_hint="준비",
    ),
    YunjeongTodo(
        text="체험학습비 15,000원을 4월 22일까지 납부해주세요",
        due_date="2026-04-22",
        amount=15000,
        confidence=0.92,
        action_hint="납부",
    ),
    YunjeongTodo(
        text="4월 25일(금) 봄 소풍이 있습니다",
        due_date="2026-04-25",
        amount=None,
        confidence=0.78,
        action_hint="참여",
    ),
    YunjeongTodo(
        text="미세먼지 심한 날에는 마스크를 착용해주세요",
        due_date=None,
        amount=None,
        confidence=0.7,
        action_hint="확인",
    ),
]
