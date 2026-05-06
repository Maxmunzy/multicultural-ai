"""URL/전화 placeholder 보호 단위 테스트.

NLLB 호출 자체는 모킹해서 마스킹 → 번역 → 복원 사이클만 검증.
실제 NLLB 모델은 무거우므로 _translate를 monkeypatch.

토큰 형식: __SLOT0__ (ASCII 대문자+언더스코어)
  ⟦P0⟧ 형태는 NLLB SentencePiece가 ⟦⟧ 를 소실시켜 "P0"만 남아 복원 실패.
  __SLOT0__ 은 NLLB가 코드/약어로 인식해 그대로 통과.
"""
import pytest

from app.services.translator import (
    _find_glossary_hits_safe,
    _is_url_or_phone,
    _mask_protected_entities,
    _post_process_vi,
    _restore_protected_entities,
    translate_short_sentence,
    translate_term,
)


# ── 마스킹 / 복원 단위 ─────────────────────────────────────────
def test_mask_url_replaces_with_token():
    masked, holders = _mask_protected_entities("신청은 https://apply.kr 에서")
    assert "https://apply.kr" not in masked
    assert "__SLOT0__" in masked
    assert holders == ["https://apply.kr"]


def test_mask_phone_replaces_with_token():
    masked, holders = _mask_protected_entities("문의 02-2649-7232")
    assert "02-2649-7232" not in masked
    assert "__SLOT0__" in masked
    assert holders == ["02-2649-7232"]


def test_mask_url_and_phone_separate_tokens():
    masked, holders = _mask_protected_entities(
        "https://a.com 문의 02-1234-5678"
    )
    assert "__SLOT0__" in masked and "__SLOT1__" in masked
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
    fake_translated = "Liên hệ __SLOT0__"
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
    assert "__SLOT0__" in captured_input[0]

    # 2) 최종 출력엔 URL/전화가 원래 문자열로 복원됨
    assert "https://apply.kr" in out
    assert "02-2649-7232" in out
    assert "__SLOT" not in out


# ── 날짜/시간/금액 슬롯 마스킹 단위 ──────────────────────────────
def test_mask_date_protected_with_target_lang():
    """날짜가 vi 포맷으로 치환되고 NLLB 입력에서 격리된다."""
    masked, holders = _mask_protected_entities("5월 9일(금)까지 제출해 주세요", "vi")
    assert "5월 9일(금)" not in masked
    assert "__SLOT0__" in masked
    assert holders[0] == "Ngày 9/5 (Thứ Sáu)"


def test_mask_time_protected_with_target_lang():
    """시간 표현이 vi 포맷으로 치환된다."""
    masked, holders = _mask_protected_entities("오전 9시부터 시작합니다", "vi")
    assert "오전 9시" not in masked
    assert "__SLOT0__" in masked
    assert holders[0] == "9 giờ sáng"


def test_mask_amount_protected_with_target_lang():
    """금액 표현이 vi 포맷으로 치환된다."""
    masked, holders = _mask_protected_entities("참가비 15,000원을 납부해 주세요", "vi")
    assert "15,000원" not in masked
    assert "__SLOT0__" in masked
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
    assert len(holders) >= 2
    assert any("Ngày" in h for h in holders)


def test_mask_already_placeholder_not_re_extracted():
    """먼저 마스킹된 URL placeholder를 날짜/시간/금액 추출이 오탐하지 않는다."""
    text = "https://apply.kr 에서 5월 9일(금)까지 신청"
    masked, holders = _mask_protected_entities(text, "vi")
    assert "https://apply.kr" not in masked
    assert "5월 9일(금)" not in masked
    # 토큰 개수 = placeholder 개수
    assert masked.count("__SLOT") == len(holders)
    assert len(holders) == 2


