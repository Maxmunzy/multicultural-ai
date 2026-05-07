from app.models.schemas import OcrCorrectionEntry
from app.services.ocr_slot_corrector import (
    apply_ocr_slot_corrections,
    find_ocr_slot_corrections,
)


def test_correct_amount_confusables_inside_amount_slot():
    corrected, changes = apply_ocr_slot_corrections("체험학습비는 44,B70완입니다.")

    assert corrected == "체험학습비는 44,870원입니다."
    assert changes[0]["slot_type"] == "amount"
    assert changes[0]["raw_text"] == "44,B70완"
    assert changes[0]["corrected_text"] == "44,870원"


def test_correct_time_confusables_inside_time_slot():
    corrected, changes = apply_ocr_slot_corrections("일시: 8:5O ~ 14:4O")

    assert corrected == "일시: 8:50 ~ 14:40"
    assert [c["slot_type"] for c in changes] == ["time", "time"]
    assert all(c["review_required"] is False for c in changes)


def test_correct_date_and_weekday_confusables():
    corrected, changes = apply_ocr_slot_corrections("5원 6일(묵)까지 제출")

    assert corrected == "5월 6일(목)까지 제출"
    assert [c["slot_type"] for c in changes] == ["date", "weekday"]


def test_correct_grade_and_class_confusables():
    corrected, changes = apply_ocr_slot_corrections("대상: l-6확년, 3밤")

    assert corrected == "대상: 1-6학년, 3반"
    assert [c["slot_type"] for c in changes] == ["grade", "class"]


def test_correct_phone_confusables_inside_phone_slot():
    corrected, changes = apply_ocr_slot_corrections("문의: O10-1234-567S")

    assert corrected == "문의: 010-1234-5675"
    assert changes[0]["slot_type"] == "phone"


def test_does_not_globally_replace_confusables():
    corrected, changes = apply_ocr_slot_corrections("B반 학생은 OpenClass로 이동")

    assert corrected == "B반 학생은 OpenClass로 이동"
    assert changes == []


def test_invalid_time_is_marked_for_review():
    changes = find_ocr_slot_corrections("일시: 28:7O")

    assert changes[0].slot_type == "time"
    assert changes[0].corrected_text == "28:70"
    assert changes[0].review_required is True


# ── OcrCorrectionEntry 필드 매핑 ─────────────────────────────────────────────

def test_ocr_correction_entry_fields_from_dict():
    """apply_ocr_slot_corrections 결과를 OcrCorrectionEntry로 변환할 수 있어야 한다."""
    _, changes = apply_ocr_slot_corrections("44,B70완")
    entry = OcrCorrectionEntry(**{k: v for k, v in changes[0].items()
                                  if k in OcrCorrectionEntry.model_fields})
    assert entry.slot_type == "amount"
    assert entry.raw_text == "44,B70완"
    assert entry.corrected_text == "44,870원"
    assert entry.review_required is False


def test_has_review_required_false_when_all_clean():
    _, changes = apply_ocr_slot_corrections("일시: 8:5O")
    entries = [OcrCorrectionEntry(**{k: v for k, v in c.items()
                                     if k in OcrCorrectionEntry.model_fields})
               for c in changes]
    assert any(e.review_required for e in entries) is False


def test_has_review_required_true_when_invalid_slot():
    corrections = find_ocr_slot_corrections("일시: 28:7O")
    entries = [OcrCorrectionEntry(
        slot_type=c.slot_type,
        raw_text=c.raw_text,
        corrected_text=c.corrected_text,
        reason=c.reason,
        review_required=c.review_required,
    ) for c in corrections]
    assert any(e.review_required for e in entries) is True


def test_no_corrections_when_text_is_clean():
    corrected, changes = apply_ocr_slot_corrections("5월 6일(목) 9:00, 문의 010-1234-5678")
    assert corrected == "5월 6일(목) 9:00, 문의 010-1234-5678"
    assert changes == []


# ── 구상서 confusable 추가 케이스 ─────────────────────────────────────────────

def test_weekday_confusable_금():
    corrected, changes = apply_ocr_slot_corrections("5월 6일(귬)에 제출")
    assert corrected == "5월 6일(금)에 제출"
    assert changes[0]["slot_type"] == "weekday"


def test_mixed_complex_sentence():
    """복합 문장 — 날짜/시간/금액/전화 동시 보정."""
    text = "5원 9일(묵) 8:5O까지 15,OOO완 납부, 문의 O2-1234-567S"
    corrected, changes = apply_ocr_slot_corrections(text)
    assert "5월 9일" in corrected
    assert "(목)" in corrected
    assert "8:50" in corrected
    assert "15,000원" in corrected
    assert "02-1234-5675" in corrected
    assert len(changes) >= 4


def test_grade_range_confusable():
    corrected, changes = apply_ocr_slot_corrections("대상: l~6확년")
    assert "1" in corrected
    assert "학년" in corrected
