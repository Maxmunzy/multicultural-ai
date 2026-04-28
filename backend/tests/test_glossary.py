"""다국어 용어사전 로딩 단위 테스트.

세종 PR 리팩토링 반영(2026-04-28):
- read_glossary(path)는 raw rows 반환 (target_lang 파라미터 제거)
- 언어별 분기는 find_glossary_hits(text, glossary, lang)에서 처리
- 반환 dict 키: preferred_vi → preferred_term (generic)
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


def test_glossary_loads_raw_rows():
    """read_glossary(path)는 144행 raw rows를 반환한다."""
    rows = _sj.read_glossary(GLOSSARY_PATH)
    assert len(rows) == 144
    # 한국어 컬럼은 비어있지 않음
    assert rows[0]["korean"]


@pytest.mark.parametrize("lang", ["vi", "en", "zh", "th", "ja", "ru", "ms", "mn"])
def test_glossary_each_language_column_filled(lang):
    """각 언어 preferred_{lang} 컬럼이 144행 모두 채워져있다."""
    rows = _sj.read_glossary(GLOSSARY_PATH)
    column = f"preferred_{lang}"
    filled = [r for r in rows if r.get(column, "").strip()]
    assert len(filled) == 144, f"{lang}: expected 144 filled, got {len(filled)}"


def test_glossary_dosirak_mapping():
    """대표 학교 도메인 단어 '도시락'이 언어별로 다른 권장어로 매핑된다."""
    expected = {"vi": "cơm hộp", "en": "Lunch box", "zh": "便当", "ja": "お弁당"}
    rows = _sj.read_glossary(GLOSSARY_PATH)
    dosirak = next((r for r in rows if r["korean"] == "도시락"), None)
    assert dosirak is not None, "'도시락' 누락"
    for lang, want in expected.items():
        # Note: ja 'お弁당' 표기 차이로 일본어는 startswith 비교
        actual = dosirak.get(f"preferred_{lang}", "").strip()
        if lang == "ja":
            assert actual.startswith("お弁") or actual.startswith("弁当"), f"ja: {actual!r}"
        else:
            assert actual == want, f"{lang}: expected {want!r}, got {actual!r}"


def test_find_glossary_hits_returns_target_language():
    """find_glossary_hits이 target_lang 권장어를 preferred_term 키로 반환한다."""
    glossary = _sj.read_glossary(GLOSSARY_PATH)
    text = "아이는 도시락과 물병을 가져와 주세요."

    en_hits = _sj.find_glossary_hits(text, glossary, "en")
    en_dosirak = next((h for h in en_hits if h["korean"] == "도시락"), None)
    assert en_dosirak is not None
    assert en_dosirak["preferred_term"].lower() == "lunch box"

    vi_hits = _sj.find_glossary_hits(text, glossary, "vi")
    vi_dosirak = next((h for h in vi_hits if h["korean"] == "도시락"), None)
    assert vi_dosirak is not None
    assert vi_dosirak["preferred_term"] == "cơm hộp"


def test_find_glossary_hits_empty_text():
    """본문에 사전 용어가 없으면 빈 리스트 반환."""
    glossary = _sj.read_glossary(GLOSSARY_PATH)
    hits = _sj.find_glossary_hits("아무 학교 용어 없음", glossary, "vi")
    assert hits == []
