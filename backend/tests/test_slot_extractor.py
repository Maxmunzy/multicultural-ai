"""슬롯 추출기 단위 테스트.

강사 처방(2026-04-28): 날짜·시간·금액은 정규식으로 1차 안전 추출.
이 테스트가 통과한다는 건 LLM 없이도 핵심 수치 데이터가 확보된다는 자동 증명.
"""
from app.services.slot_extractor import (
    extract_amounts,
    extract_dates,
    extract_phones,
    extract_summary_regex_slots,
    extract_times,
    extract_urls,
    find_amount_in_text,
    find_deadline_in_text,
    find_when_in_text,
    format_amount,
    format_date,
    format_time,
    split_supply_tokens,
    strip_markers,
)


# ── 날짜 ─────────────────────────────────────────────────────────
def test_extract_dates_full_with_year_and_weekday():
    result = extract_dates("2026년 5월 14일(수) 출발")
    assert len(result) == 1
    d = result[0]
    assert d["year"] == 2026
    assert d["month"] == 5
    assert d["day"] == 14
    assert d["weekday"] == "수"


def test_extract_dates_md_only():
    result = extract_dates("5월 9일(금)까지 제출")
    assert len(result) == 1
    d = result[0]
    assert d["year"] is None
    assert d["month"] == 5
    assert d["day"] == 9
    assert d["weekday"] == "금"


def test_extract_dates_relative_words():
    result = extract_dates("내일까지 동의서를 제출하세요")
    assert any(d.get("relative") == "내일" for d in result)


def test_extract_dates_dedups_surface():
    result = extract_dates("5월 9일(금)까지 납부, 5월 9일(금)까지 제출")
    # 동일 표면형은 1개로
    surfaces = [d["ko"] for d in result]
    assert surfaces.count("5월 9일(금)") == 1


# ── 시간 ─────────────────────────────────────────────────────────
def test_extract_times_ampm():
    result = extract_times("오전 9시 출발")
    assert len(result) == 1
    assert result[0]["hour"] == 9
    assert result[0]["ampm"] == "오전"


def test_extract_times_with_minute():
    result = extract_times("오후 2시 30분")
    assert result[0]["hour"] == 2
    assert result[0]["minute"] == 30


def test_extract_times_24h():
    result = extract_times("회의 14:30 시작")
    assert result[0]["hour"] == 14
    assert result[0]["minute"] == 30


# ── 금액 ─────────────────────────────────────────────────────────
def test_extract_amounts_with_comma():
    result = extract_amounts("참가비 15,000원")
    assert result[0]["value"] == 15000
    assert result[0]["ko"] == "15,000원"


def test_extract_amounts_korean_unit():
    result = extract_amounts("5천원만 가져오세요")
    assert any(a["value"] == 5000 for a in result)


def test_extract_amounts_no_match():
    assert extract_amounts("그냥 평범한 통신문") == []


# ── 베트남어 포매터 ──────────────────────────────────────────────
def test_format_date_vi_with_year_weekday():
    d = {"ko": "2026년 5월 14일(수)", "year": 2026, "month": 5, "day": 14, "weekday": "수"}
    assert format_date(d, "vi") == "Ngày 14/5/2026 (Thứ Tư)"


def test_format_date_vi_md_only():
    d = {"ko": "5월 9일(금)", "year": None, "month": 5, "day": 9, "weekday": "금"}
    assert format_date(d, "vi") == "Ngày 9/5 (Thứ Sáu)"


def test_format_date_vi_relative():
    d = {"ko": "내일", "year": None, "month": None, "day": None,
         "weekday": None, "relative": "내일"}
    assert format_date(d, "vi") == "Ngày mai"


def test_format_time_vi_morning():
    t = {"ko": "오전 9시", "hour": 9, "minute": 0, "ampm": "오전"}
    assert format_time(t, "vi") == "9 giờ sáng"


def test_format_amount_vi():
    a = {"ko": "15,000원", "value": 15000, "currency": "KRW"}
    assert format_amount(a, "vi") == "15,000 won"


# ── 영어 포매터 (보조 시연용) ────────────────────────────────────
def test_format_date_en():
    d = {"ko": "5월 14일(수)", "year": None, "month": 5, "day": 14, "weekday": "수"}
    assert format_date(d, "en") == "May 14 (Wed)"


