"""다국어 용어사전 로딩 단위 테스트.

세종 PR(`ed0a855`)의 9개 언어 wide-format CSV가 백엔드에서
target_lang에 따라 올바른 컬럼을 읽는지 검증.
"""
import sys
from pathlib import Path

import pytest

# run_mvp_pipeline.py 직접 import
_TRANSLATION_DIR = Path("/app/external_model/translation_tts")
if str(_TRANSLATION_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATION_DIR))
import run_mvp_pipeline as _sj  # noqa: E402

GLOSSARY_PATH = _TRANSLATION_DIR / "term_glossary.csv"


@pytest.mark.parametrize("lang", ["vi", "en", "zh", "th", "ja", "ru", "ms", "mn"])
def test_glossary_loads_each_language(lang):
    """각 언어 컬럼이 144개 모두 채워져있다."""
    rows = _sj.read_glossary(GLOSSARY_PATH, target_lang=lang)
    assert len(rows) == 144, f"{lang}: expected 144 rows, got {len(rows)}"
    # 최소 첫 행에 한국어/번역 둘 다 비어있지 않음
    assert rows[0]["korean"]
    assert rows[0]["preferred_vi"]  # 키 이름은 호환 위해 preferred_vi 유지


def test_glossary_korean_term_consistency():
    """vi와 en에서 같은 한국어 단어가 매칭된다 (행 정렬 동일)."""
    vi = _sj.read_glossary(GLOSSARY_PATH, target_lang="vi")
    en = _sj.read_glossary(GLOSSARY_PATH, target_lang="en")
    vi_keywords = {r["korean"] for r in vi}
    en_keywords = {r["korean"] for r in en}
    assert vi_keywords == en_keywords


def test_glossary_dosirak_mapping():
    """대표 학교 도메인 단어 '도시락'이 언어별로 다른 권장어로 매핑된다."""
    expected = {"vi": "cơm hộp", "en": "Lunch box", "zh": "便当", "ja": "お弁当"}
    for lang, want in expected.items():
        rows = _sj.read_glossary(GLOSSARY_PATH, target_lang=lang)
        match = next((r for r in rows if r["korean"] == "도시락"), None)
        assert match is not None, f"{lang}: '도시락' missing from glossary"
        assert match["preferred_vi"] == want, f"{lang}: 도시락 -> expected {want!r}, got {match['preferred_vi']!r}"


def test_find_glossary_hits_returns_target_language():
    """find_glossary_hits이 target_lang 권장어를 반환한다."""
    en_glossary = _sj.read_glossary(GLOSSARY_PATH, target_lang="en")
    text = "아이는 도시락과 물병을 가져와 주세요."
    hits = _sj.find_glossary_hits(text, en_glossary)
    assert len(hits) >= 1
    dosirak_hit = next((h for h in hits if h["korean"] == "도시락"), None)
    assert dosirak_hit is not None
    assert dosirak_hit["preferred_vi"].lower() == "lunch box"
