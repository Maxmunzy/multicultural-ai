"""세종님 NLLB 번역 + 용어 검수 wrapper.

run_mvp_pipeline.py의 가벼운 함수들(easy_korean, glossary)은 직접 호출.
NLLB 번역은 매번 모델 새로 로드하지 않게 캐싱.
"""
import re
import sys
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

_TRANSLATION_DIR = Path("/app/external_model/translation_tts")
if str(_TRANSLATION_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATION_DIR))

import run_mvp_pipeline as _sejong  # noqa: E402

NLLB_MODEL_NAME = "facebook/nllb-200-distilled-600M"
SOURCE_LANG = "kor_Hang"

# 안드 언어 코드 → NLLB FLORES-200 코드
LANG_TO_NLLB = {
    "vi": "vie_Latn",
    "en": "eng_Latn",
    "ru": "rus_Cyrl",
    "ms": "zsm_Latn",
    "mn": "khk_Cyrl",
    "zh": "zho_Hans",
    "th": "tha_Thai",
    "ja": "jpn_Jpan",
}

_tokenizer = None
_model = None
# 사전 raw rows 단일 캐시. 언어별 분기는 find_glossary_hits 호출 시 target_lang 인자로 처리.
_glossary_rows: list | None = None


def _get_translator():
    global _tokenizer, _model
    if _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL_NAME, src_lang=SOURCE_LANG)
        _model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL_NAME)
        _model.eval()
    return _tokenizer, _model


def _get_glossary():
    """raw 사전 rows를 1회 로드. 언어별 컬럼 선택은 find_glossary_hits에서 처리."""
    global _glossary_rows
    if _glossary_rows is None:
        try:
            _glossary_rows = _sejong.read_glossary(_TRANSLATION_DIR / "term_glossary.csv")
        except Exception as error:
            print(f"[translator] glossary load failed: {error}")
            _glossary_rows = []
    return _glossary_rows


def _translate(text: str, target_nllb: str = "vie_Latn", max_length: int = 512) -> str:
    tokenizer, model = _get_translator()
    target_id = tokenizer.convert_tokens_to_ids(target_nllb)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_length)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            forced_bos_token_id=target_id,
            max_length=max_length,
            num_beams=4,
            no_repeat_ngram_size=3,
            repetition_penalty=1.3,
            early_stopping=True,
        )
    return tokenizer.batch_decode(out, skip_special_tokens=True)[0]


# 한국어 원문 → 베트남어 번역 결과의 명백한 오번역 강제 치환.
# NLLB가 학교 도메인을 못 배워서 발생하는 시각적 결함을 시연 전에 막는 안전망.
_CURRENCY_PATTERNS = [
    re.compile(r"\bđô\s*la\b", re.IGNORECASE),
    re.compile(r"\bdollars?\b", re.IGNORECASE),
    re.compile(r"\bUSD\b"),
]
# 천단위 점(40.000) → 콤마(40,000). 베트남식 표기지만 한국 학부모는 "40원"으로 오인할 수 있음.
_THOUSAND_DOT = re.compile(r"(\d{1,3}(?:\.\d{3})+)")


def _normalize_thousand_separator(text: str) -> str:
    def repl(m):
        return m.group(1).replace(".", ",")
    return _THOUSAND_DOT.sub(repl, text)


def _post_process_vi(easy_ko: str, vi_text: str) -> str:
    if not vi_text:
        return vi_text
    if "원" in easy_ko:
        for pat in _CURRENCY_PATTERNS:
            vi_text = pat.sub("won", vi_text)
        vi_text = _normalize_thousand_separator(vi_text)
    return vi_text


def translate_term(text: str, target_lang: str) -> str:
    """glossary 직접 치환 (summary 슬롯용 — places, supplies, deadlines).

    exact match 우선. 없으면 한국어 원문 그대로 반환 (빈 문자열 금지).
    고유명사("서울숲 생태체험관")처럼 사전에 없으면 한국어 노출이 NLLB 오역보다 낫다.
    """
    if not text or not text.strip():
        return text
    if target_lang == "ko_easy":
        return text

    glossary = _get_glossary()
    term = text.strip()
    for row in glossary:
        if row.get("korean", "").strip() == term:
            translated = row.get(f"preferred_{target_lang}", "").strip()
            if translated:
                return translated
    return text  # Korean passthrough


