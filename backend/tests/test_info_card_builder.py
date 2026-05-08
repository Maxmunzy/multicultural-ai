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
