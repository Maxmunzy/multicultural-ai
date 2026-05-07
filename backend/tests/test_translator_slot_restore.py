from app.services.translator import _restore_protected_entities


def test_restore_with_nllb_mixed_case_token():
    holders = ["Ngày 17/3 (Thứ Sáu)", "19:00~20:00"]
    fake_translated = "Khac: den __Slot0__. ZOOM luc __SLOt1__."

    restored = _restore_protected_entities(fake_translated, holders)

    assert "Ngày 17/3 (Thứ Sáu)" in restored
    assert "19:00~20:00" in restored
    assert "__Slot" not in restored
    assert "__SLOt" not in restored


def test_restore_with_spaces_inside_token():
    holders = ["https://bit.ly/example"]

    restored = _restore_protected_entities("Dang ky tai __ SLOT 0 __.", holders)

    assert restored == "Dang ky tai https://bit.ly/example."


def test_restore_removes_unknown_slot_token():
    holders = ["Ngay 17/3"]

    restored = _restore_protected_entities("Den __Slot9__ vao __Slot0__.", holders)

    assert "__Slot9__" not in restored
    assert "Ngay 17/3" in restored
