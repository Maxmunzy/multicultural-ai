import json

from app.services.sentence_skeleton import (
    build_gemini_sentence_list_prompt,
    normalize_header,
    parse_sentence_list_payload,
    raw_text_to_sentence_list,
)


def test_normalize_spaced_headers():
    assert normalize_header("대 상") == "대상"
    assert normalize_header("신 청 URL") == "신청 URL"
    assert normalize_header("연 락 처") == "연락처"
    assert normalize_header("운 영 일 시") == "운영일시"


def test_parse_sentence_list_payload_contract():
    payload = {
        "document_title": "2026년 5월 서귀포외국문화학습관 토요프로그램 추가모집 안내",
        "sentence_list": [
            {
                "sentence_id": "s001",
                "text": "대상: 초등학생 3·4학년 8명 모집",
                "section": "토요영어체험교실",
                "section_type": "program",
                "role_hint": "target",
                "is_action_candidate": False,
                "contains_slots": ["target"],
                "source_order": 1,
            }
        ],
    }

    doc = parse_sentence_list_payload(json.dumps(payload, ensure_ascii=False))

    assert doc.document_title.startswith("2026년")
    assert doc.sentence_list[0].role_hint == "target"


def test_raw_text_to_sentence_list_fallback_roles():
    doc = raw_text_to_sentence_list(
        "\n".join([
            "2026년 5월 서귀포외국문화학습관 토요프로그램 추가모집 안내",
            "대 상: 초등학생 3·4학년 8명 모집",
            "수강신청 2026. 4. 21.(화) 10:00 ~ 4. 24.(금) 24:00",
            "운영일시 2026. 5. 9.(토) 10:00 ~ 12:00",
            "문의: 064-767-9811~5",
        ])
    )

    roles = [item.role_hint for item in doc.sentence_list]
    assert "target" in roles
    assert "application_period" in roles
    assert "event_datetime" in roles
    assert "contact" in roles


def test_prompt_is_sentence_list_not_summary():
    prompt = build_gemini_sentence_list_prompt("문서 텍스트")

    assert "요약하지 말고" in prompt
    assert "번역하지 않는다" in prompt
    assert "JSON만 출력" in prompt
    assert "{document_text}" not in prompt
