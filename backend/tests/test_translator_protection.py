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


# ── 날짜/시간/금액 슬롯 마스킹 단위 ──────────────────────────────
def test_mask_date_protected_with_target_lang():
    """날짜가 vi 포맷으로 치환되고 NLLB 입력에서 격리된다."""
    masked, holders = _mask_protected_entities("5월 9일(금)까지 제출해 주세요", "vi")
    assert "5월 9일(금)" not in masked
    assert "⟦P0⟧" in masked
    assert holders[0] == "Ngày 9/5 (Thứ Sáu)"


def test_mask_time_protected_with_target_lang():
    """시간 표현이 vi 포맷으로 치환된다."""
    masked, holders = _mask_protected_entities("오전 9시부터 시작합니다", "vi")
    assert "오전 9시" not in masked
    assert "⟦P0⟧" in masked
    assert holders[0] == "9 giờ sáng"


def test_mask_amount_protected_with_target_lang():
    """금액 표현이 vi 포맷으로 치환된다."""
    masked, holders = _mask_protected_entities("참가비 15,000원을 납부해 주세요", "vi")
    assert "15,000원" not in masked
    assert "⟦P0⟧" in masked
    assert holders[0] == "15,000 won"


def test_mask_no_slot_protection_without_target_lang():
    """target_lang 없이 호출하면 날짜/시간/금액은 보호하지 않는다 (URL/전화만)."""
    masked, holders = _mask_protected_entities("5월 9일(금)까지 제출해 주세요")
    assert "5월 9일(금)" in masked
    assert holders == []


def test_mask_date_time_no_overlap():
    """날짜+시간이 같이 있을 때 중복 없이 각각 격리된다."""
    text = "2026년 5월 6일(목) 8:50 ~ 14:40"
    masked, holders = _mask_protected_entities(text, "vi")
    assert "2026년 5월 6일(목)" not in masked
    assert "8:50" not in masked
    assert "14:40" not in masked
    # 날짜 1개 + 시간 2개 = 3개 이상의 placeholder
    assert len(holders) >= 2
    assert any("Ngày" in h for h in holders)


def test_mask_already_placeholder_not_re_extracted():
    """먼저 마스킹된 URL placeholder를 날짜/시간/금액 추출이 오탐하지 않는다."""
    text = "https://apply.kr 에서 5월 9일(금)까지 신청"
    masked, holders = _mask_protected_entities(text, "vi")
    # URL + 날짜 둘 다 보호
    assert "https://apply.kr" not in masked
    assert "5월 9일(금)" not in masked
    # placeholder 토큰 자체가 다시 추출되면 안 됨
    assert masked.count("⟦P") == masked.count("⟧")
    assert len(holders) == 2


# ── translate_short_sentence NLLB 입력/출력 보호 검증 ─────────────
def test_translate_short_sentence_protects_date(monkeypatch):
    """날짜가 NLLB 입력에 안 들어가고 최종 출력엔 vi 포맷으로 복원된다."""
    captured = []

    def fake_translate(text, target_nllb="vie_Latn", max_length=512):
        captured.append(text)
        return text  # identity — ⟦P0⟧ 토큰이 그대로 통과

    monkeypatch.setattr("app.services.translator._translate", fake_translate)
    monkeypatch.setattr("app.services.translator._get_glossary", lambda: [])

    out = translate_short_sentence("5월 9일(금)까지 제출해 주세요", "vi")

    assert captured, "fake_translate가 호출되지 않음"
    assert "5월 9일(금)" not in captured[0]
    assert "⟦P0⟧" in captured[0]
    assert "Ngày 9/5 (Thứ Sáu)" in out
    assert "⟦P" not in out


def test_translate_short_sentence_protects_time(monkeypatch):
    """시간이 NLLB 입력에 안 들어가고 최종 출력엔 vi 포맷으로 복원된다."""
    captured = []

    def fake_translate(text, target_nllb="vie_Latn", max_length=512):
        captured.append(text)
        return text

    monkeypatch.setattr("app.services.translator._translate", fake_translate)
    monkeypatch.setattr("app.services.translator._get_glossary", lambda: [])

    out = translate_short_sentence("오전 9시부터 시작합니다", "vi")

    assert captured
    assert "오전 9시" not in captured[0]
    assert "⟦P0⟧" in captured[0]
    assert "9 giờ sáng" in out
    assert "⟦P" not in out


def test_translate_short_sentence_protects_amount(monkeypatch):
    """금액이 NLLB 입력에 안 들어가고 최종 출력엔 vi 포맷으로 복원된다."""
    captured = []

    def fake_translate(text, target_nllb="vie_Latn", max_length=512):
        captured.append(text)
        return text

    monkeypatch.setattr("app.services.translator._translate", fake_translate)
    monkeypatch.setattr("app.services.translator._get_glossary", lambda: [])

    out = translate_short_sentence("참가비 15,000원을 납부해 주세요", "vi")

    assert captured
    assert "15,000원" not in captured[0]
    assert "⟦P0⟧" in captured[0]
    assert "15,000 won" in out
    assert "⟦P" not in out


def test_translate_short_sentence_en_date_format(monkeypatch):
    """en 타깃에서는 날짜가 영어 포맷으로 복원된다."""
    captured = []

    def fake_translate(text, target_nllb="eng_Latn", max_length=512):
        captured.append(text)
        return text

    monkeypatch.setattr("app.services.translator._translate", fake_translate)
    monkeypatch.setattr("app.services.translator._get_glossary", lambda: [])

    out = translate_short_sentence("5월 9일(금)까지 제출해 주세요", "en")

    assert captured
    assert "5월 9일(금)" not in captured[0]
    assert "May 9 (Fri)" in out or "May 9" in out
    assert "⟦P" not in out
