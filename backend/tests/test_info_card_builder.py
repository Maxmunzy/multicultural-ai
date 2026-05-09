from app.services.info_card_builder import (
    build_info_cards_from_sentence_document,
    is_nllb_skip_value,
)
from app.services.sentence_skeleton import raw_text_to_sentence_list


def test_build_info_cards_from_sentence_document():
    doc = raw_text_to_sentence_list(
        "\n".join([
            "2026년 5월 서귀포외국문화학습관 토요프로그램 추가모집 안내",
            "대 상: 초등학생 3·4학년 8명 모집",
            "수강신청 2026. 4. 21.(화) 10:00 ~ 4. 24.(금) 24:00",
            "운영일시 2026. 5. 9.(토) 10:00 ~ 12:00",
            "문의: 064-767-9811~5",
            "신청 URL: https://org.jje.go.kr/jiei/index.jje",
        ])
    )

    cards = build_info_cards_from_sentence_document(doc, "vi")

    by_header = {card.header_ko: card.value_ko for card in cards}
    assert by_header["대상"] == "초등학생 3·4학년 8명 모집"
    assert by_header["신청기간"].startswith("2026. 4. 21.")
    assert by_header["운영일시"].startswith("2026. 5. 9.")
    assert by_header["문의"] == "064-767-9811~5"
    assert by_header["신청 URL"] == "https://org.jje.go.kr/jiei/index.jje"


def test_url_and_phone_are_not_nllb_translated():
    doc = raw_text_to_sentence_list(
        "\n".join([
            "문의: 064-767-9811~5",
            "신청 URL: https://org.jje.go.kr/jiei/index.jje",
        ])
    )

    cards = build_info_cards_from_sentence_document(doc, "vi")

    for card in cards:
        assert card.value_translated == card.value_ko


def test_date_time_fragment_skips_nllb():
    assert is_nllb_skip_value("23.(토) / 13:00 ~ 15:00", "event_datetime")
    assert is_nllb_skip_value("13:00 ~ 15:00", "event_datetime")


def test_activity_content_preserved_as_info_card():
    """활동 내용/체험 내용 헤더가 info_card로 보존되는지 검증."""
    doc = raw_text_to_sentence_list(
        "\n".join([
            "해조류박람회 체험학습 안내",
            "일시: 2026년 5월 6일(목) 8:50~14:40",
            "장소: 해조류박람회 및 빙그레 시네마",
            "활동 내용: 해조류박람회 및 빙그레 시네마 체험",
            "준비물: 도시락, 물통",
        ])
    )

    cards = build_info_cards_from_sentence_document(doc, "vi")
    headers = [c.header_ko for c in cards]

    assert "활동 내용" in headers, f"활동 내용 info_card 누락. headers={headers}"
    content_card = next(c for c in cards if c.header_ko == "활동 내용")
    assert "해조류박람회" in content_card.value_ko