def translate_short_sentence(text: str, target_lang: str) -> str:
    """짧은 문장 NLLB 번역 (items[].title_translated용).

    glossary injection → NLLB → vi post-process.
    실패 시 빈 문자열 반환 (호출부가 fallback 처리).
    """
    if not text or not text.strip():
        return ""
    if target_lang == "ko_easy":
        return text

    glossary = _get_glossary()
    hits = _sejong.find_glossary_hits(text, glossary, target_lang)

    # 긴 용어 먼저 치환해야 부분 치환 충돌 방지
    injected = text
    for hit in sorted(hits, key=lambda h: len(h["korean"]), reverse=True):
        injected = injected.replace(
            hit["korean"], f"{hit['korean']}({hit['preferred_term']})"
        )

    target_nllb = LANG_TO_NLLB.get(target_lang, "vie_Latn")
    try:
        translated = _translate(injected, target_nllb=target_nllb)
        if target_lang == "vi":
            translated = _post_process_vi(text, translated)
    except Exception as error:
        print(f"[translator] translate_short_sentence failed: {error}")
        return ""

    return translated


# DEPRECATED: 아래 함수는 단일 blob 번역 구조. 새 API(translate_term / translate_short_sentence)로 전환 후 제거 예정.
def translate_and_review(notice_text: str, target_lang: str = "vi") -> dict:
    """[DEPRECATED] 가정통신문 → easy_ko + 다국어 번역 + 용어 검수 결과.

    슬롯 기반 응답(summary + items)으로 전환 후 호출부 없음. 다음 PR에서 제거 예정.
    신규 호출은 translate_term / translate_short_sentence 사용.
    """
    empty = {
        "easy_ko_text": "",
        "translation": "",
        "target_language": target_lang,
        "vi_text": "",
        "quality_note": "",
        "review_needed": "",
    }
    if not notice_text or not notice_text.strip():
        return empty

    source = {"easy_ko_text": "", "easy_korean": "", "original_text": notice_text}
    baseline = {"original_text": notice_text}

    try:
        easy_ko_text = _sejong.prepare_easy_ko_text(
            _sejong.build_easy_korean(source, baseline)
        )
    except Exception as error:
        print(f"[translator] easy_ko failed: {error}")
        easy_ko_text = notice_text

    if not easy_ko_text:
        return empty

    # ko_easy는 한국어 자체라 사전 검수 무의미 → 빈 hits
    if target_lang == "ko_easy":
        glossary_hits = []
    else:
        glossary = _get_glossary()
        glossary_hits = _sejong.find_glossary_hits(easy_ko_text, glossary, target_lang)

    # ko_easy: 번역 없이 easy_ko_text를 그대로 사용
    if target_lang == "ko_easy":
        rows = _sejong.build_glossary_check_rows(easy_ko_text, "", glossary_hits)
        label, note = _sejong.summarize_quality(rows)
        return {
            "easy_ko_text": easy_ko_text,
            "translation": "",
            "target_language": "ko_easy",
            "vi_text": "",
            "quality_note": note if note else f"ok ({label})",
            "review_needed": note if label == "review_needed" else "",
        }

    target_nllb = LANG_TO_NLLB.get(target_lang, "vie_Latn")
    try:
        translated = _translate(easy_ko_text, target_nllb=target_nllb)
        if target_lang == "vi":
            translated = _post_process_vi(easy_ko_text, translated)
    except Exception as error:
        print(f"[translator] translate failed: {error}")
        translated = ""

    rows = _sejong.build_glossary_check_rows(easy_ko_text, translated, glossary_hits)
    label, note = _sejong.summarize_quality(rows)

    return {
        "easy_ko_text": easy_ko_text,
        "translation": translated,
        "target_language": target_lang,
        # 호환: vi_text는 vi 선택 시만 채움 (안드 기존 fallback 동작)
        "vi_text": translated if target_lang == "vi" else "",
        "quality_note": note if note else f"ok ({label})",
        "review_needed": note if label == "review_needed" else "",
    }

