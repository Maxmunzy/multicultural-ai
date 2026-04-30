"""card_builder 슬롯 카드 빌드 + dedup 단위 테스트."""
from app.models.schemas import SlotCard
from app.services.card_builder import _dedup_cards


def _card(header: str, value: str, importance: float = 0.5) -> SlotCard:
    return SlotCard(
        header_ko=header,
        header_translated=header,
        value_ko=value,
        value_easy_ko=value,
        value_translated=value,
        chip=None,
        importance=importance,
    )


def test_dedup_removes_substring_within_same_header():
    """같은 헤더 안에서 짧은 value가 긴 value 안에 들어있으면 짧은 것 제거 — 본문/표 영역 중복 흡수."""
    cards = [
        _card("운영방법", "온라인 사전예약 100명 선착순 5가지 체험 안전 복장", 0.99),
        _card("운영방법", "온라인 사전예약 100명 선착순", 0.53),  # substring
    ]
    out = _dedup_cards(cards)
    assert len(out) == 1
    assert out[0].importance == 0.99  # 긴 쪽이 살아남음


def test_dedup_keeps_different_headers():
    """헤더가 다르면 손대지 않음 — 운영방법과 일시는 별개 슬롯."""
    cards = [
        _card("운영방법", "온라인 사전예약", 0.9),
        _card("일시", "2026. 4. 18.(토)", 0.7),
        _card("신청 URL", "http://example.com", 0.7),
    ]
    out = _dedup_cards(cards)
    assert len(out) == 3


def test_dedup_normalizes_pipe_and_colon_separators():
    """`|`/`:` 구분자 차이로 substring 매칭 놓치는 것 방지 — 윤정님 기호 정제 전후 둘 다 호환."""
    cards = [
        _card("운영방법", "온라인 사전예약 100명 선착순", 0.99),
        _card("운영방법", "온라인 | 사전예약 | 100명 선착순", 0.50),  # `|` 구분자만 다름
    ]
    out = _dedup_cards(cards)
    assert len(out) == 1


def test_dedup_keeps_distinct_values_under_same_header():
    """같은 헤더라도 substring 관계 아니면 둘 다 유지 — 정보 손실 방지."""
    cards = [
        _card("기타", "물 지참", 0.8),
        _card("기타", "음식물 반입 금지", 0.6),
    ]
    out = _dedup_cards(cards)
    assert len(out) == 2