# ── URL / 전화 ───────────────────────────────────────────────────
def test_extract_urls_http_https_www():
    text = "신청은 https://example.kr/apply 에서, 자세한 내용은 www.school.go.kr 참조."
    urls = extract_urls(text)
    assert "https://example.kr/apply" in urls
    assert "www.school.go.kr" in urls


def test_extract_urls_dedupes():
    text = "http://a.com 안내 http://a.com 재공지"
    urls = extract_urls(text)
    assert urls.count("http://a.com") == 1


def test_extract_phones_dash_formats():
    text = "교무실 02-2649-7232, 학교 849-7003, 신고 1588-0260, 휴대폰 010-1234-5678"
    phones = extract_phones(text)
    assert "02-2649-7232" in phones
    assert "849-7003" in phones
    assert "1588-0260" in phones
    assert "010-1234-5678" in phones


def test_extract_phones_does_not_match_amount_with_comma():
    """'15,000원' 같은 숫자에서 전화번호가 잘못 잡히면 안 됨."""
    text = "참가비 15,000원, 문의 02-1234-5678"
    phones = extract_phones(text)
    assert "02-1234-5678" in phones
    assert not any(p.startswith("15") or p.startswith("000") for p in phones)


# ── 통합 진입점 ──────────────────────────────────────────────────
def test_extract_summary_regex_slots_full_flow():
    text = "5월 14일(수) 오전 9시 출발. 참가비 15,000원."
    out = extract_summary_regex_slots(text, "vi")
    assert any(d["ko"] == "5월 14일(수)" for d in out["dates"])
    assert all(d["source"] == "regex" for d in out["dates"])
    assert any(t["ko"] == "오전 9시" for t in out["times"])
    assert any(a["ko"] == "15,000원" for a in out["amounts"])


def test_extract_summary_regex_slots_includes_urls_and_phones():
    """summary 슬롯에 urls/phones가 ko 그대로 통과 (NLLB 안 거침)."""
    text = "신청 https://apply.school.kr 문의 02-2649-7232"
    out = extract_summary_regex_slots(text, "vi")
    assert any(u["ko"] == "https://apply.school.kr" for u in out["urls"])
    assert any(p["ko"] == "02-2649-7232" for p in out["phones"])
    # 보호: translated가 ko와 동일해야 한다
    for slot in out["urls"] + out["phones"]:
        assert slot["translated"] == slot["ko"]
        assert slot["source"] == "regex"


def test_find_when_combines_date_and_time():
    when = find_when_in_text("5월 14일(수) 오전 9시 출발", "vi")
    assert "Ngày 14/5" in when
    assert "9 giờ sáng" in when


def test_find_amount_returns_korean_surface():
    assert find_amount_in_text("참가비 15,000원", "vi") == "15,000원"


def test_find_deadline_phrase_with_까지():
    assert "5월 9일(금)까지" in find_deadline_in_text("5월 9일(금)까지 제출")


def test_find_deadline_not_broken_by_number_comma():
    """`15,000원 (...까지...)` 의 콤마에서 잘려서 '000원...'만 잡히던 회귀 방지."""
    text = "참가비: 15,000원 (5월 9일(금)까지 스쿨뱅킹으로 납부)"
    result = find_deadline_in_text(text)
    assert result is not None
    assert "5월 9일" in result
    assert not result.lstrip().startswith("000")


# ── 마크업 strip ────────────────────────────────────────────────
def test_strip_markers_leading_bullet():
    assert strip_markers("■ 준비물: 도시락") == "준비물: 도시락"


def test_strip_markers_multiple_chars():
    assert strip_markers("▶▸ 안내사항") == "안내사항"


def test_strip_markers_preserves_inside():
    """문장 내부의 기호는 보존 (시작 부분만 제거)."""
    assert strip_markers("■ 5월 14일 - 출발") == "5월 14일 - 출발"


def test_strip_markers_no_op_when_clean():
    assert strip_markers("도시락을 준비하세요") == "도시락을 준비하세요"


# ── 준비물 토큰 분해 ─────────────────────────────────────────────
def test_split_supply_tokens_comma_separated():
    tokens = split_supply_tokens("도시락, 물통, 돗자리, 편한 운동화, 여벌 옷")
    assert "도시락" in tokens
    assert "물통" in tokens
    assert "돗자리" in tokens
    assert "편한 운동화" in tokens


def test_split_supply_tokens_strips_prefix():
    tokens = split_supply_tokens("준비물: 도시락, 물병을 준비해 주세요")
    assert "도시락" in tokens
    assert "물병" in tokens
