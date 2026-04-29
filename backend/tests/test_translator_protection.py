"""URL/전화 placeholder 보호 단위 테스트.

NLLB 호출 자체는 모킹해서 마스킹 → 번역 → 복원 사이클만 검증.
실제 NLLB 모델은 무거우므로 _translate를 monkeypatch.
"""
import pytest

from app.services.translator import (
    _is_url_or_phone,
    _mask_protected_entities,
    _restore_protected_entities,
    translate_short_sentence,
    translate_term,
)


# ── 마스킹 / 복원 단위 ─────────────────────────────────────────
def test_mask_url_replaces_with_token():
    masked, holders = _mask_protected_entities("신청은 https://apply.kr 에서")
    assert "https://apply.kr" not in masked
    assert "⟦P0⟧" in masked
    assert holders == ["https://apply.kr"]


def test_mask_phone_replaces_with_token():
    masked, holders = _mask_protected_entities("문의 02-2649-7232")
    assert "02-2649-7232" not in masked
    assert "⟦P0⟧" in masked
    assert holders == ["02-2649-7232"]


def test_mask_url_and_phone_separate_tokens():
    masked, holders = _mask_protected_entities(
        "https://a.com 문의 02-1234-5678"
    )
    # 두 엔티티 각각 다른 인덱스
    assert "⟦P0⟧" in masked and "⟦P1⟧" in masked
    assert set(holders) == {"https://a.com", "02-1234-5678"}


def test_mask_no_entities_returns_text_unchanged():
    masked, holders = _mask_protected_entities("그냥 평범한 통신문")
    assert masked == "그냥 평범한 통신문"
    assert holders == []


def test_restore_returns_original_entities():
    masked, holders = _mask_protected_entities("문의 02-2649-7232")
    restored = _restore_protected_entities(masked, holders)
    assert restored == "문의 02-2649-7232"


def test_restore_with_translated_token_intact():
    """NLLB 번역 결과에도 토큰이 살아남으면 복원 가능."""
    holders = ["02-2649-7232"]
    fake_translated = "Liên hệ ⟦P0⟧"
    assert _restore_protected_entities(fake_translated, holders) == "Liên hệ 02-2649-7232"


# ── 슬롯 단위 가드 ────────────────────────────────────────────
def test_is_url_or_phone_true_for_url():
    assert _is_url_or_phone("https://example.kr/path")
    assert _is_url_or_phone("www.school.go.kr")


def test_is_url_or_phone_true_for_phone():
    assert _is_url_or_phone("02-2649-7232")
    assert _is_url_or_phone("1588-0260")


def test_is_url_or_phone_false_for_normal_text():
    assert not _is_url_or_phone("도시락")
    assert not _is_url_or_phone("5월 14일")


def test_translate_term_passthrough_for_url_phone(monkeypatch):
    """URL/전화는 어떤 언어든 번역 안 거치고 ko 그대로."""
    # glossary 호출이 일어나면 안 됨 (URL/전화 가드가 그 위에서 차단)
    called = []
    monkeypatch.setattr(
        "app.services.translator._get_glossary",
        lambda: called.append("glossary") or [],
    )
    assert translate_term("https://apply.kr", "vi") == "https://apply.kr"
    assert translate_term("02-2649-7232", "en") == "02-2649-7232"
    assert called == []


# ── translate_short_sentence E2E (NLLB 모킹) ──────────────────
def test_translate_short_sentence_protects_url_through_nllb(monkeypatch):
    """URL이 NLLB 호출 후에도 원래 문자열로 복원돼야 한다."""
    captured_input = []

    def fake_translate(text, target_nllb="vie_Latn", max_length=512):
        captured_input.append(text)
        # NLLB는 마스킹된 토큰을 그대로 통과시킨다고 가정 (실제로도 ⟦…⟧ 안 깸)
        return text.replace("문의", "Liên hệ").replace("신청은", "Đăng ký")

    monkeypatch.setattr("app.services.translator._translate", fake_translate)
    monkeypatch.setattr("app.services.translator._get_glossary", lambda: [])
    monkeypatch.setattr(
        "app.services.translator._sejong.find_glossary_hits",
        lambda text, glossary, lang: [],
    )

    out = translate_short_sentence(
        "신청은 https://apply.kr 에서, 문의 02-2649-7232",
        "vi",
    )

    # 1) NLLB에 들어간 입력엔 URL/전화가 토큰으로 마스킹됨
    assert "https://apply.kr" not in captured_input[0]
    assert "02-2649-7232" not in captured_input[0]
    assert "⟦P0⟧" in captured_input[0]

    # 2) 최종 출력엔 URL/전화가 원래 문자열로 복원됨
    assert "https://apply.kr" in out
    assert "02-2649-7232" in out
    assert "⟦P" not in out