# ── translate_short_sentence NLLB 입력/출력 보호 검증 ─────────────
def test_translate_short_sentence_protects_date(monkeypatch):
    """날짜가 NLLB 입력에 안 들어가고 최종 출력엔 vi 포맷으로 복원된다."""
    captured = []

    def fake_translate(text, target_nllb="vie_Latn", max_length=512):
        captured.append(text)
        return text  # identity — __SLOT0__ 토큰이 그대로 통과

    monkeypatch.setattr("app.services.translator._translate", fake_translate)
    monkeypatch.setattr("app.services.translator._get_glossary", lambda: [])

    out = translate_short_sentence("5월 9일(금)까지 제출해 주세요", "vi")

    assert captured, "fake_translate가 호출되지 않음"
    assert "5월 9일(금)" not in captured[0]
    assert "__SLOT0__" in captured[0]
    assert "Ngày 9/5 (Thứ Sáu)" in out
    assert "__SLOT" not in out


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
    assert "__SLOT0__" in captured[0]
    assert "9 giờ sáng" in out
    assert "__SLOT" not in out


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
    assert "__SLOT0__" in captured[0]
    assert "15,000 won" in out
    assert "__SLOT" not in out


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
    assert "__SLOT" not in out


# ── 1글자 glossary 가드 및 공백 normalize ──────────────────────
def test_glossary_single_char_guard():
    """1글자 korean 키는 glossary hit에서 제외된다."""
    glossary = [
        {"korean": "원", "preferred_vi": "won"},
        {"korean": "반", "preferred_vi": "lớp"},
        {"korean": "학생", "preferred_vi": "học sinh"},
    ]
    hits = _find_glossary_hits_safe("반드시 학생이 원문을 제출", glossary, "vi")
    koreans = [h["korean"] for h in hits]
    assert "원" not in koreans
    assert "반" not in koreans
    assert "학생" in koreans


def test_glossary_whitespace_normalize():
    """'담임 선생님'과 '담임선생님'이 공백 관계없이 같은 키로 매칭된다."""
    glossary = [
        {"korean": "담임선생님", "preferred_vi": "giáo viên chủ nhiệm"},
    ]
    hits_space = _find_glossary_hits_safe("담임 선생님께 제출해주세요", glossary, "vi")
    hits_nospace = _find_glossary_hits_safe("담임선생님께 제출해주세요", glossary, "vi")
    assert len(hits_space) == 1
    assert len(hits_nospace) == 1
    assert hits_space[0]["preferred_term"] == "giáo viên chủ nhiệm"


# ── 날짜 + 금액 동시 보호 ──────────────────────────────────────
def test_mask_date_and_amount_together():
    """날짜와 금액이 함께 있을 때 각각 독립적으로 격리된다."""
    text = "4월 30일(화)까지 참가비 15,000원을 납부해 주세요"
    masked, holders = _mask_protected_entities(text, "vi")
    assert "4월 30일(화)" not in masked
    assert "15,000원" not in masked
    assert len(holders) == 2
    assert any("Ngày" in h for h in holders)
    assert any("won" in h for h in holders)
    assert masked.count("__SLOT") == 2


# ── 베트남어 후처리 패턴 ──────────────────────────────────────
def test_post_process_vi_student_correction():
    """학생 맥락에서 sinh viên → học sinh 교정이 일어난다."""
    result = _post_process_vi("학생이 제출해야 합니다", "sinh viên phải nộp")
    assert "học sinh" in result
    assert "sinh viên" not in result


def test_post_process_vi_homeroom_correction():
    """담임선생님 맥락에서 giáo viên giám đốc → giáo viên chủ nhiệm 교정."""
    result = _post_process_vi("담임선생님께 제출하세요", "nộp cho giáo viên giám đốc")
    assert "giáo viên chủ nhiệm" in result


# ── 100자 trim 안전성 ──────────────────────────────────────────
def test_trim_does_not_discard_early_slot(monkeypatch):
    """100자 이내에 있는 날짜+금액은 trim 후에도 보호되고 복원된다."""
    captured = []

    def fake_translate(text, target_nllb="vie_Latn", max_length=512):
        captured.append(text)
        return text  # identity — __SLOT 토큰이 그대로 통과

    monkeypatch.setattr("app.services.translator._translate", fake_translate)
    monkeypatch.setattr("app.services.translator._get_glossary", lambda: [])

    out = translate_short_sentence("5월 9일(금)까지 참가비 15,000원 납부", "vi")

    assert captured, "fake_translate가 호출되지 않음"
    assert "5월 9일(금)" not in captured[0]
    assert "15,000원" not in captured[0]
    assert "__SLOT" not in out
    assert "Ngày" in out
    assert "won" in out
