"""세종님 NLLB 번역 + 용어 검수 wrapper.

run_mvp_pipeline.py의 가벼운 함수들(easy_korean, glossary)은 직접 호출.
NLLB 번역은 매번 모델 새로 로드하지 않게 캐싱.

URL/전화는 NLLB가 토큰화하면서 깨먹는 패턴이라 placeholder 치환 + 복원으로 보호.
세종님 요청(2026-04-29).

성능 최적화 (2026-05-06, 시연 ~10s 목표):
- num_beams 4 → 1 (greedy): -50% latency, 학교 공지 도메인은 beam 효과 미미
- @lru_cache: 분석 1번에 같은 한국어 슬롯/카드 헤더가 반복 등장 → 재호출 방지
"""
from __future__ import annotations

import re
import sys
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from app.services.unknown_terms import log_unknown
from app.services.slot_extractor import (
    _PHONE,
    _URL,
    _URL_TRAILING_JOSA,
    extract_amounts,
    extract_dates,
    extract_times,
    format_amount,
    format_date,
    format_time,
)

_TRANSLATION_DIR = Path("/app/external_model/translation_tts")
if str(_TRANSLATION_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATION_DIR))

# 외부 마운트가 없는 환경(CI/테스트)에서도 모듈 로드는 성공해야 한다.
try:
    import run_mvp_pipeline as _sejong  # noqa: E402
except ImportError as error:
    print(f"[translator] run_mvp_pipeline unavailable: {error}")
    _sejong = None

NLLB_MODEL_NAME = "facebook/nllb-200-distilled-600M"
SOURCE_LANG = "kor_Hang"
MAX_TRANSLATE_CHARS = 100

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


def _load_glossary_csv_direct() -> list:
    """run_mvp_pipeline 없이 term_glossary.csv를 직접 읽는 fallback."""
    import csv as _csv
    candidates = [
        _TRANSLATION_DIR / "term_glossary.csv",
        Path(__file__).resolve().parents[3] / "model" / "translation_tts" / "term_glossary.csv",
    ]
    for p in candidates:
        if p.exists():
            rows: list = []
            with open(p, encoding="utf-8-sig") as f:
                for row in _csv.DictReader(f):
                    rows.append(dict(row))
            return rows
    return []


def _get_glossary():
    """raw 사전 rows를 1회 로드. 언어별 컬럼 선택은 find_glossary_hits에서 처리."""
    global _glossary_rows
    if _glossary_rows is None:
        if _sejong is None:
            _glossary_rows = _load_glossary_csv_direct()
            return _glossary_rows
        try:
            _glossary_rows = _sejong.read_glossary(_TRANSLATION_DIR / "term_glossary.csv")
        except Exception as error:
            print(f"[translator] glossary load failed: {error}")
            _glossary_rows = []
    return _glossary_rows


@lru_cache(maxsize=1024)
def _translate(text: str, target_nllb: str = "vie_Latn", max_length: int = 512) -> str:
    """NLLB 호출. (text, target_nllb) 동일 입력은 캐시 히트.

    분석 1번 안에서 같은 슬롯 헤더("준비물", "비용" 등)가 cards/items/summary에
    여러 번 등장하므로 캐시 효과 큼. greedy decoding으로 단일 호출 자체도 빠름.
    """
    tokenizer, model = _get_translator()
    target_id = tokenizer.convert_tokens_to_ids(target_nllb)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_length)
    with torch.no_grad():
        # greedy(num_beams=1) — early_stopping은 beam search 전용이라 제외
        out = model.generate(
            **inputs,
            forced_bos_token_id=target_id,
            max_length=max_length,
            num_beams=1,
            no_repeat_ngram_size=3,
            repetition_penalty=1.3,
        )
    return tokenizer.batch_decode(out, skip_special_tokens=True)[0]


def _translate_batch_raw(
    texts: list[str],
    target_nllb: str = "vie_Latn",
    max_length: int = 384,
) -> list[str]:
    """NLLB batch generate — 입력 순서 그대로 번역 결과 list 반환.

    단일 호출(`_translate`) 14회 → batch 1회로 줄여 CPU 오버헤드 감축.
    tokenizer가 padding=True로 가장 긴 문장에 맞춰 패드 → 한 번의 forward 통과.
    """
    if not texts:
        return []
    tokenizer, model = _get_translator()
    target_id = tokenizer.convert_tokens_to_ids(target_nllb)
    inputs = tokenizer(
        texts, return_tensors="pt", padding=True, truncation=True, max_length=max_length,
    )
    with torch.no_grad():
        out = model.generate(
            **inputs,
            forced_bos_token_id=target_id,
            max_length=max_length,
            num_beams=1,
            no_repeat_ngram_size=3,
            repetition_penalty=1.3,
        )
    return tokenizer.batch_decode(out, skip_special_tokens=True)


# 세종님 지적(2026-05-09): batch 경로가 _translate의 lru_cache를 우회 → 같은 헤더
# 반복 시 캐시 효과 사라짐. 분석 내부 dedup + 모듈 LRU 캐시로 lru_cache 등가 효과 복원.
# OrderedDict — get 시 move_to_end로 최근 사용 갱신, 초과 시 가장 오래된 1개 제거 (진짜 LRU).
_BATCH_NLLB_CACHE: "OrderedDict[tuple[str, str], str]" = OrderedDict()
_BATCH_NLLB_CACHE_MAX = 1024  # _translate의 lru_cache(maxsize=1024)와 일치


def _translate_batch_cached(
    texts: list[str],
    target_nllb: str = "vie_Latn",
    max_length: int = 384,
) -> list[str]:
    """`_translate_batch_raw`의 dedup + cache 래퍼.

    A. 분석 내부 dedup — 같은 입력이 여러 번 와도 NLLB는 1회만 forward
    B. 모듈 LRU 캐시 — 분석 간 동일 입력은 NLLB 우회 (단일 _translate의 lru_cache 등가).
       OrderedDict 기반: 히트 시 move_to_end, 초과 시 가장 오래된 1개 제거.
    """
    if not texts:
        return []

    # 1) Dedup — 보존 순서로 unique 추출
    unique: list[str] = []
    pos: dict[str, int] = {}
    for t in texts:
        if t not in pos:
            pos[t] = len(unique)
            unique.append(t)

    # 2) 캐시 분리 — 미스만 batch. 히트는 LRU 갱신.
    unique_results: list[str] = [""] * len(unique)
    misses: list[str] = []
    miss_indices: list[int] = []
    for i, t in enumerate(unique):
        key = (t, target_nllb)
        if key in _BATCH_NLLB_CACHE:
            _BATCH_NLLB_CACHE.move_to_end(key)
            unique_results[i] = _BATCH_NLLB_CACHE[key]
        else:
            misses.append(t)
            miss_indices.append(i)

    # 3) 미스 batch 실행 → 결과 LRU 캐시 (가장 오래된 항목부터 evict)
    if misses:
        miss_translations = _translate_batch_raw(misses, target_nllb, max_length)
        for idx, t, tr in zip(miss_indices, misses, miss_translations):
            unique_results[idx] = tr
            _BATCH_NLLB_CACHE[(t, target_nllb)] = tr
            _BATCH_NLLB_CACHE.move_to_end((t, target_nllb))
            while len(_BATCH_NLLB_CACHE) > _BATCH_NLLB_CACHE_MAX:
                _BATCH_NLLB_CACHE.popitem(last=False)

    # 4) 원래 순서로 펼치기
    return [unique_results[pos[t]] for t in texts]


# 한국어 원문 → 베트남어 번역 결과의 명백한 오번역 강제 치환.
# NLLB가 학교 도메인을 못 배워서 발생하는 시각적 결함을 시연 전에 막는 안전망.
_CURRENCY_PATTERNS = [
    re.compile(r"\bđô\s*la\b", re.IGNORECASE),
    re.compile(r"\bdollars?\b", re.IGNORECASE),
    re.compile(r"\bUSD\b"),
]
# 천단위 점(40.000) → 콤마(40,000). 베트남식 표기지만 한국 학부모는 "40원"으로 오인할 수 있음.
_THOUSAND_DOT = re.compile(r"(\d{1,3}(?:\.\d{3})+)")
_KRW_AMOUNT = re.compile(r"\d[\d,]*\s*원")

_STUDENT_CONTEXT_TERMS = (
    "\ud559\uc0dd", "\ud559\ub144", "\ucd08\ub4f1\ud559\uc0dd",
    "\uc804\uad50\uc0dd", "\uc544\ub3d9", "\uc790\ub140",
)
_HOMEROOM_CONTEXT_TERMS = (
    "\ub2f4\uc784\uc120\uc0dd\ub2d8", "\ub2f4\uc784 \uc120\uc0dd\ub2d8",
    "\ub2f4\uc784\uad50\uc0ac", "\ub2f4\uc784",
)
_KINDERGARTEN_CONTEXT_TERMS = (
    "\uc720\uce58\uc6d0\uc0dd", "\uc720\uce58\uc6d0", "\uc6d0\uc0dd", "\uc720\uc544",
)
_FIELD_TRIP_CONTEXT_TERMS = (
    "\ud604\uc7a5\uccb4\ud5d8\ud559\uc2b5", "\uccb4\ud5d8\ud559\uc2b5",
    "\uc18c\ud48d", "\uc218\ub828\ud68c",
)
_ALLSTUDENT_CONTEXT_TERMS = ("\uc804\uad50\uc0dd",)
_SCHOOL_TRIP_CONTEXT_TERMS = ("\uc218\ud559\uc5ec\ud589",)
_SCHOOL_NOTICE_CONTEXT_TERMS = ("\uac00\uc815\ud1b5\uc2e0\ubb38",)
_LUNCH_CONTEXT_TERMS = ("\uae09\uc2dd\ube44", "\uae09\uc2dd")
_ELEMENTARY_CONTEXT_TERMS = ("\ucd08\ub4f1\ud559\uc0dd",)
_INFANT_CONTEXT_TERMS = ("\uc720\uc544",)
# P11-B: \uc9c0\ub3c4(\u6307\u5c0e)=guidance context \u2014 NLLB\uac00 \uc9c0\ub3c4(\u5730\u5716)=map\uc73c\ub85c \uc624\uc5ed\ud558\ub294 mn/th/ms/ja \uad50\uc815
_GUIDANCE_CONTEXT_TERMS = ("\uc9c0\ub3c4 \ubd80\ud0c1", "\uac00\uc815\uc5d0\uc11c\ub3c4 \uc9c0\ub3c4", "\uc0dd\ud65c\uc9c0\ub3c4")
# P11-E: vi/en \ub9d0\ubbf8 \ub4dc\ub86d \uad50\uc815 \u2014 glossary injection \ud6c4 \ubb38\uc7a5 \ub9d0\ubbf8 \uc11c\uc220\uc5b4 \uc18c\uc2e4 \ud328\ud134
_HOME_GUIDANCE_KO = ("\uac00\uc815\uc5d0\uc11c\ub3c4 \uc9c0\ub3c4", "\uc0dd\ud65c\uc9c0\ub3c4")   # \uac00\uc815\uc5d0\uc11c\ub3c4 \uc9c0\ub3c4, \uc0dd\ud65c\uc9c0\ub3c4
_ABSENT_NOTIFY_KO = ("\uacb0\uc11d",)                                                                 # \uacb0\uc11d
_ABSENT_NOTIFY_TRIGGER_KO = ("\uc54c\ub824 \uc8fc\uc138\uc694", "\uc54c\ub824\uc8fc\uc138\uc694")    # \uc54c\ub824 \uc8fc\uc138\uc694, \uc54c\ub824\uc8fc\uc138\uc694

_STUDENT_PATTERNS = (
    re.compile(r"\bsinh vi(?:\u00ean|en)\b", re.IGNORECASE),
    re.compile(r"\bh(?:\u1ecdc|o)c vi(?:\u00ean|en)\b", re.IGNORECASE),
)
_HOMEROOM_PATTERNS = (
    re.compile(r"gi(?:\u00e1|a)o vi(?:\u00ean|en) gi(?:\u00e1|a)m (?:\u0111|d)(?:\u1ed1|o)c", re.IGNORECASE),
    re.compile(r"gi(?:\u00e1|a)o vi(?:\u00ean|en) qu(?:\u1ea3|a)n l(?:\u00fd|y)", re.IGNORECASE),
    re.compile(r"gi(?:\u00e1|a)o vi(?:\u00ean|en) ph(?:\u1ee5|u) tr(?:\u00e1|a)ch", re.IGNORECASE),
    re.compile(r"gi(?:\u00e1|a)o s(?:\u01b0|u) gi(?:\u00e1|a)o vi(?:\u00ean|en)", re.IGNORECASE),
)
_KINDERGARTEN_PATTERNS = (
    re.compile(r"H\u1ecdc vi\u1ec7n sinh vi\u00ean m\u1eabu gi\u00e1o", re.IGNORECASE),
    re.compile(r"Hoc vien sinh vien mau giao", re.IGNORECASE),
    re.compile(r"H\u1ecdc vi\u1ec7n m\u1eabu gi\u00e1o", re.IGNORECASE),
    re.compile(r"Hoc vien mau giao", re.IGNORECASE),
    re.compile(r"sinh vi(?:\u00ean|en) m(?:\u1eabu|au) gi(?:\u00e1|a)o", re.IGNORECASE),
)
_FIELD_TRIP_PATTERNS = (
    re.compile(r"h(?:\u1ecdc|o)c t(?:\u1ead|a)p th(?:\u1ef1|u)c t(?:\u1ead|a)p t(?:\u1ea1|a)i tr(?:\u01b0|u)(?:\u1edd|o)ng", re.IGNORECASE),
    re.compile(r"h(?:\u1ecdc|o)c t(?:\u1ead|a)p t(?:\u1ea1|a)i tr(?:\u01b0|u)(?:\u1edd|o)ng h(?:\u1ecdc|o)c", re.IGNORECASE),
)

# \u2500\u2500 EN post-processing patterns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_HOMEROOM_PATTERNS_EN = (
    re.compile(r"\bvice[\s\-]?president\b", re.IGNORECASE),
    re.compile(r"\bguarantor\b", re.IGNORECASE),
)
_ALLSTUDENT_PATTERNS_EN = (
    re.compile(r"\bex[\s\-]?students?\b", re.IGNORECASE),
    re.compile(r"\bformer\s+students?\b", re.IGNORECASE),
)
_SCHOOL_TRIP_PATTERNS_EN = (
    re.compile(r"\bmath(?:ematics)?\s+trip\b", re.IGNORECASE),
)
_NEWSLETTER_PATTERNS_EN = (
    re.compile(r"\bhome\s+news\b", re.IGNORECASE),
)
_FIELD_TRIP_PATTERNS_EN = (
    re.compile(r"\bspring\s+vents?\b", re.IGNORECASE),
    re.compile(r"\bfield\s+trials?\b", re.IGNORECASE),
)

# \u2500\u2500 RU post-processing patterns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_HOMEROOM_PATTERNS_RU = (
    re.compile(r"\u0437\u0430\u0432\u0435\u0434(?:\u0443\u044e\u0449|\u0443\u0435\u0442)[\u0430-\u044f\u0451\u0410-\u042f\u0401]*\s+\u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440[\u0430-\u044f\u0451\u0410-\u042f\u0401]*", re.IGNORECASE),
    re.compile(r"\b\u0433\u0430\u0440\u0430\u043d(?:\u0442\u0443|\u0442\u0430|\u0442\u043e\u043c|\u0442\u0438\u0439)\b", re.IGNORECASE),
)
_SCHOOL_TRIP_PATTERNS_RU = (
    re.compile(r"\u043c\u0430\u0442\u0435\u043c\u0430\u0442\u0438\u0447[\u0430-\u044f\u0451\u0410-\u042f\u0401]+\s+\u043f\u0443\u0442\u0435\u0448\u0435\u0441\u0442\u0432[\u0430-\u044f\u0451\u0410-\u042f\u0401]+", re.IGNORECASE),
)
_NEWSLETTER_PATTERNS_RU = (
    re.compile(r"\u0434\u043e\u043c\u0430\u0448\u043d[\u0430-\u044f\u0451\u0410-\u042f\u0401]+\s+\u0433\u0430\u0437\u0435\u0442[\u0430-\u044f\u0451\u0410-\u042f\u0401]+", re.IGNORECASE),
)
_PICNIC_PATTERNS_RU = (
    re.compile(r"\u0432\u0435\u0441\u0435\u043d\u043d\u0438[\u0430-\u044f\u0451\u0410-\u042f\u0401]+\s+\u0432\u0435\u0442\u0435\u0440?[\u0430-\u044f\u0451\u0410-\u042f\u0401]*", re.IGNORECASE),
)

# \u2500\u2500 MS post-processing patterns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_HOMEROOM_PATTERNS_MS = (
    re.compile(r"doktor\s+yang\s+bertanggungjawab\b", re.IGNORECASE),
)
_ALLSTUDENT_PATTERNS_MS = (
    re.compile(r"pelajar[\s\-]pelajar\s+terdahulu\b", re.IGNORECASE),
    re.compile(r"bekas\s+pelajar\b", re.IGNORECASE),
)
_SCHOOL_TRIP_PATTERNS_MS = (
    re.compile(r"perjalanan\s+matematik\b", re.IGNORECASE),
)
_NEWSLETTER_PATTERNS_MS = (
    re.compile(r"surat\s+khabar\s+rumah\b", re.IGNORECASE),
)

# \u2500\u2500 MN post-processing patterns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_ALLSTUDENT_PATTERNS_MN = (
    re.compile(r"\u0441\u0443\u0440\u0433\u0443\u0443\u043b\u0438\u0439\u043d\s+\u04e9\u043c\u043d\u04e9\u0445\s+\u0431\u043e\u043b\u043e\u0432\u0441\u0440\u043e\u043b[\u0430-\u044f\u0451\u0410-\u042f\u0401]*", re.IGNORECASE),
)
_SCHOOL_TRIP_PATTERNS_MN = (
    re.compile(r"\u043c\u0430\u0442\u0435\u043c\u0430\u0442\u0438\u043a\u0438\u0439\u043d\s+\u0430\u044f\u043b\u0430\u043b[\u0430-\u044f\u0451\u0410-\u042f\u0401]*", re.IGNORECASE),
)

# \u2500\u2500 ZH post-processing patterns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_HOMEROOM_PATTERNS_ZH = (
    re.compile(r"(?<!\u73ed)\u4e3b\u4efb"),
)
_ALLSTUDENT_PATTERNS_ZH = (
    re.compile(r"\u524d\u5b66\u751f"),
)
_SCHOOL_TRIP_PATTERNS_ZH = (
    re.compile(r"\u6570\u5b66(?:\u8003\u8bd5\u7b7e\u8bc1|\u65c5\u884c)"),
)
_NEWSLETTER_PATTERNS_ZH = (
    re.compile(r"\u5bb6\u5ead\u62a5\u9053"),
)
_LUNCH_PATTERNS_ZH = (
    re.compile(r"\u5feb\u9910\u8d39\u7528"),
)

# \u2500\u2500 TH post-processing patterns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# NLLB\uac00 TH\uc5d0\uc11c \uac19\uc740 \ub2e8\uc5b4\ub97c \uc218\ubc31 \ubc88 \ubc18\ubcf5 \ucd9c\ub825\ud558\ub294 hallucination \ubc84\uadf8 \ubc29\uc5b4
_TH_LOOP_RE = re.compile(r"(.{3,12})\1{3,}")
_ALLSTUDENT_PATTERNS_TH = (
    re.compile(r"\u0e19\u0e31\u0e01\u0e40\u0e23\u0e35\u0e22\u0e19\u0e0a\u0e31\u0e49\u0e19(?:\u0e21\u0e31\u0e18\u0e22\u0e21|\u0e1b\u0e23\u0e30\u0e16\u0e21)(?:\u0e28\u0e36\u0e01\u0e29\u0e32)?(?:\u0e15\u0e2d\u0e19\u0e15\u0e49\u0e19|\u0e15\u0e2d\u0e19\u0e1b\u0e25\u0e32\u0e22)?"),
)
_ELEMENTARY_PATTERNS_TH = (
    re.compile(r"\u0e19\u0e31\u0e01\u0e40\u0e23\u0e35\u0e22\u0e19\u0e0a\u0e31\u0e49\u0e19\u0e21\u0e31\u0e18\u0e22\u0e21\u0e28\u0e36\u0e01\u0e29\u0e32\u0e15\u0e2d\u0e19\u0e15\u0e49\u0e19"),
)

# \u2500\u2500 JA post-processing patterns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_HOMEROOM_PATTERNS_JA = (
    re.compile(r"\u88c1\u5224\u9577"),
    re.compile(r"\u8b66\u5831"),
)
_SCHOOL_TRIP_PATTERNS_JA = (
    re.compile(r"\u6570\u5b66\u65c5\u884c"),
)
_NEWSLETTER_PATTERNS_JA = (
    re.compile(r"\u5bb6\u5ead\u65b0\u805e"),
)
_ELEMENTARY_PATTERNS_JA = (
    re.compile(r"\u5e7c\u7a1a\u5712\u306e\u5b50\u4f9b"),
)
_INFANT_PATTERNS_JA = (
    re.compile(r"\u8d64\u3061\u3083\u3093"),
)
_LUNCH_PATTERNS_JA = (
    re.compile(r"\u98df\u6599\u3092\u6025\u306b\u652f\u3048\u308b"),
)

# P11-B: guidance map-word correction patterns (\uc9c0\ub3c4\u2192map \uc624\uc5ed \uad50\uc815)
_GUIDANCE_PATTERNS_MN = (
    re.compile(r"\u0437\u0443\u0440\u0430\u0433\s+\u0430\u0432\u0430\u0445", re.IGNORECASE),
    re.compile(r"\u0433\u0430\u0437\u0440\u044b\u043d\s+\u0437\u0443\u0440\u0430\u0433", re.IGNORECASE),
    re.compile(r"\b\u0437\u0443\u0440\u0430\u0433\b", re.IGNORECASE),
)
_GUIDANCE_PATTERNS_TH = (
    re.compile(r"\u0e41\u0e1c\u0e19\u0e17\u0e35\u0e48"),
)
_GUIDANCE_PATTERNS_MS = (
    re.compile(r"\bpeta\b", re.IGNORECASE),
)
_GUIDANCE_PATTERNS_JA = (
    re.compile(r"\u5730\u56f3"),
    re.compile(r"\u30de\u30c3\u30d7"),  # NLLB\uac00 \u30ab\u30bf\u30ab\u30ca\ub85c \ucd9c\ub825\ud558\ub294 \uacbd\uc6b0
)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


# P11-E: 언어별 말미 드롭 교정 상수
_P11E_GUIDANCE = {
    'vi': ('hướng dẫn',   ', xin hãy hướng dẫn thêm tại nhà.'),
    'en': ('guidance',    ', please also provide guidance at home.'),
    'mn': ('хяналт',      ', гэрт ч хяналт тавина уу.'),
    'th': ('ดูแล',         ', กรุณาช่วยดูแลที่บ้านด้วย'),
    'ru': ('воспитани',   ', пожалуйста, уделите внимание воспитанию ребёнка дома.'),
    'ms': ('bimbingan',   ', sila beri bimbingan di rumah juga.'),
    'zh': ('指导',          '，请在家里也多加指导。'),
    'ja': ('ご指導',        '、ご家庭でもご指導をよろしくお願いします。'),
}
_P11E_ABSENT = {
    'vi': ('vắng mặt',   ('kết thúc',), 'Nếu học sinh vắng mặt, xin vui lòng thông báo trước cho giáo viên chủ nhiệm.'),
    'en': ('absent',     (),            'If your child will be absent, please inform the homeroom teacher in advance.'),
    'mn': ('ирэхгүй',   (),            'Хэрэв сурагч ирэхгүй бол урьдчилан ангийн багшид мэдэгдэнэ үү.'),
    'th': ('ขาดเรียน',  (),            'หากนักเรียนขาดเรียน กรุณาแจ้งครูประจำชั้นล่วงหน้า'),
    'ru': ('отсутств',  (),            'Если ребёнок будет отсутствовать, пожалуйста, заранее сообщите классному руководителю.'),
    'ms': ('tidak hadir', (),           'Jika pelajar tidak hadir, sila maklumkan kepada guru kelas terlebih dahulu.'),
    'zh': ('缺席',       (),            '如果学生缺席，请提前通知班主任。'),
    'ja': ('欠席',       (),            '欠席の場合は、事前に担任の先生にご連絡ください。'),
}
# P11-E: "생활지도" — NLLB가 전체 문장 오역 → 완전 교체
_P11E_SEIKATSU_JIDO = {
    'vi': 'Sau khi đến trường, xin hãy hướng dẫn thêm cho học sinh tại nhà.',
    'en': 'After school hours, please also provide guidance at home.',
    'mn': 'Сургуульд ирсний дараа гэрт ч хяналт тавина уу.',
    'th': 'หลังจากไปโรงเรียน กรุณาช่วยดูแลที่บ้านด้วย',
    'ru': 'После прихода домой из школы, пожалуйста, уделите внимание воспитанию ребёнка.',
    'ms': 'Selepas pergi ke sekolah, sila beri bimbingan di rumah juga.',
    'zh': '放学后，请在家里也多加指导。',
    'ja': '登校後、ご家庭でもご指導をよろしくお願いします。',
}
# P11-E: 강당 → 교실/방 오역 교정 (NLLB가 2글자라 주입 못 받는 용어)
_GANGDANG_KO = ("강당",)
_P11E_GANGDANG = {
    'vi': 'hội trường',
    'en': 'auditorium',
    'mn': 'их танхим',
    'th': 'หอประชุม',
    'ru': 'актовый зал',
    'ms': 'dewan sekolah',
    'zh': '礼堂',
    'ja': '講堂',
}
# P11-E: 담임교사 수합 → 교무실 제출 (R-003) — NLLB가 수신자를 역전시키는 오역 교정
_TEACHER_COLLECT_KO = ("담임교사는",)
_TEACHER_COLLECT_TRIGGER_KO = ("수합", "수거")
_P11E_TEACHER_COLLECT = {
    'vi': 'Giáo viên chủ nhiệm sẽ thu hồi phiếu phản hồi và nộp lên văn phòng nhà trường.',
    'en': 'The homeroom teacher will collect the reply forms and submit them to the school office.',
    'mn': 'Ангийн багш хариу маягтуудыг цуглуулж, багш нарын өрөөнд хүргэнэ.',
    'th': 'ครูประจำชั้นจะเก็บรวบรวมใบตอบรับและส่งที่ห้องพักครู',
    'ru': 'Классный руководитель соберёт бланки ответов и сдаст их в учительскую.',
    'ms': 'Guru kelas akan mengumpul borang balas dan menghantarnya ke bilik guru.',
    'zh': '班主任老师将收集回执并提交至教务处。',
    'ja': '担任の先生が返信書を回収して、職員室に提出します。',
}


def _apply_p11e(lang: str, easy_ko: str, text: str) -> str:
    """P11-E: 가정지도/결석알림/담임수합/강당 오역 교정 — 8개 언어 공통."""
    # 강당 → 교실/방 오역 교정 (2글자라 glossary 주입 불가)
    if _has_any(easy_ko, _GANGDANG_KO):
        correct = _P11E_GANGDANG.get(lang)
        if correct:
            for wrong in ('课堂', 'classroom', 'class room', 'ห้องเรียน',
                          'класс', 'bilik darjah', 'kelas', 'сургуулийн танхим',
                          'цуглаан',
                          '교실', '강의실', 'lớp học'):
                if wrong in text:
                    text = text.replace(wrong, correct)
    # 담임교사 수합 → 교무실 제출 역전 교정 (R-003)
    if _has_any(easy_ko, _TEACHER_COLLECT_KO) and _has_any(easy_ko, _TEACHER_COLLECT_TRIGGER_KO):
        repl = _P11E_TEACHER_COLLECT.get(lang)
        if repl:
            return repl
    # 생활지도 — NLLB 전체 오역이므로 완전 교체
    if "생활지도" in easy_ko and "부탁드립니다" in easy_ko:
        repl = _P11E_SEIKATSU_JIDO.get(lang)
        if repl:
            return repl
    # 가정지도 말미 드롭 (F-001 패턴)
    if _has_any(easy_ko, _HOME_GUIDANCE_KO) and "부탁드립니다" in easy_ko:
        indicator, tail = _P11E_GUIDANCE.get(lang, (None, None))
        if indicator and indicator not in text:
            text = text.rstrip(". ") + tail
    # 결석 알림 말미 드롭
    if _has_any(easy_ko, _ABSENT_NOTIFY_KO) and _has_any(easy_ko, _ABSENT_NOTIFY_TRIGGER_KO):
        cfg = _P11E_ABSENT.get(lang)
        if cfg:
            indicator, wrong, replacement = cfg
            if indicator not in text or any(w in text for w in wrong):
                text = replacement
    return text


def _normalize_glossary_key(text: str) -> str:
    # 및/또는/그리고는 1글자(및) 또는 다음절 접속사로 _get_item_zone 토큰화 시 버려짐.
    # 양쪽 key 모두에서 제거해 compound glossary 매칭이 깨지지 않도록 함.
    t = re.sub(r"및|또는|그리고", "", text or "")
    return re.sub(r"\s+", "", t)


# ── Review Required Guard ─────────────────────────────────────────────────────
# review_required=True일 때 번역문 끝에 붙이는 언어별 경고 문구
_REVIEW_WARNING: dict[str, str] = {
    'vi': '\n※ Vui lòng kiểm tra lại cùng con bạn.',
    'en': '\n※ Please confirm the details with your child.',
    'mn': '\n※ Хүүхэдтэйгээ хамт дахин шалгана уу.',
    'th': '\n※ กรุณาตรวจสอบรายละเอียดร่วมกับบุตรหลานของท่าน',
    'ru': '\n※ Пожалуйста, уточните подробности у ребёнка.',
    'ms': '\n※ Sila semak semula butiran bersama anak anda.',
    'zh': '\n※ 请与孩子一同确认详情。',
    'ja': '\n※ お子様と一緒に内容をご確認ください。',
}

# 교사/행정실 대상 문장: 부모 앱에 자동 확정 번역 금지
NON_PARENT_TARGET_PATTERNS: tuple[str, ...] = (
    "담임교사는",
    "교사는",
    "담임 선생님은",
    "각 반 담임",
    "업무 담당자는",
    "행정실에서는",
    "학교에서는",
    "인솔 교사는",
    "교무실로 제출",
)

# 부정문/조건문/선택사항: 자동 템플릿 결과라도 검수 필요
RISKY_CONTEXT_PATTERNS: tuple[str, ...] = (
    "제출하지 않고",
    "가져오지",
    "준비하지 않아도",
    "납부하지",
    "해당되는 가정만",
    "희망자만",
    "희망자는",
    "희망 가정만",
    "선택 사항",
    "무상급식",   # P11-A: 무상급식+부정문 조합 → 면제 오역 방지
    "무상 급식",
)

# item_zone 오염 방어 — 절 경계 이후만 item으로 인정
# "작성하여", "서명 후", "표시하여"는 오탐 가능성으로 제외
SAFE_CLAUSE_BOUNDARIES: tuple[str, ...] = (
    # "," 제외 — 한국어 목록 콤마("색종이, 풀, 가위")를 절 경계로 오인해
    # 마지막 항목만 item_zone에 남기는 버그 방지. 동사절 경계는 아래 패턴이 처리.
    ".",
    "읽고",
    "확인한 뒤",
    "확인 후",
    "사항이며",
    "이며",
)


def detect_non_parent_target(text: str) -> bool:
    return any(p in text for p in NON_PARENT_TARGET_PATTERNS)


def detect_risky_context(text: str) -> str | None:
    for p in RISKY_CONTEXT_PATTERNS:
        if p in text:
            return p
    return None


# ── Template-based translation (all languages) ────────────────────────────────
# 준비물/제출물 문장은 NLLB 대신 구조 분석 + glossary로 직접 번역.
# 용어 보존율: NLLB 직접 입력 6% → 템플릿 100% (2026-05-07 실험)
# 9개 언어 확장: vi 전용 → en/ru/ms/mn/zh/th/ja 전체 (2026-05-22)

_SENTENCE_TYPES: dict[str, list[str]] = {
    "prepare": ["준비해 주세요", "준비해주세요", "준비하세요", "준비 바랍니다"],
    "bring":   ["가져오세요", "가져와 주세요", "가져와주세요", "챙겨 주세요", "챙겨주세요", "지참해 주세요", "지참하세요", "지참 바랍니다", "착용하고 오세요", "착용해 주세요", "착용해주세요"],
    "submit":  ["제출해 주세요", "제출해주세요", "제출하세요", "내 주세요", "내주세요", "보내 주세요", "보내주세요", "제출 바랍니다", "제출바랍니다", "제출 부탁드립니다", "제출해 주시기"],
    "attend":  ["참석해 주세요", "참석해주세요", "참석하세요", "참여해 주세요", "참여해주세요", "참여하세요"],
    "pay":     ["납부해 주세요", "납부해주세요", "납부하세요", "입금해 주세요", "입금해주세요", "입금하세요"],
    "check":   ["확인해 주세요", "확인해주세요", "확인하세요", "확인 바랍니다", "확인해 주시기 바랍니다"],
    "fill":    ["작성해 주세요", "작성해주세요", "작성하세요", "작성 바랍니다", "기재해 주세요", "기재해주세요"],
    "apply":   ["신청해 주세요", "신청해주세요", "신청하세요", "신청 바랍니다", "접수해 주세요", "접수해주세요"],
}

_LANG_TEMPLATES: dict[str, dict[str, str]] = {
    "vi": {
        "prepare": "Vui lòng chuẩn bị {items}.",
        "bring":   "Vui lòng mang theo {items}.",
        "submit":  "Vui lòng nộp {items}.",
        "attend":  "Vui lòng tham gia {items}.",
        "pay":     "Vui lòng thanh toán {items}.",
        "check":   "Vui lòng kiểm tra {items}.",
        "fill":    "Vui lòng điền vào {items}.",
        "apply":   "Vui lòng đăng ký {items}.",
    },
    "en": {
        "prepare": "Please prepare {items}.",
        "bring":   "Please bring {items}.",
        "submit":  "Please submit {items}.",
        "attend":  "Please attend {items}.",
        "pay":     "Please pay {items}.",
        "check":   "Please check {items}.",
        "fill":    "Please fill out {items}.",
        "apply":   "Please apply for {items}.",
    },
    "ru": {
        "prepare": "Пожалуйста, подготовьте {items}.",
        "bring":   "Пожалуйста, принесите {items}.",
        "submit":  "Пожалуйста, сдайте {items}.",
        "attend":  "Пожалуйста, примите участие: {items}.",
        "pay":     "Пожалуйста, оплатите {items}.",
        "check":   "Пожалуйста, проверьте {items}.",
        "fill":    "Пожалуйста, заполните {items}.",
        "apply":   "Пожалуйста, запишитесь на {items}.",
    },
    "ms": {
        "prepare": "Sila sediakan {items}.",
        "bring":   "Sila bawa {items}.",
        "submit":  "Sila hantar {items}.",
        "attend":  "Sila hadir ke {items}.",
        "pay":     "Sila bayar {items}.",
        "check":   "Sila semak {items}.",
        "fill":    "Sila isi {items}.",
        "apply":   "Sila daftar untuk {items}.",
    },
    "mn": {
        "prepare": "{items} бэлдэж өгнө үү.",
        "bring":   "{items} авчирна уу.",
        "submit":  "{items} өгнө үү.",
        "attend":  "{items}-д оролцоно уу.",
        "pay":     "{items} төлнө үү.",
        "check":   "{items}-ийг шалгаж өгнө үү.",
        "fill":    "{items}-ийг бөглөж өгнө үү.",
        "apply":   "{items}-д бүртгүүлнэ үү.",
    },
    "zh": {
        "prepare": "请准备{items}。",
        "bring":   "请携带{items}。",
        "submit":  "请提交{items}。",
        "attend":  "请参加{items}。",
        "pay":     "请缴纳{items}。",
        "check":   "请确认{items}。",
        "fill":    "请填写{items}。",
        "apply":   "请申请{items}。",
    },
    "th": {
        "prepare": "กรุณาเตรียม {items}",
        "bring":   "กรุณานำ {items} มาด้วย",
        "submit":  "กรุณาส่ง {items}",
        "attend":  "กรุณาเข้าร่วม {items}",
        "pay":     "กรุณาชำระ {items}",
        "check":   "กรุณาตรวจสอบ {items}",
        "fill":    "กรุณากรอก {items}",
        "apply":   "กรุณาสมัคร {items}",
    },
    "ja": {
        "prepare": "{items}をご準備ください。",
        "bring":   "{items}をお持ちください。",
        "submit":  "{items}を提出してください。",
        "attend":  "{items}にご参加ください。",
        "pay":     "{items}をお支払いください。",
        "check":   "{items}をご確認ください。",
        "fill":    "{items}にご記入ください。",
        "apply":   "{items}をお申し込みください。",
    },
}

# 항목 나열 시 언어별 접속사
_LANG_CONJUNCTIONS: dict[str, str] = {
    "vi": " và ",
    "en": " and ",
    "ru": " и ",
    "ms": " dan ",
    "mn": " болон ",
    "zh": "和",
    "th": "และ",
    "ja": "と",
}

# submit 유형 제출처 표현 — "{recipient}" 자리에 수신인 삽입
_LANG_RECIPIENT_SUFFIX: dict[str, str] = {
    "vi": " cho {recipient}",
    "en": " to {recipient}",
    "ru": " для {recipient}",
    "ms": " kepada {recipient}",
    "mn": " {recipient}-д",
    "zh": "，交给{recipient}",
    "th": " ถึง{recipient}",
    "ja":" ({recipient}へ)",
}

# 대상(audience) 접두 표현
_LANG_AUDIENCE_PREFIX: dict[str, str] = {
    "vi": "Dành cho {audience}: ",
    "en": "For {audience}: ",
    "ru": "Для {audience}: ",
    "ms": "Untuk {audience}: ",
    "mn": "{audience}-д: ",
    "zh": "致{audience}：",
    "th": "สำหรับ{audience}: ",
    "ja": "{audience}へ：",
}

# deadline 포함 submit/pay 등 템플릿 — __SLOTn__까지 패턴 감지 시 사용
_LANG_TEMPLATES_DEADLINE: dict[str, dict[str, str]] = {
    "vi": {
        "submit":  "Vui lòng nộp {items} trước {deadline}.",
        "pay":     "Vui lòng thanh toán {items} trước {deadline}.",
        "bring":   "Vui lòng mang theo {items} trước {deadline}.",
        "prepare": "Vui lòng chuẩn bị {items} trước {deadline}.",
        "apply":   "Vui lòng đăng ký {items} trước {deadline}.",
    },
    "en": {
        "submit":  "Please submit {items} by {deadline}.",
        "pay":     "Please pay {items} by {deadline}.",
        "bring":   "Please bring {items} by {deadline}.",
        "prepare": "Please prepare {items} by {deadline}.",
        "apply":   "Please apply for {items} by {deadline}.",
    },
    "ru": {
        "submit":  "Пожалуйста, сдайте {items} до {deadline}.",
        "pay":     "Пожалуйста, оплатите {items} до {deadline}.",
        "bring":   "Пожалуйста, принесите {items} до {deadline}.",
        "prepare": "Пожалуйста, подготовьте {items} до {deadline}.",
        "apply":   "Пожалуйста, запишитесь на {items} до {deadline}.",
    },
    "ms": {
        "submit":  "Sila hantar {items} sebelum {deadline}.",
        "pay":     "Sila bayar {items} sebelum {deadline}.",
        "bring":   "Sila bawa {items} sebelum {deadline}.",
        "prepare": "Sila sediakan {items} sebelum {deadline}.",
        "apply":   "Sila daftar untuk {items} sebelum {deadline}.",
    },
    "mn": {
        "submit":  "{items} {deadline}-аас өмнө өгнө үү.",
        "pay":     "{items} {deadline}-аас өмнө төлнө үү.",
        "bring":   "{items} {deadline}-аас өмнө авчирна уу.",
        "prepare": "{items} {deadline}-аас өмнө бэлдэж өгнө үү.",
        "apply":   "{items}-д {deadline}-аас өмнө бүртгүүлнэ үү.",
    },
    "zh": {
        "submit":  "请在{deadline}前提交{items}。",
        "pay":     "请在{deadline}前缴纳{items}。",
        "bring":   "请在{deadline}前携带{items}。",
        "prepare": "请在{deadline}前准备{items}。",
        "apply":   "请在{deadline}前申请{items}。",
    },
    "th": {
        "submit":  "กรุณาส่ง {items} ก่อน {deadline}",
        "pay":     "กรุณาชำระ {items} ก่อน {deadline}",
        "bring":   "กรุณานำ {items} มาก่อน {deadline}",
        "prepare": "กรุณาเตรียม {items} ก่อน {deadline}",
        "apply":   "กรุณาสมัคร {items} ก่อน {deadline}",
    },
    "ja": {
        "submit":  "{deadline}までに{items}を提出してください。",
        "pay":     "{deadline}までに{items}をお支払いください。",
        "bring":   "{deadline}までに{items}をお持ちください。",
        "prepare": "{deadline}までに{items}をご準備ください。",
        "apply":   "{deadline}までに{items}をお申し込みください。",
    },
}

# masked 문장에서 "__SLOTn__까지" 형태의 마감일 토큰을 감지
_DEADLINE_RE = re.compile(r"(__SLOT\d+__)까지")

# masked 문장에서 "__SLOTn__부터" 형태의 시작일 토큰을 감지 (P9: apply 기간 범위)
_START_DATE_RE = re.compile(r"(__SLOT\d+__)부터")

# apply stype 전용 기간 범위 템플릿 — 시작일 + 마감일이 모두 있을 때 사용 (P9)
_LANG_TEMPLATES_DEADLINE_RANGE: dict[str, str] = {
    "vi": "Vui lòng đăng ký {items} từ {start_date} đến {end_date}.",
    "en": "Please apply for {items} from {start_date} to {end_date}.",
    "ru": "Пожалуйста, запишитесь на {items} с {start_date} по {end_date}.",
    "ms": "Sila daftar untuk {items} dari {start_date} hingga {end_date}.",
    "mn": "{items}-д {start_date}-аас {end_date} хүртэл бүртгүүлнэ үү.",
    "zh": "请于{start_date}至{end_date}期间申请{items}。",
    "th": "กรุณาสมัคร {items} ตั้งแต่ {start_date} ถึง {end_date}",
    "ja": "{start_date}から{end_date}までに{items}をお申し込みください。",
}

# masked 문장에서 "__SLOTn__을/를" 형태의 금액 토큰을 감지
# 금액은 마스킹 후 "을/를" 조사만 남으므로 deadline("까지")과 구별됨
_AMOUNT_RE = re.compile(r"(__SLOT\d+__)(?:을|를)(?!\s*통해)")

# pay + amount 전용 템플릿 — amount가 있는 납부 문장에서 금액을 보존
_LANG_TEMPLATES_PAY_AMOUNT: dict[str, dict[str, str]] = {
    "vi": {
        "no_deadline":          "Vui lòng thanh toán {items} {amount}.",
        "with_deadline":        "Vui lòng thanh toán {items} {amount} trước {deadline}.",
        "with_method":          "Vui lòng thanh toán {items} {amount} {method}.",
        "with_method_deadline": "Vui lòng thanh toán {items} {amount} {method} trước {deadline}.",
    },
    "en": {
        "no_deadline":          "Please pay {items} of {amount}.",
        "with_deadline":        "Please pay {items} of {amount} by {deadline}.",
        "with_method":          "Please pay {items} of {amount} {method}.",
        "with_method_deadline": "Please pay {items} of {amount} {method} by {deadline}.",
    },
    "ru": {
        "no_deadline":          "Пожалуйста, оплатите {items} в размере {amount}.",
        "with_deadline":        "Пожалуйста, оплатите {items} в размере {amount} до {deadline}.",
        "with_method":          "Пожалуйста, оплатите {items} в размере {amount} {method}.",
        "with_method_deadline": "Пожалуйста, оплатите {items} в размере {amount} {method} до {deadline}.",
    },
    "ms": {
        "no_deadline":          "Sila bayar {items} sebanyak {amount}.",
        "with_deadline":        "Sila bayar {items} sebanyak {amount} sebelum {deadline}.",
        "with_method":          "Sila bayar {items} sebanyak {amount} {method}.",
        "with_method_deadline": "Sila bayar {items} sebanyak {amount} {method} sebelum {deadline}.",
    },
    "mn": {
        "no_deadline":          "{items} {amount} төлнө үү.",
        "with_deadline":        "{items} {amount}-г {deadline}-аас өмнө төлнө үү.",
        "with_method":          "{items} {amount}-г {method} төлнө үү.",
        "with_method_deadline": "{items} {amount}-г {method} {deadline}-аас өмнө төлнө үү.",
    },
    "zh": {
        "no_deadline":          "请缴纳{items} {amount}。",
        "with_deadline":        "请在{deadline}前缴纳{items} {amount}。",
        "with_method":          "请{method}缴纳{items} {amount}。",
        "with_method_deadline": "请在{deadline}前{method}缴纳{items} {amount}。",
    },
    "th": {
        "no_deadline":          "กรุณาชำระ {items} {amount}",
        "with_deadline":        "กรุณาชำระ {items} {amount} ก่อน {deadline}",
        "with_method":          "กรุณาชำระ {items} {amount} {method}",
        "with_method_deadline": "กรุณาชำระ {items} {amount} {method} ก่อน {deadline}",
    },
    "ja": {
        "no_deadline":          "{items} {amount}をお支払いください。",
        "with_deadline":        "{deadline}までに{items} {amount}をお支払いください。",
        "with_method":          "{items} {amount}を{method}お支払いください。",
        "with_method_deadline": "{deadline}までに{items} {amount}を{method}お支払いください。",
    },
}

# 납부 수단 표현 패턴 — "스쿨뱅킹을 통해", "계좌이체로" 등을 item이 아닌 method로 분리
# (pattern, {lang: translated_method}) 순서: 더 구체적인 패턴 먼저
_PAYMENT_METHOD_PATTERNS: list[tuple[re.Pattern, dict[str, str]]] = [
    (
        re.compile(r"스쿨뱅킹(?:을|를)?\s*통해"),
        {"vi": "qua School Banking", "en": "through School Banking",
         "ru": "через School Banking", "ms": "melalui School Banking",
         "mn": "Сургуулийн банкаар дамжуулан", "zh": "通过School Banking",
         "th": "ผ่าน School Banking", "ja": "School Bankingを通じて"},
    ),
    (
        re.compile(r"스쿨뱅킹(?:으로|로)"),
        {"vi": "qua School Banking", "en": "via School Banking",
         "ru": "через School Banking", "ms": "melalui School Banking",
         "mn": "Сургуулийн банкаар", "zh": "通过School Banking",
         "th": "ผ่าน School Banking", "ja": "School Bankingで"},
    ),
    (
        re.compile(r"계좌이체(?:로|으로)"),
        {"vi": "qua chuyển khoản ngân hàng", "en": "by bank transfer",
         "ru": "банковским переводом", "ms": "melalui pindahan bank",
         "mn": "банкны шилжүүлгээр", "zh": "通过银行转账",
         "th": "โดยการโอนเงินผ่านธนาคาร", "ja": "銀行振込で"},
    ),
    (
        re.compile(r"자동이체(?:로|으로)"),
        {"vi": "qua ghi nợ tự động", "en": "by auto-debit",
         "ru": "автоматическим списанием", "ms": "melalui debit automatik",
         "mn": "автомат шилжүүлгээр", "zh": "通过自动扣款",
         "th": "โดยการหักบัญชีอัตโนมัติ", "ja": "自動振替で"},
    ),
    (
        re.compile(r"학교\s*계좌(?:로|으로)"),
        {"vi": "vào tài khoản trường", "en": "to the school account",
         "ru": "на счёт школы", "ms": "ke akaun sekolah",
         "mn": "сургуулийн дансанд", "zh": "到学校账户",
         "th": "ไปยังบัญชีของโรงเรียน", "ja": "学校の口座に"},
    ),
    (
        re.compile(r"무통장\s*입금(?:으로|으로)?"),
        {"vi": "qua nộp tiền mặt tại ngân hàng", "en": "by cash deposit",
         "ru": "наличным депозитом", "ms": "melalui deposit tunai",
         "mn": "бэлэн мөнгөний хадгаламжаар", "zh": "通过现金存款",
         "th": "โดยการฝากเงินสด", "ja": "無通帳入金で"},
    ),
]

# 요일/상대기한 표현 → 언어별 번역 테이블
# 키: 공백 제거 정규화(다음주금요일 등), 값: lang → translated deadline string
_WEEKDAY_DEADLINE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "내일":        {"vi": "ngày mai",         "en": "tomorrow",      "ru": "завтра",                    "ms": "esok",          "mn": "маргааш",                    "zh": "明天",   "th": "พรุ่งนี้",           "ja": "明日"},
    "이번주":      {"vi": "tuần này",          "en": "this week",     "ru": "на этой неделе",            "ms": "minggu ini",    "mn": "энэ долоо хоногт",           "zh": "本周",   "th": "สัปดาห์นี้",         "ja": "今週"},
    "다음주":      {"vi": "tuần sau",          "en": "next week",     "ru": "на следующей неделе",       "ms": "minggu depan",  "mn": "дараа долоо хоногт",         "zh": "下周",   "th": "สัปดาห์หน้า",        "ja": "来週"},
    "월요일":      {"vi": "thứ Hai",           "en": "Monday",        "ru": "понедельник",               "ms": "Isnin",         "mn": "даваа гараг",                "zh": "周一",   "th": "วันจันทร์",           "ja": "月曜日"},
    "화요일":      {"vi": "thứ Ba",            "en": "Tuesday",       "ru": "вторник",                   "ms": "Selasa",        "mn": "мягмар гараг",               "zh": "周二",   "th": "วันอังคาร",           "ja": "火曜日"},
    "수요일":      {"vi": "thứ Tư",            "en": "Wednesday",     "ru": "среда",                     "ms": "Rabu",          "mn": "лхагва гараг",               "zh": "周三",   "th": "วันพุธ",              "ja": "水曜日"},
    "목요일":      {"vi": "thứ Năm",           "en": "Thursday",      "ru": "четверг",                   "ms": "Khamis",        "mn": "пүрэв гараг",                "zh": "周四",   "th": "วันพฤหัสบดี",         "ja": "木曜日"},
    "금요일":      {"vi": "thứ Sáu",           "en": "Friday",        "ru": "пятница",                   "ms": "Jumaat",        "mn": "баасан гараг",               "zh": "周五",   "th": "วันศุกร์",            "ja": "金曜日"},
    "토요일":      {"vi": "thứ Bảy",           "en": "Saturday",      "ru": "суббота",                   "ms": "Sabtu",         "mn": "бямба гараг",                "zh": "周六",   "th": "วันเสาร์",            "ja": "土曜日"},
    "일요일":      {"vi": "Chủ nhật",          "en": "Sunday",        "ru": "воскресенье",               "ms": "Ahad",          "mn": "ням гараг",                  "zh": "周日",   "th": "วันอาทิตย์",          "ja": "日曜日"},
    # 이번 주 + 요일
    "이번주월요일": {"vi": "thứ Hai tuần này",  "en": "this Monday",   "ru": "в этот понедельник",        "ms": "Isnin ini",     "mn": "энэ даваа гараг",            "zh": "本周一",  "th": "วันจันทร์นี้",         "ja": "今週月曜日"},
    "이번주화요일": {"vi": "thứ Ba tuần này",   "en": "this Tuesday",  "ru": "в этот вторник",            "ms": "Selasa ini",    "mn": "энэ мягмар гараг",           "zh": "本周二",  "th": "วันอังคารนี้",         "ja": "今週火曜日"},
    "이번주수요일": {"vi": "thứ Tư tuần này",   "en": "this Wednesday","ru": "в эту среду",               "ms": "Rabu ini",      "mn": "энэ лхагва гараг",           "zh": "本周三",  "th": "วันพุธนี้",            "ja": "今週水曜日"},
    "이번주목요일": {"vi": "thứ Năm tuần này",  "en": "this Thursday", "ru": "в этот четверг",            "ms": "Khamis ini",    "mn": "энэ пүрэв гараг",            "zh": "本周四",  "th": "วันพฤหัสบดีนี้",       "ja": "今週木曜日"},
    "이번주금요일": {"vi": "thứ Sáu tuần này",  "en": "this Friday",   "ru": "в эту пятницу",             "ms": "Jumaat ini",    "mn": "энэ баасан гараг",           "zh": "本周五",  "th": "วันศุกร์นี้",          "ja": "今週金曜日"},
    "이번주토요일": {"vi": "thứ Bảy tuần này",  "en": "this Saturday", "ru": "в эту субботу",             "ms": "Sabtu ini",     "mn": "энэ бямба гараг",            "zh": "本周六",  "th": "วันเสาร์นี้",          "ja": "今週土曜日"},
    "이번주일요일": {"vi": "Chủ nhật tuần này", "en": "this Sunday",   "ru": "в это воскресенье",         "ms": "Ahad ini",      "mn": "энэ ням гараг",              "zh": "本周日",  "th": "วันอาทิตย์นี้",        "ja": "今週日曜日"},
    # 다음 주 + 요일
    "다음주월요일": {"vi": "thứ Hai tuần sau",  "en": "next Monday",   "ru": "в следующий понедельник",   "ms": "Isnin depan",   "mn": "дараа долоо хоногийн даваа", "zh": "下周一",  "th": "วันจันทร์หน้า",        "ja": "来週月曜日"},
    "다음주화요일": {"vi": "thứ Ba tuần sau",   "en": "next Tuesday",  "ru": "в следующий вторник",       "ms": "Selasa depan",  "mn": "дараа долоо хоногийн мягмар","zh": "下周二",  "th": "วันอังคารหน้า",        "ja": "来週火曜日"},
    "다음주수요일": {"vi": "thứ Tư tuần sau",   "en": "next Wednesday","ru": "в следующую среду",         "ms": "Rabu depan",    "mn": "дараа долоо хоногийн лхагва","zh": "下周三",  "th": "วันพุธหน้า",           "ja": "来週水曜日"},
    "다음주목요일": {"vi": "thứ Năm tuần sau",  "en": "next Thursday", "ru": "в следующий четверг",       "ms": "Khamis depan",  "mn": "дараа долоо хоногийн пүрэв", "zh": "下周四",  "th": "วันพฤหัสบดีหน้า",      "ja": "来週木曜日"},
    "다음주금요일": {"vi": "thứ Sáu tuần sau",  "en": "next Friday",   "ru": "в следующую пятницу",       "ms": "Jumaat depan",  "mn": "дараа долоо хоногийн баасан","zh": "下周五",  "th": "วันศุกร์หน้า",         "ja": "来週金曜日"},
    "다음주토요일": {"vi": "thứ Bảy tuần sau",  "en": "next Saturday", "ru": "в следующую субботу",       "ms": "Sabtu depan",   "mn": "дараа долоо хоногийн бямба", "zh": "下周六",  "th": "วันเสาร์หน้า",         "ja": "来週土曜日"},
    "다음주일요일": {"vi": "Chủ nhật tuần sau", "en": "next Sunday",   "ru": "в следующее воскресенье",   "ms": "Ahad depan",    "mn": "дараа долоо хоногийн ням",   "zh": "下周日",  "th": "วันอาทิตย์หน้า",       "ja": "来週日曜日"},
}

# 요일/상대기한 소스 패턴 — "까지" 앞에 오는 요일/주차 표현만 매칭 (까지는 유지)
# 순서: 복합 표현(다음 주 금요일) → 주차 단독(다음 주) → 요일 단독(금요일) → 내일
_WEEKDAY_DEADLINE_SOURCE_RE = re.compile(
    r"(?:"
    r"(?:다음|이번)\s*주\s*(?:월|화|수|목|금|토|일)요일"
    r"|(?:다음|이번)\s*주"
    r"|(?:월|화|수|목|금|토|일)요일"
    r"|내일"
    r")(?=까지)"
)

# P3: 시점·빈도 부사 → time_context로 분리 (까지 없는 독립 부사만)
# "내일까지"는 P1(WEEKDAY_DEADLINE_SOURCE_RE)이 처리하므로 여기서는 제외.
_TIME_CONTEXT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "매일":   {"vi": "hằng ngày",   "en": "every day",  "ru": "каждый день",         "ms": "setiap hari",   "mn": "өдөр бүр",         "zh": "每天",   "th": "ทุกวัน",      "ja": "毎日"},
    "내일":   {"vi": "ngày mai",    "en": "tomorrow",   "ru": "завтра",              "ms": "esok",          "mn": "маргааш",           "zh": "明天",   "th": "พรุ่งนี้",    "ja": "明日"},
    "오늘":   {"vi": "hôm nay",     "en": "today",      "ru": "сегодня",             "ms": "hari ini",      "mn": "өнөөдөр",           "zh": "今天",   "th": "วันนี้",      "ja": "今日"},
    "당일":   {"vi": "trong ngày",  "en": "on the day", "ru": "в тот же день",       "ms": "pada hari itu", "mn": "тэр өдөр",          "zh": "当天",   "th": "ในวันนั้น",   "ja": "当日"},
    "이번주": {"vi": "tuần này",    "en": "this week",  "ru": "на этой неделе",      "ms": "minggu ini",    "mn": "энэ долоо хоногт",  "zh": "本周",   "th": "สัปดาห์นี้",  "ja": "今週"},
    "다음주": {"vi": "tuần sau",    "en": "next week",  "ru": "на следующей неделе", "ms": "minggu depan",  "mn": "дараа долоо хоногт","zh": "下周",   "th": "สัปดาห์หน้า", "ja": "来週"},
    # P7: 방학 time_context — item zone에서 "여름 방학"이 제출물로 오인되는 것을 방지
    "여름방학": {"vi": "kỳ nghỉ hè",   "en": "summer vacation", "ru": "на летних каникулах", "ms": "cuti sekolah",    "mn": "зуны амралтын үед", "zh": "暑假期间",  "th": "ช่วงปิดเทอมฤดูร้อน", "ja": "夏休み中"},
    "겨울방학": {"vi": "kỳ nghỉ đông", "en": "winter vacation", "ru": "на зимних каникулах", "ms": "cuti musim sejuk","mn": "өвлийн амралтын үед","zh": "寒假期间",  "th": "ช่วงปิดเทอมฤดูหนาว", "ja": "冬休み中"},
    "방학중":   {"vi": "trong kỳ nghỉ","en": "during vacation", "ru": "на каникулах",        "ms": "semasa cuti",     "mn": "амралтын үед",      "zh": "假期中",    "th": "ในช่วงปิดเทอม",      "ja": "休み中"},
}

# 순서: 이번/다음 주 복합 → 단독 부사. (?!까지): P1이 처리하는 deadline 컨텍스트 제외.
# P7: 여름/겨울 방학 — "방학 전까지"는 P4가 먼저 처리하므로 여기서는 (?!까지|전) 가드만.
_TIME_CONTEXT_SOURCE_RE = re.compile(
    r"(?:이번|다음)\s*주(?!까지)"
    r"|매일|내일(?!까지)|오늘|당일"
    r"|(?:여름|겨울)\s*방학(?!까지|전)"
    r"|방학\s*중"
)

# P4: 월말/월초/중순 기한 — "N월 말까지", "이번 달 초까지", "학기 말까지" 등
# extract_dates가 처리하지 못하는 월말/상대기한 표현을 deadline 슬롯으로 변환.
_MONTH_NAMES_BY_LANG: dict[str, dict[str, str]] = {
    "vi": {"1":"tháng 1","2":"tháng 2","3":"tháng 3","4":"tháng 4",
           "5":"tháng 5","6":"tháng 6","7":"tháng 7","8":"tháng 8",
           "9":"tháng 9","10":"tháng 10","11":"tháng 11","12":"tháng 12"},
    "en": {"1":"January","2":"February","3":"March","4":"April",
           "5":"May","6":"June","7":"July","8":"August",
           "9":"September","10":"October","11":"November","12":"December"},
    "ru": {"1":"января","2":"февраля","3":"марта","4":"апреля",
           "5":"мая","6":"июня","7":"июля","8":"августа",
           "9":"сентября","10":"октября","11":"ноября","12":"декабря"},
    "ms": {"1":"Januari","2":"Februari","3":"Mac","4":"April",
           "5":"Mei","6":"Jun","7":"Julai","8":"Ogos",
           "9":"September","10":"Oktober","11":"November","12":"Disember"},
    "mn": {"1":"1-р сар","2":"2-р сар","3":"3-р сар","4":"4-р сар",
           "5":"5-р сар","6":"6-р сар","7":"7-р сар","8":"8-р сар",
           "9":"9-р сар","10":"10-р сар","11":"11-р сар","12":"12-р сар"},
    "zh": {"1":"1月","2":"2月","3":"3月","4":"4月",
           "5":"5月","6":"6月","7":"7月","8":"8月",
           "9":"9月","10":"10月","11":"11月","12":"12月"},
    "th": {"1":"มกราคม","2":"กุมภาพันธ์","3":"มีนาคม","4":"เมษายน",
           "5":"พฤษภาคม","6":"มิถุนายน","7":"กรกฎาคม","8":"สิงหาคม",
           "9":"กันยายน","10":"ตุลาคม","11":"พฤศจิกายน","12":"ธันวาคม"},
    "ja": {"1":"1月","2":"2月","3":"3月","4":"4月",
           "5":"5月","6":"6月","7":"7月","8":"8月",
           "9":"9月","10":"10月","11":"11月","12":"12月"},
}

# 말/초/중순 언어별 형식 — {month} 자리에 위 테이블의 월 이름 삽입
_MONTH_PERIOD_SUFFIXES: dict[str, dict[str, str]] = {
    "말": {
        "vi": "cuối {month}",          "en": "the end of {month}",
        "ru": "конец {month}",         "ms": "akhir {month}",
        "mn": "{month}ын сүүлд",       "zh": "{month}底",
        "th": "ปลาย{month}",           "ja": "{month}末",
    },
    "초": {
        "vi": "đầu {month}",           "en": "the beginning of {month}",
        "ru": "начало {month}",        "ms": "awal {month}",
        "mn": "{month}ын эхэнд",       "zh": "{month}初",
        "th": "ต้น{month}",            "ja": "{month}初め",
    },
    "중순": {
        "vi": "giữa {month}",          "en": "mid-{month}",
        "ru": "середина {month}",      "ms": "pertengahan {month}",
        "mn": "{month}ын дунд",        "zh": "{month}中旬",
        "th": "กลาง{month}",           "ja": "{month}中旬",
    },
}

# 고정 상대 기한 — 동적 월 번호가 없는 표현
_FIXED_PERIOD_DEADLINE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "이번달말": {
        "vi":"cuối tháng này",  "en":"the end of this month",    "ru":"конец этого месяца",
        "ms":"akhir bulan ini", "mn":"энэ сарын сүүлд",          "zh":"本月底",
        "th":"ปลายเดือนนี้",   "ja":"今月末",
    },
    "이번달초": {
        "vi":"đầu tháng này",   "en":"the beginning of this month", "ru":"начало этого месяца",
        "ms":"awal bulan ini",  "mn":"энэ сарын эхэнд",             "zh":"本月初",
        "th":"ต้นเดือนนี้",    "ja":"今月初め",
    },
    "다음달말": {
        "vi":"cuối tháng sau",  "en":"the end of next month",    "ru":"конец следующего месяца",
        "ms":"akhir bulan depan","mn":"дараа сарын сүүлд",       "zh":"下月底",
        "th":"ปลายเดือนหน้า",  "ja":"来月末",
    },
    "다음달초": {
        "vi":"đầu tháng sau",   "en":"the beginning of next month", "ru":"начало следующего месяца",
        "ms":"awal bulan depan","mn":"дараа сарын эхэнд",           "zh":"下月初",
        "th":"ต้นเดือนหน้า",   "ja":"来月初め",
    },
    "학기말": {
        "vi":"cuối học kỳ",     "en":"the end of the semester",  "ru":"конец семестра",
        "ms":"akhir semester",  "mn":"улирлын сүүлд",            "zh":"学期末",
        "th":"ปลายภาคเรียน",   "ja":"学期末",
    },
    "방학전": {
        "vi":"kỳ nghỉ",         "en":"the school break",         "ru":"каникулы",
        "ms":"cuti sekolah",    "mn":"амралтын өмнө",            "zh":"放假前",
        "th":"ก่อนปิดเทอม",    "ja":"休み前",
    },
}

# 월말/월초/학기말 deadline 소스 패턴 — "까지" 앞에만 매칭 (P1 요일과 동일 방식)
_MONTH_PERIOD_SOURCE_RE = re.compile(
    r"(?:"
    r"(?:이번|다음)\s*달\s*(?:말|초|중순)"        # 이번 달 말, 다음 달 초
    r"|(?:1[0-2]|[1-9])\s*월\s*(?:말|초|중순)"   # 3월 말, 12월 초, 5월 중순
    r"|학기\s*말"                                  # 학기 말
    r"|방학\s*전"                                  # 방학 전
    r")(?=까지)"
)


def _translate_weekday_deadline(ko_text: str, lang_key: str) -> str:
    """요일/상대기한 표현을 대상 언어로 번역. 테이블에 없으면 원문 반환."""
    key = re.sub(r"\s+", "", ko_text)
    return _WEEKDAY_DEADLINE_TRANSLATIONS.get(key, {}).get(lang_key, ko_text)


def _translate_time_context(ko_text: str, lang_key: str) -> str:
    """시점·빈도 부사를 대상 언어로 번역. 테이블에 없으면 원문 반환."""
    key = re.sub(r"\s+", "", ko_text)
    return _TIME_CONTEXT_TRANSLATIONS.get(key, {}).get(lang_key, ko_text)


def _translate_month_period_deadline(ko_text: str, lang_key: str) -> str:
    """월말/월초/중순/학기말/방학전 기한 표현을 대상 언어로 번역."""
    key = re.sub(r"\s+", "", ko_text)
    if key in _FIXED_PERIOD_DEADLINE_TRANSLATIONS:
        return _FIXED_PERIOD_DEADLINE_TRANSLATIONS[key].get(lang_key, ko_text)
    m = re.match(r"(1[0-2]|[1-9])월(말|초|중순)$", key)
    if m:
        month_num = m.group(1)
        period = m.group(2)
        suffix_tpl = _MONTH_PERIOD_SUFFIXES.get(period, {}).get(lang_key)
        if not suffix_tpl:
            return ko_text
        month_str = _MONTH_NAMES_BY_LANG.get(lang_key, {}).get(month_num, f"{month_num}월")
        return suffix_tpl.format(month=month_str)
    return ko_text


# P6: 소풍/행사 당일 등 이벤트+당일 복합 표현 — TC로 처리해 item 오분류 방지.
# P3(당일 단독) 보다 먼저 마스킹해야 "소풍"이 item zone에 남지 않음.
_EVENT_CONTEXT_COMPOUND_TRANSLATIONS: dict[str, dict[str, str]] = {
    "소풍당일": {
        "vi": "vào ngày đi dã ngoại",    "en": "on the picnic day",
        "ru": "в день экскурсии",         "ms": "pada hari berkelah",
        "mn": "аяллын өдөр",             "zh": "郊游当天",
        "th": "ในวันทัศนศึกษา",          "ja": "遠足当日",
    },
    "현장체험학습당일": {
        "vi": "vào ngày đi trải nghiệm thực tế", "en": "on the field trip day",
        "ru": "в день выездной экскурсии",        "ms": "pada hari lawatan sambil belajar",
        "mn": "аяллын өдөр",                     "zh": "户外体验当天",
        "th": "ในวันทัศนศึกษา",                  "ja": "校外学習当日",
    },
    "체험학습당일": {
        "vi": "vào ngày đi trải nghiệm thực tế", "en": "on the field trip day",
        "ru": "в день экскурсии",           "ms": "pada hari lawatan",
        "mn": "аяллын өдөр",               "zh": "体验活动当天",
        "th": "ในวันทัศนศึกษา",            "ja": "体験学習当日",
    },
    "운동회당일": {
        "vi": "vào ngày hội thao",       "en": "on sports day",
        "ru": "в день спортивного праздника", "ms": "pada hari sukan",
        "mn": "спортын баярын өдөр",     "zh": "运动会当天",
        "th": "ในวันกีฬาสี",             "ja": "運動会当日",
    },
    "행사당일": {
        "vi": "vào ngày sự kiện",   "en": "on the event day",
        "ru": "в день мероприятия", "ms": "pada hari acara",
        "mn": "арга хэмжээний өдөр", "zh": "活动当天",
        "th": "ในวันจัดงาน",        "ja": "行事当日",
    },
}

# 순서: 현장체험학습(긴 것) → 체험학습(짧은 것) 순으로 배치해 longest-match 보장
_EVENT_CONTEXT_COMPOUND_RE = re.compile(
    r"(?:현장체험학습|체험학습|소풍|운동회|행사)\s*당일"
)


def _translate_event_context_compound(ko_text: str, lang_key: str) -> str:
    """소풍/체험학습/운동회 당일 등 이벤트 복합 표현을 대상 언어로 번역."""
    key = re.sub(r"\s+", "", ko_text)
    return _EVENT_CONTEXT_COMPOUND_TRANSLATIONS.get(key, {}).get(lang_key, ko_text)


# 준비물 label 패턴 — "준비물은 A, B, C입니다", "준비물: A, B", "준비물 - A, B" 등
# 동사 트리거가 없는 info형 준비물 나열 문장을 template 경로로 처리하기 위해 사용
_SUPPLY_LABEL_RE = re.compile(r"준비물[은는이가]?\s*[:\-：－]?\s*")

# 준비물 label 템플릿 — action형 prepare와 별도로 "목록 알림" 형식 사용
_LANG_SUPPLY_LABEL: dict[str, str] = {
    "vi": "Đồ dùng cần mang: {items}.",
    "en": "Things to bring: {items}.",
    "ru": "Необходимые принадлежности: {items}.",
    "ms": "Barang yang perlu dibawa: {items}.",
    "mn": "Авчрах зүйлс: {items}.",
    "zh": "携带物品：{items}。",
    "th": "สิ่งที่ต้องนำมา: {items}",
    "ja": "持ち物：{items}。",
}

# P3: 준비물 label + time_context — "{time_context}" 위치는 언어별로 결정
_LANG_SUPPLY_LABEL_TIME: dict[str, str] = {
    "vi": "Đồ dùng cần mang {time_context}: {items}.",
    "en": "Things to bring {time_context}: {items}.",
    "ru": "Необходимые принадлежности {time_context}: {items}.",
    "ms": "Barang yang perlu dibawa {time_context}: {items}.",
    "mn": "Авчрах зүйлс ({time_context}): {items}.",
    "zh": "{time_context}携带物品：{items}。",
    "th": "สิ่งที่ต้องนำมา {time_context}: {items}",
    "ja": "{time_context}の持ち物：{items}。",
}

# P3: 문장 끝에 time_context 추가 시 언어별 suffix 형식
_LANG_TIME_CONTEXT_SUFFIX: dict[str, str] = {
    "vi": " {time_context}.",
    "en": " {time_context}.",
    "ru": " {time_context}.",
    "ms": " {time_context}.",
    "mn": " {time_context}.",
    "zh": " {time_context}。",
    "th": " {time_context}",
    "ja": "、{time_context}。",
}

# 슬롯이 없는 순수 명사+동사 문장에서 명사구를 추출하기 위한 조사 패턴
# 과/와 포함: "공책과 연필을" 같은 나열형에서 과/와를 조사로 올바르게 제거
_KO_PARTICLES = re.compile(r"[을를이가은는도의에게로부터과와]$|까지$|으로$")

# 청중/제출처는 term_glossary.csv의 role 컬럼(audience/recipient)으로 관리.
# 코드 수정 없이 CSV 편집만으로 용어 추가 가능.
_TEMPLATE_EXCLUDE_KO: frozenset[str] = frozenset()  # _build_role_sets() 호출 후 갱신
_AUDIENCE_BY_LANG: dict[str, dict[str, str]] = {}   # lang → {ko: translated}
_RECIPIENT_BY_LANG: dict[str, dict[str, str]] = {}  # lang → {ko: translated}
# 복합 glossary 항목의 구성 단어 집합.
# 예) "학생 생활지도" → {"학생", "생활지도"}
# _get_item_zone에서 조사 제거 전 확인해 "생활지도→생활지" 오절삭을 방지.
_GLOSSARY_WORD_PARTS: frozenset[str] = frozenset()
_ROLE_SETS_BUILT = False


def _build_role_sets(glossary: list) -> None:
    """glossary rows에서 role=audience/recipient 항목을 언어별로 인덱싱.

    동시에 복합 glossary 항목("학생 생활지도" 등)의 구성 단어를
    _GLOSSARY_WORD_PARTS에 등록해 _get_item_zone의 조사 오절삭을 방지한다.
    """
    global _TEMPLATE_EXCLUDE_KO, _AUDIENCE_BY_LANG, _RECIPIENT_BY_LANG
    global _ROLE_SETS_BUILT, _GLOSSARY_WORD_PARTS
    if _ROLE_SETS_BUILT:
        return
    audience: dict[str, dict[str, str]] = {}
    recipient: dict[str, dict[str, str]] = {}
    exclude: set[str] = set()
    word_parts: set[str] = set()
    for row in glossary:
        ko = row.get("korean", "").strip()
        if not ko:
            continue
        # 복합어(공백 포함)의 구성 단어 수집
        parts = ko.split()
        if len(parts) > 1:
            for w in parts:
                if len(w) >= 2:
                    word_parts.add(w)
        role = row.get("role", "item").strip()
        if role not in ("audience", "recipient"):
            continue
        exclude.add(ko)
        for lang in LANG_TO_NLLB:
            val = row.get(f"preferred_{lang}", "").strip()
            if not val:
                continue
            if role == "audience":
                audience.setdefault(lang, {})[ko] = val
            else:
                recipient.setdefault(lang, {})[ko] = val
    _TEMPLATE_EXCLUDE_KO = frozenset(exclude)
    _AUDIENCE_BY_LANG = audience
    _RECIPIENT_BY_LANG = recipient
    _GLOSSARY_WORD_PARTS = frozenset(word_parts)
    _ROLE_SETS_BUILT = True


def _classify_sentence(text: str) -> str:
    for stype, keywords in _SENTENCE_TYPES.items():
        for kw in keywords:
            if kw in text:
                return stype
    # P8: "신청을 … 해 주세요" — 날짜 범위 등이 끼어 직접 매칭 실패하는 구조 보완.
    if re.search(r"신청을.{0,30}해 주세요", text):
        return "apply"
    return "info"


def _get_item_zone(text: str, stype: str) -> str:
    """동사 트리거 이전 텍스트 반환. 조사 정리.

    ISSUE-03: 조사 제거 후 1자 이하가 되면 원형 유지.
    Glossary-first: 복합 glossary 항목의 구성 단어(_GLOSSARY_WORD_PARTS)이면
      조사 제거 없이 원형 유지. 예) '생활지도' → 도 제거 안 함.
    """
    def _clean_zone(zone: str, skip_slots: bool = False) -> str:
        tokens = zone.split()
        cleaned = []
        for t in tokens:
            if skip_slots and t.startswith("__SLOT"):
                continue
            if t in _GLOSSARY_WORD_PARTS:
                cleaned.append(t)
                continue
            s = _KO_PARTICLES.sub("", t).strip()
            if len(s) >= 2:
                cleaned.append(s)
            elif len(t) >= 2:
                cleaned.append(t)
        return " ".join(cleaned)

    for trigger in _SENTENCE_TYPES.get(stype, []):
        idx = text.find(trigger)
        if idx == -1:
            continue
        before = text[:idx]
        last_pos = -1
        for boundary in SAFE_CLAUSE_BOUNDARIES:
            pos = before.rfind(boundary)
            if pos != -1:
                last_pos = max(last_pos, pos + len(boundary))
        zone = (before[last_pos:] if last_pos != -1 else before).strip()
        return _clean_zone(zone)

    # P8: apply stype — "신청을 … 해 주세요" 구조에서 날짜 범위 슬롯이 끼어
    # 키워드 직접 매칭 실패 시 "해 주세요" 위치에서 분리. 슬롯 토큰은 제외.
    if stype == "apply" and "해 주세요" in text:
        idx = text.find("해 주세요")
        before = text[:idx]
        last_pos = -1
        for boundary in SAFE_CLAUSE_BOUNDARIES:
            pos = before.rfind(boundary)
            if pos != -1:
                last_pos = max(last_pos, pos + len(boundary))
        zone = (before[last_pos:] if last_pos != -1 else before).strip()
        return _clean_zone(zone, skip_slots=True)

    return ""


def _extract_template_items(item_zone: str, glossary: list, target_lang: str) -> list[tuple[str, str]]:
    """동사 이전 구간(item_zone)에서만 glossary 검색 — 동사 오염 원천 차단."""
    lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang
    preferred_col = f"preferred_{lang_key}"
    text_norm = _normalize_glossary_key(item_zone)
    spans: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for row in sorted(glossary, key=lambda r: -len(r.get("korean", ""))):
        korean = row.get("korean", "").strip()
        preferred = row.get(preferred_col, "").strip()
        if not korean or not preferred or korean in _TEMPLATE_EXCLUDE_KO:
            continue
        ko_norm = _normalize_glossary_key(korean)
        start = text_norm.find(ko_norm)
        if start == -1:
            continue
        end = start + len(ko_norm)
        # 한자어 + "하" = "~하다" 동사 어근. "서명하여", "제출하여" 등 동사형은 명사 항목으로 추출 제외.
        if end < len(text_norm) and text_norm[end] == "하":
            continue
        if any(not (end <= a or start >= b) for a, b in occupied):
            continue
        spans.append((start, end, korean, preferred))
        occupied.append((start, end))
    spans.sort(key=lambda x: x[0])
    return [(ko, vi) for _, _, ko, vi in spans]


def _extract_audience(text: str, lang: str) -> str | None:
    for ko, val in _AUDIENCE_BY_LANG.get(lang, {}).items():
        if ko in text:
            return val
    return None


def _extract_recipient(text: str, lang: str) -> str | None:
    for ko, val in _RECIPIENT_BY_LANG.get(lang, {}).items():
        if ko in text:
            return val
    return None


def _join_items(items: list[str], lang: str) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    conj = _LANG_CONJUNCTIONS.get(lang, " and ")
    return ", ".join(items[:-1]) + conj + items[-1]


def _build_from_template(
    stype: str,
    items: list[tuple[str, str]],
    lang: str,
    audience: str | None,
    recipient: str | None,
    deadline: str | None = None,
    amount: str | None = None,
    method: str | None = None,
    time_context: str | None = None,
    start_date: str | None = None,
) -> str | None:
    if stype == "info" or not items:
        return None
    items_str = _join_items([tr for _, tr in items], lang)

    # P9: apply + 시작일 + 마감일 → 기간 범위 템플릿 우선 사용
    if stype == "apply" and start_date and deadline:
        range_tpl = _LANG_TEMPLATES_DEADLINE_RANGE.get(lang)
        if range_tpl:
            sentence = range_tpl.format(items=items_str, start_date=start_date, end_date=deadline)
            sentence = _apply_time_context(sentence, time_context, lang)
            if audience:
                prefix_tpl = _LANG_AUDIENCE_PREFIX.get(lang, "")
                if prefix_tpl:
                    sentence = prefix_tpl.format(audience=audience) + sentence
            return sentence

    # pay + amount: 금액 보존 전용 템플릿 우선 사용
    # method가 있으면 with_method/_deadline variant 선택
    if stype == "pay" and amount:
        pay_tpls = _LANG_TEMPLATES_PAY_AMOUNT.get(lang, {})
        if method and deadline and "with_method_deadline" in pay_tpls:
            sentence = pay_tpls["with_method_deadline"].format(
                items=items_str, amount=amount, method=method, deadline=deadline
            )
        elif method and "with_method" in pay_tpls:
            sentence = pay_tpls["with_method"].format(
                items=items_str, amount=amount, method=method
            )
        elif deadline and "with_deadline" in pay_tpls:
            sentence = pay_tpls["with_deadline"].format(
                items=items_str, amount=amount, deadline=deadline
            )
        elif "no_deadline" in pay_tpls:
            sentence = pay_tpls["no_deadline"].format(items=items_str, amount=amount)
        else:
            sentence = None
        if sentence:
            sentence = _apply_time_context(sentence, time_context, lang)
            if audience:
                prefix_tpl = _LANG_AUDIENCE_PREFIX.get(lang, "")
                if prefix_tpl:
                    sentence = prefix_tpl.format(audience=audience) + sentence
            return sentence

    # deadline이 있으면 deadline-aware 템플릿 우선 사용
    if deadline:
        deadline_tpl = _LANG_TEMPLATES_DEADLINE.get(lang, {}).get(stype)
        if deadline_tpl:
            sentence = deadline_tpl.format(items=items_str, deadline=deadline)
            sentence = _apply_time_context(sentence, time_context, lang)
            if audience:
                prefix_tpl = _LANG_AUDIENCE_PREFIX.get(lang, "")
                if prefix_tpl:
                    sentence = prefix_tpl.format(audience=audience) + sentence
            return sentence
    lang_templates = _LANG_TEMPLATES.get(lang, {})
    tpl = lang_templates.get(stype)
    if tpl is None:
        return None
    sentence = tpl.format(items=items_str)
    if recipient and stype == "submit":
        suffix_tpl = _LANG_RECIPIENT_SUFFIX.get(lang, "")
        if suffix_tpl:
            # 언어별 문장 종결자 제거 후 수신인 접미 붙이기
            sentence = sentence.rstrip(".。") + suffix_tpl.format(recipient=recipient)
            if lang not in ("zh", "ja", "th", "mn"):
                sentence += "."
    sentence = _apply_time_context(sentence, time_context, lang)
    if audience:
        prefix_tpl = _LANG_AUDIENCE_PREFIX.get(lang, "")
        if prefix_tpl:
            sentence = prefix_tpl.format(audience=audience) + sentence
    return sentence


def _extract_deadline_token(masked: str) -> str | None:
    """masked 문장에서 '__SLOTn__까지' 패턴의 마감일 토큰 추출."""
    m = _DEADLINE_RE.search(masked)
    return m.group(1) if m else None


def _extract_start_date_token(masked: str) -> str | None:
    """masked 문장에서 '__SLOTn__부터' 패턴의 시작일 토큰 추출 (P9: apply 기간 범위)."""
    m = _START_DATE_RE.search(masked)
    return m.group(1) if m else None


def _extract_amount_token(masked: str) -> str | None:
    """masked 문장에서 '__SLOTn__을/를' 형태의 금액 토큰 추출.

    '을 통해' 뒤는 수단 표현(스쿨뱅킹을 통해)이므로 제외.
    """
    m = _AMOUNT_RE.search(masked)
    return m.group(1) if m else None


def _extract_payment_method(masked: str, lang_key: str) -> tuple[str | None, str]:
    """masked 문장에서 납부 수단 표현(스쿨뱅킹을 통해, 계좌이체로 등)을 추출.

    반환: (translated_method, masked_without_method).
    - translated_method: 대상 언어로 번역된 수단 문자열 (예: "through School Banking")
    - masked_without_method: 수단 표현이 제거된 masked 문장
    수단 표현이 없으면 (None, masked) 반환.
    """
    for pattern, translations in _PAYMENT_METHOD_PATTERNS:
        m = pattern.search(masked)
        if m:
            translated = translations.get(lang_key, m.group(0))
            cleaned = masked[:m.start()] + masked[m.end():]
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            return translated, cleaned
    return None, masked


def _extract_time_context(masked: str, lang_key: str) -> tuple[str | None, str]:
    """masked 문장에서 Korean TC 표현(아직 마스킹 안 된 경우)을 추출.

    반환: (translated_time_context, masked_without_time_context).
    표현이 없으면 (None, masked) 반환.
    ※ 이미 _mask_protected_entities에서 TC 슬롯으로 변환된 경우는 _extract_time_context_token 사용.
    """
    m = _TIME_CONTEXT_SOURCE_RE.search(masked)
    if m:
        key = re.sub(r"\s+", "", m.group(0))
        translated = _TIME_CONTEXT_TRANSLATIONS.get(key, {}).get(lang_key, m.group(0))
        cleaned = masked[:m.start()] + masked[m.end():]
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return translated, cleaned
    return None, masked


_TC_SLOT_RE = re.compile(r"__SLOT(\d+)__")


def _extract_time_context_token(masked: str, placeholders: list[str]) -> tuple[str | None, str]:
    """masked 문장의 __SLOTn__ 중 'TC:' 접두 값을 가진 time_context 슬롯을 추출.

    _mask_protected_entities에서 TC: 접두로 stash된 시점·빈도 부사를 찾아 반환.
    반환: (translated_time_context, masked_without_tc_slot).
    """
    for m in _TC_SLOT_RE.finditer(masked):
        idx = int(m.group(1))
        if idx < len(placeholders) and placeholders[idx].startswith("TC:"):
            translated = placeholders[idx][3:]  # strip "TC:"
            cleaned = masked[:m.start()] + masked[m.end():]
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            return translated, cleaned
    return None, masked


def _apply_time_context(sentence: str, time_context: str | None, lang: str) -> str:
    """조립된 번역 문장에 time_context를 언어별 위치에 삽입."""
    if not time_context:
        return sentence
    suffix_tpl = _LANG_TIME_CONTEXT_SUFFIX.get(lang, " {time_context}.")
    return sentence.rstrip(".。") + suffix_tpl.format(time_context=time_context)


def _get_supply_label_zone(text: str) -> str | None:
    """준비물 label 문장에서 items 구간(준비물 키워드 이후) 반환. 없으면 None.

    "내일 준비물은 색종이, 풀, 가위입니다." → "색종이, 풀, 가위"
    "준비물: 개인 물병, 도시락" → "개인 물병, 도시락"
    """
    m = _SUPPLY_LABEL_RE.search(text)
    if not m:
        return None
    zone = text[m.end():]
    # 문장 종결자 이전까지만 추출
    for ender in ("입니다", "이에요", "예요", "임.", "임"):
        pos = zone.find(ender)
        if pos != -1:
            zone = zone[:pos]
            break
    zone = zone.rstrip(".。 \t").strip()
    return zone if zone else None


def _extract_noun_for_template(text: str, stype: str) -> str:
    """슬롯 없는 문장에서 동사구를 제거하고 명사구만 반환.

    "체육복과 실내화를 준비해 주세요" → "체육복과 실내화"
    슬롯 토큰(__SLOT0__)이 남아있으면 None 반환 — 슬롯 있는 문장은 NLLB가 처리.
    """
    if "__SLOT" in text:
        return ""
    for kw in _SENTENCE_TYPES.get(stype, []):
        idx = text.find(kw)
        if idx != -1:
            noun_part = text[:idx]
            tokens = noun_part.split()
            cleaned = []
            for tok in tokens:
                s = _KO_PARTICLES.sub("", tok).strip()
                if len(s) >= 2:
                    cleaned.append(s)
                elif len(tok) >= 2:
                    cleaned.append(tok)
                # else: 단독 1자 조사 토큰 → 버림 (ISSUE-03)
            return " ".join(cleaned)
    return ""


def _find_glossary_hits_safe(text: str, glossary: list, target_lang: str, min_len: int = 1) -> list[dict]:
    """Find glossary hits with whitespace normalization and length guard.

    min_len: glossary 항목의 최소 길이 (기본 1 → 2자 이상). NLLB fallback 경로에서는
    3을 권장 — 짧은 일반 단어(학생, 귀가)가 슬롯화되면 NLLB mixed-text 오역 유발(P10).
    """
    lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang
    preferred_col = f"preferred_{lang_key}"
    text_norm = _normalize_glossary_key(text)
    hits: list[dict] = []
    seen: set[str] = set()
    for row in glossary:
        korean = row.get("korean", "").strip()
        preferred = row.get(preferred_col, "").strip()
        if not korean or not preferred or len(korean) <= min_len:
            continue
        key = _normalize_glossary_key(korean)
        if key and key in text_norm and korean not in seen:
            hits.append({"korean": korean, "preferred_term": preferred})
            seen.add(korean)
    return hits


def _normalize_thousand_separator(text: str) -> str:
    def repl(m):
        return m.group(1).replace(".", ",")
    return _THOUSAND_DOT.sub(repl, text)


def _post_process_vi(easy_ko: str, vi_text: str) -> str:
    if not vi_text:
        return vi_text
    if _KRW_AMOUNT.search(easy_ko):
        for pat in _CURRENCY_PATTERNS:
            vi_text = pat.sub("won", vi_text)
        vi_text = _normalize_thousand_separator(vi_text)
    if _has_any(easy_ko, _STUDENT_CONTEXT_TERMS):
        for pat in _STUDENT_PATTERNS:
            vi_text = pat.sub("h\u1ecdc sinh", vi_text)
    if _has_any(easy_ko, _HOMEROOM_CONTEXT_TERMS):
        for pat in _HOMEROOM_PATTERNS:
            vi_text = pat.sub("gi\u00e1o vi\u00ean ch\u1ee7 nhi\u1ec7m", vi_text)
    if _has_any(easy_ko, _KINDERGARTEN_CONTEXT_TERMS):
        for pat in _KINDERGARTEN_PATTERNS:
            vi_text = pat.sub("tr\u1ebb m\u1eabu gi\u00e1o", vi_text)
    if _has_any(easy_ko, _FIELD_TRIP_CONTEXT_TERMS):
        for pat in _FIELD_TRIP_PATTERNS:
            vi_text = pat.sub("bu\u1ed5i tr\u1ea3i nghi\u1ec7m th\u1ef1c t\u1ebf", vi_text)
    vi_text = _apply_p11e('vi', easy_ko, vi_text)  # P11-E
    return vi_text.strip()


def _post_process_en(easy_ko: str, en_text: str) -> str:
    if not en_text:
        return en_text
    if _has_any(easy_ko, _HOMEROOM_CONTEXT_TERMS):
        for pat in _HOMEROOM_PATTERNS_EN:
            en_text = pat.sub('homeroom teacher', en_text)
    if _has_any(easy_ko, _ALLSTUDENT_CONTEXT_TERMS):
        for pat in _ALLSTUDENT_PATTERNS_EN:
            en_text = pat.sub('all students', en_text)
    if _has_any(easy_ko, _SCHOOL_TRIP_CONTEXT_TERMS):
        for pat in _SCHOOL_TRIP_PATTERNS_EN:
            en_text = pat.sub('school trip', en_text)
    if _has_any(easy_ko, _SCHOOL_NOTICE_CONTEXT_TERMS):
        for pat in _NEWSLETTER_PATTERNS_EN:
            en_text = pat.sub('school newsletter', en_text)
    if _has_any(easy_ko, _FIELD_TRIP_CONTEXT_TERMS):
        for pat in _FIELD_TRIP_PATTERNS_EN:
            en_text = pat.sub('field trip', en_text)
    en_text = _apply_p11e('en', easy_ko, en_text)  # P11-E
    return en_text.strip()


def _post_process_ru(easy_ko: str, ru_text: str) -> str:
    if not ru_text:
        return ru_text
    if _has_any(easy_ko, _HOMEROOM_CONTEXT_TERMS):
        for pat in _HOMEROOM_PATTERNS_RU:
            ru_text = pat.sub('классному руководителю', ru_text)
    if _has_any(easy_ko, _SCHOOL_TRIP_CONTEXT_TERMS):
        for pat in _SCHOOL_TRIP_PATTERNS_RU:
            ru_text = pat.sub('школьной поездке', ru_text)
    if _has_any(easy_ko, _SCHOOL_NOTICE_CONTEXT_TERMS):
        for pat in _NEWSLETTER_PATTERNS_RU:
            ru_text = pat.sub('школьному сообщению', ru_text)
    if _has_any(easy_ko, _FIELD_TRIP_CONTEXT_TERMS):
        for pat in _PICNIC_PATTERNS_RU:
            ru_text = pat.sub('пикника', ru_text)
    ru_text = _apply_p11e('ru', easy_ko, ru_text)  # P11-E
    return ru_text.strip()


def _post_process_ms(easy_ko: str, ms_text: str) -> str:
    if not ms_text:
        return ms_text
    if _has_any(easy_ko, _HOMEROOM_CONTEXT_TERMS):
        for pat in _HOMEROOM_PATTERNS_MS:
            ms_text = pat.sub('guru kelas', ms_text)
    if _has_any(easy_ko, _ALLSTUDENT_CONTEXT_TERMS):
        for pat in _ALLSTUDENT_PATTERNS_MS:
            ms_text = pat.sub('semua pelajar', ms_text)
    if _has_any(easy_ko, _SCHOOL_TRIP_CONTEXT_TERMS):
        for pat in _SCHOOL_TRIP_PATTERNS_MS:
            ms_text = pat.sub('lawatan sambil belajar', ms_text)
    if _has_any(easy_ko, _SCHOOL_NOTICE_CONTEXT_TERMS):
        for pat in _NEWSLETTER_PATTERNS_MS:
            ms_text = pat.sub('surat edaran sekolah', ms_text)
    if _has_any(easy_ko, _GUIDANCE_CONTEXT_TERMS):  # P11-B
        for pat in _GUIDANCE_PATTERNS_MS:
            ms_text = pat.sub('bimbingan', ms_text)
    ms_text = _apply_p11e('ms', easy_ko, ms_text)  # P11-E
    return ms_text.strip()


def _post_process_mn(easy_ko: str, mn_text: str) -> str:
    if not mn_text:
        return mn_text
    if _has_any(easy_ko, _ALLSTUDENT_CONTEXT_TERMS):
        for pat in _ALLSTUDENT_PATTERNS_MN:
            mn_text = pat.sub('бүх сурагчид', mn_text)
    if _has_any(easy_ko, _SCHOOL_TRIP_CONTEXT_TERMS):
        for pat in _SCHOOL_TRIP_PATTERNS_MN:
            mn_text = pat.sub('сургуулийн аялалд', mn_text)
    if _has_any(easy_ko, _GUIDANCE_CONTEXT_TERMS):  # P11-B
        for pat in _GUIDANCE_PATTERNS_MN:
            mn_text = pat.sub('хяналт', mn_text)
    mn_text = _apply_p11e('mn', easy_ko, mn_text)  # P11-E
    return mn_text.strip()


def _post_process_zh(easy_ko: str, zh_text: str) -> str:
    if not zh_text:
        return zh_text
    if _has_any(easy_ko, _HOMEROOM_CONTEXT_TERMS):
        for pat in _HOMEROOM_PATTERNS_ZH:
            zh_text = pat.sub('班主任', zh_text)
    if _has_any(easy_ko, _ALLSTUDENT_CONTEXT_TERMS):
        for pat in _ALLSTUDENT_PATTERNS_ZH:
            zh_text = pat.sub('全校学生', zh_text)
    if _has_any(easy_ko, _SCHOOL_TRIP_CONTEXT_TERMS):
        for pat in _SCHOOL_TRIP_PATTERNS_ZH:
            zh_text = pat.sub('修学旅行', zh_text)
    if _has_any(easy_ko, _SCHOOL_NOTICE_CONTEXT_TERMS):
        for pat in _NEWSLETTER_PATTERNS_ZH:
            zh_text = pat.sub('家长通知书', zh_text)
    if _has_any(easy_ko, _LUNCH_CONTEXT_TERMS):
        for pat in _LUNCH_PATTERNS_ZH:
            zh_text = pat.sub('餐费', zh_text)
    zh_text = _apply_p11e('zh', easy_ko, zh_text)  # P11-E
    return zh_text.strip()


def _post_process_th(easy_ko: str, th_text: str) -> str:
    if not th_text:
        return th_text
    # NLLB에서 TH 출력 반복 홍 hallucination 방어
    th_text = _TH_LOOP_RE.sub(r'', th_text)
    if _has_any(easy_ko, _ALLSTUDENT_CONTEXT_TERMS):
        for pat in _ALLSTUDENT_PATTERNS_TH:
            th_text = pat.sub('นักเรียนทุกคน', th_text)
    if _has_any(easy_ko, _ELEMENTARY_CONTEXT_TERMS):
        for pat in _ELEMENTARY_PATTERNS_TH:
            th_text = pat.sub('นักเรียนชั้นประถมศึกษา', th_text)
    if _has_any(easy_ko, _GUIDANCE_CONTEXT_TERMS):  # P11-B
        for pat in _GUIDANCE_PATTERNS_TH:
            th_text = pat.sub('การดูแล', th_text)
    th_text = _apply_p11e('th', easy_ko, th_text)  # P11-E
    return th_text.strip()


def _post_process_ja(easy_ko: str, ja_text: str) -> str:
    if not ja_text:
        return ja_text
    if _has_any(easy_ko, _HOMEROOM_CONTEXT_TERMS):
        for pat in _HOMEROOM_PATTERNS_JA:
            ja_text = pat.sub('担任の先生', ja_text)
    if _has_any(easy_ko, _SCHOOL_TRIP_CONTEXT_TERMS):
        for pat in _SCHOOL_TRIP_PATTERNS_JA:
            ja_text = pat.sub('修学旅行', ja_text)
    if _has_any(easy_ko, _SCHOOL_NOTICE_CONTEXT_TERMS):
        for pat in _NEWSLETTER_PATTERNS_JA:
            ja_text = pat.sub('学校からのお知らせ', ja_text)
    if _has_any(easy_ko, _ELEMENTARY_CONTEXT_TERMS):
        for pat in _ELEMENTARY_PATTERNS_JA:
            ja_text = pat.sub('小学生の子供', ja_text)
    if _has_any(easy_ko, _INFANT_CONTEXT_TERMS):
        for pat in _INFANT_PATTERNS_JA:
            ja_text = pat.sub('幼児', ja_text)
    if _has_any(easy_ko, _LUNCH_CONTEXT_TERMS):
        for pat in _LUNCH_PATTERNS_JA:
            ja_text = pat.sub('給食費を支払う', ja_text)
    if _has_any(easy_ko, _GUIDANCE_CONTEXT_TERMS):  # P11-B
        for pat in _GUIDANCE_PATTERNS_JA:
            ja_text = pat.sub('ご指導', ja_text)
    ja_text = _apply_p11e('ja', easy_ko, ja_text)  # P11-E
    return ja_text.strip()


def _post_process(lang: str, easy_ko: str, text: str) -> str:
    if lang == 'vi':
        return _post_process_vi(easy_ko, text)
    if lang == 'en':
        return _post_process_en(easy_ko, text)
    if lang == 'ru':
        return _post_process_ru(easy_ko, text)
    if lang == 'ms':
        return _post_process_ms(easy_ko, text)
    if lang == 'mn':
        return _post_process_mn(easy_ko, text)
    if lang == 'zh':
        return _post_process_zh(easy_ko, text)
    if lang == 'th':
        return _post_process_th(easy_ko, text)
    if lang == 'ja':
        return _post_process_ja(easy_ko, text)
    return text


# 고유명사(장소명) 보호 — NLLB에 넣으면 오역되는 한국 고유 시설명을 한글 그대로 유지.
# 복원 값 = 한글 원문 그대로 → 어느 언어 출력에서도 동일하게 보임.
# NLLB는 __SLOT0__에서... 처럼 조사가 붙어있어도 위치 맥락을 파악해 tại/在 등 전치사 삽입.
_PLACE_SUFFIX = (
    r"(?:박물관|미술관|과학관|천문대|체험관|기념관|생태관|역사관"
    r"|동물원|식물원|수목원|전시관|문화관|문화원|문화회관|기념회관"
    r"|공연장|체육관|빙상장|수영장|야영장|캠핑장|공원|정원|회관|센터)"
)
_PROPER_PLACE = re.compile(
    # 국립/시립 등 접두 + 최대 12자 한글 + 시설 접미 (서울특별시교육청과학전시관 등 커버)
    r"(?:국립|시립|도립|구립|군립|사립|공립)[가-힣]{1,12}" + _PLACE_SUFFIX
    # 고유명사 1-2단어(공백 포함) + 선택적 공백 + 시설 접미 (최대 12자로 확장)
    + r"|[가-힣a-zA-Z]{1,12}(?:\s[가-힣a-zA-Z]{1,8})?\s?" + _PLACE_SUFFIX
)
# 시간/방향 부사나 조사로 끝나는 단어가 앞에 오면 오탐 발생
# stash_place에서 첫 단어가 이 목록이거나 조사 어미로 끝나면 보호 제외
_PLACE_NON_PREFIX: frozenset[str] = frozenset([
    "금일", "오늘", "내일", "모레", "이번", "다음", "당일", "매일", "매주", "매월",
    "현재", "현장", "해당", "관련", "각종", "여러", "일부", "방문", "견학",
])
# 조사/어미로 끝나는 단어 → 고유명사 아님 (학생들은, 어린이는, 학부모가 등)
_JOSA_ENDING = re.compile(r"[은는이가을를도]$")

# OCR 변환 과정에서 생기는 특수문자 제거. HWP 체크박스/불릿이 □·▣ 등으로 깨지는 패턴.
_OCR_NOISE = re.compile(r"[□■▣▷◆◇▶◀►◄■-◿`]+")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def _clean_for_translation(text: str) -> str:
    """NLLB 입력 전 OCR 잔여 특수문자를 제거한다."""
    text = _OCR_NOISE.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


# URL/전화 보호 — NLLB가 깨먹는 패턴 방어.
# ⟦…⟧ (U+27E6/27E7) 는 NLLB SentencePiece 어휘에 없어서 tokenize 시 소실됨 → "P0"만 남아 복원 실패.
# __SLOT0__ 형태(ASCII 대문자 + 언더스코어)는 NLLB가 코드/약어로 인식해 그대로 통과.
# NLLB가 "SLOT" → "SLO T" 로 쪼개는 경우도 복원할 수 있도록 SLO\s+T 패턴 추가.
_PROTECT_TOKEN = re.compile(
    r"(?:_{1,2}\s*)?S\s*L\s*O\s*T\s*(\d+)\s*_*",
    re.IGNORECASE,
)
_RESIDUAL_PROTECT_TOKEN = re.compile(
    r"_{1,2}\s*S\s*L\s*O\s*[A-Z0-9_ ]*_{1,2}\.*"
    r"|(?<![A-Za-z])S\s*L\s*O\s*T\s*\d+\.*(?![A-Za-z])",
    re.IGNORECASE,
)


def _mask_protected_entities(text: str, target_lang: str | None = None) -> tuple[str, list[str]]:
    """URL/전화/날짜/시간/금액 → __SLOT0__ 등 토큰. (masked, restore_values) 반환."""
    placeholders: list[str] = []

    def stash_value(value: str) -> str:
        placeholders.append(value)
        return f"__SLOT{len(placeholders) - 1}__"

    def stash_match(match: re.Match) -> str:
        return stash_value(match.group(0))

    def stash_url(match: re.Match) -> str:
        # URL 뒤에 붙은 한국어 조사("에서", "을" 등)를 분리해 텍스트로 되돌림.
        # "www.school.kr에서" → stash("www.school.kr") + "에서" 반환.
        url = match.group(0)
        josa_m = _URL_TRAILING_JOSA.search(url)
        if josa_m:
            josa = url[josa_m.start():]
            url = url[:josa_m.start()]
            return stash_value(url) + josa
        return stash_value(url)

    masked = _URL.sub(stash_url, text)
    masked = _PHONE.sub(stash_match, masked)

    def stash_place(m: re.Match) -> str:
        # 첫 단어가 시간/방향 부사면 보호 제외 (예: 금일 식물원, 오늘 체육관)
        text = m.group(0)
        first = text.split()[0]
        if first in _PLACE_NON_PREFIX:
            return text
        # 첫 단어가 조사 어미로 끝나면 첫 단어만 제외하고 나머지 장소명은 슬롯 처리
        # (예: 학생들은 국립해양박물관 → 학생들은 + [SLOT:국립해양박물관])
        if _JOSA_ENDING.search(first):
            rest = text[len(first):].lstrip()
            return first + " " + stash_value(rest)
        return stash_value(text)

    masked = _PROPER_PLACE.sub(stash_place, masked)  # 고유명사 한글 그대로 보존

    if target_lang and target_lang != "ko_easy":
        lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang

        # 요일/상대기한을 먼저 마스킹: "다음 주 월요일", "이번 주 금요일", "금요일" 등
        # extract_dates 보다 먼저 실행해야 "월요일"만 단독 추출되는 것을 방지.
        masked = _WEEKDAY_DEADLINE_SOURCE_RE.sub(
            lambda m: stash_value(_translate_weekday_deadline(m.group(0), lang_key)),
            masked,
        )

        # P4: 월말/월초/중순/학기말 상대 기한 마스킹 — extract_dates가 처리 못하는 패턴 방어.
        masked = _MONTH_PERIOD_SOURCE_RE.sub(
            lambda m: stash_value(_translate_month_period_deadline(m.group(0), lang_key)),
            masked,
        )

        # P6: 소풍/체험학습/운동회 당일 등 이벤트 복합 표현 — P3("당일" 단독) 보다 먼저 마스킹.
        masked = _EVENT_CONTEXT_COMPOUND_RE.sub(
            lambda m: stash_value("TC:" + _translate_event_context_compound(m.group(0), lang_key)),
            masked,
        )

        # P3: 시점·빈도 부사 마스킹 — "내일"·"오늘" 등이 extract_dates에 소모되는 것을 방지.
        # "TC:" 접두를 붙여 _restore_protected_entities에서 벗겨낼 수 있게 마킹.
        masked = _TIME_CONTEXT_SOURCE_RE.sub(
            lambda m: stash_value("TC:" + _translate_time_context(m.group(0), lang_key)),
            masked,
        )

        slot_values: list[tuple[str, str]] = []
        date_items = extract_dates(masked)
        time_items = extract_times(masked)
        _merged_ko: set[str] = set()
        # P7: 날짜+시간이 인접한 경우 하나의 슬롯으로 병합 — NLLB가 시간 슬롯만 탈락시키는 현상 방지.
        for _d in date_items:
            for _ti in time_items:
                _combined_ko = _d["ko"] + " " + _ti["ko"]
                if _combined_ko in masked:
                    _combined_tr = format_date(_d, target_lang) + " " + format_time(_ti, target_lang)
                    slot_values.append((_combined_ko, _combined_tr))
                    _merged_ko.add(_d["ko"])
                    _merged_ko.add(_ti["ko"])
        slot_values.extend((_d["ko"], format_date(_d, target_lang)) for _d in date_items if _d["ko"] not in _merged_ko)
        slot_values.extend((_ti["ko"], format_time(_ti, target_lang)) for _ti in time_items if _ti["ko"] not in _merged_ko)
        slot_values.extend((a["ko"], format_amount(a, target_lang)) for a in extract_amounts(masked))

        for source, translated in sorted(slot_values, key=lambda item: len(item[0]), reverse=True):
            if source and source in masked:
                masked = masked.replace(source, stash_value(translated or source))
    return masked, placeholders


# NLLB가 스쿨뱅킹 계좌 이체 관련 문장에서 "___" 를 출력하는 hallucination 패턴 제거
_NLLB_UNDERSCORE = re.compile(r"_{2,}")


def _strip_residual_protect_tokens(text: str) -> str:
    text = _RESIDUAL_PROTECT_TOKEN.sub("", text)
    text = _NLLB_UNDERSCORE.sub("", text)   # NLLB underscore artifact 제거
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _restore_protected_entities(text: str, placeholders: list[str]) -> str:
    def restore(match: re.Match) -> str:
        idx = int(match.group(1))
        val = placeholders[idx] if idx < len(placeholders) else ""
        # P3: "TC:" 접두는 마킹용 — 복원 시 제거
        return val[3:] if val.startswith("TC:") else val

    restored = _PROTECT_TOKEN.sub(restore, text)
    return _strip_residual_protect_tokens(restored)


def _is_url_or_phone(text: str) -> bool:
    """슬롯 단위 번역 시 URL/전화면 NLLB 안 거치고 ko 그대로 반환하기 위한 가드."""
    s = text.strip()
    return bool(_URL.fullmatch(s) or _PHONE.fullmatch(s))


# glossary CSV에 없는 UI 라벨 고정 번역 — 카드 헤더/라벨 한국어 노출 방지
_TERM_OVERRIDES: dict[str, dict[str, str]] = {
    "지원안내": {
        "vi": "Thông tin hỗ trợ",
        "en": "Support information",
        "zh": "支援信息",
        "ja": "支援案内",
        "th": "ข้อมูลการสนับสนุน",
        "ms": "Maklumat sokongan",
        "mn": "Дэмжлэгийн мэдээлэл",
        "ru": "Информация о поддержке",
    },
    "지원정보": {
        "vi": "Thông tin hỗ trợ",
        "en": "Support information",
        "zh": "支援信息",
        "ja": "支援情報",
    },
    # "일시"와 "시간" 둘 다 NLLB → "Thời gian"으로 번역되어 같은 헤더로 보임.
    # 일시(日時) = 날짜+시간 복합, 시간(時間) = 시각/시간대 → 의미 구분용 override.
    "일시": {
        "vi": "Ngày và giờ",
        "en": "Date & Time",
        "zh": "日期与时间",
        "ja": "日時",
        "th": "วันและเวลา",
        "ms": "Tarikh & Masa",
        "mn": "Огноо ба цаг",
        "ru": "Дата и время",
    },
    "제출": {
        "vi": "Nộp tài liệu",
        "en": "Submission",
        "zh": "提交",
        "ja": "提出",
        "th": "การส่งเอกสาร",
        "ms": "Penghantaran",
        "mn": "Илгээх",
        "ru": "Сдача документов",
    },
    "활동내용": {
        "vi": "Nội dung hoạt động",
        "en": "Activity",
        "zh": "活动内容",
        "ja": "活動内容",
        "th": "กิจกรรม",
        "ms": "Kandungan aktiviti",
        "mn": "Үйл ажиллагааны агуулга",
        "ru": "Содержание мероприятия",
    },
    "프로그램": {
        "vi": "Chương trình",
        "en": "Program",
        "zh": "项目",
        "ja": "プログラム",
        "th": "โปรแกรม",
        "ms": "Program",
        "mn": "Хөтөлбөр",
        "ru": "Программа",
    },
}


def translate_term(text: str, target_lang: str) -> str:
    """glossary 직접 치환 (summary 슬롯용 — places, supplies, deadlines).

    exact match 우선. 없으면 한국어 원문 그대로 반환 (빈 문자열 금지).
    고유명사("서울숲 생태체험관")처럼 사전에 없으면 한국어 노출이 NLLB 오역보다 낫다.
    URL/전화는 어떤 언어든 ko 그대로 (방어적 가드).
    공백 normalize: HWP 표 셀 변형 "일 시" / "장 소" / "대 상" 도 "일시"/"장소"/"대상"
    glossary 항목에 매치되도록 양쪽 공백 제거 후 비교.
    """
    if not text or not text.strip():
        return text
    if target_lang == "ko_easy" or _is_url_or_phone(text):
        return text

    term_norm = re.sub(r"\s+", "", text.strip())
    lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang  # vi_demo → vi

    # 1) 하드코딩 override — glossary CSV 미등록 UI 라벨 우선 처리
    override = _TERM_OVERRIDES.get(term_norm, {})
    if override.get(lang_key):
        return override[lang_key]

    # 2) glossary CSV 매칭
    glossary = _get_glossary()
    for row in glossary:
        if re.sub(r"\s+", "", row.get("korean", "")) == term_norm:
            translated = row.get(f"preferred_{lang_key}", "").strip()
            if translated:
                return translated
    log_unknown(text, target_lang)
    return text  # Korean passthrough


def translate_short_sentence(text: str, target_lang: str) -> str:
    """짧은 문장 번역 (items[].title_translated용).

    vi + prepare/bring/submit/attend/pay 유형: 템플릿 번역 (NLLB 없이 용어 100% 보존).
    나머지: URL/전화 보호 → glossary injection → NLLB → 보호 토큰 복원 → vi post-process.
    실패 시 빈 문자열 반환 (호출부가 fallback 처리).
    """
    if not text or not text.strip():
        return ""
    if target_lang == "ko_easy":
        return text
    text = _clean_for_translation(text)[:MAX_TRANSLATE_CHARS]

    # 1) URL/전화/날짜/시간/금액 placeholder 치환
    masked, placeholders = _mask_protected_entities(text, target_lang)

    # 마스킹 후 한국어·알파벳이 없으면 NLLB에 보낼 내용 없음 → 바로 복원.
    # 케이스 A: "일시: __SLOT0__ __SLOT1__" → SLOT 제거 후 빈 문자열
    # 케이스 B: "23.(토) / __SLOT0__ ~ __SLOT1__" → SLOT 제거 후 "/ ~" (구두점만 남음)
    # 양쪽 모두 NLLB는 "Tôi không biết"를 반환 — 스킵이 맞다.
    _non_slot = re.sub(r"(?:_{0,2})\s*SLOT\s*\d+\s*_*", "", masked, flags=re.IGNORECASE)
    if not re.search(r"[가-힣a-zA-Z]", _non_slot):
        return _restore_protected_entities(masked, placeholders)

    # 2) Template-based (모든 언어): 문장 유형 분류 → glossary 직접 매핑 → 템플릿 조립
    # ko_easy는 원문 그대로이므로 제외. LANG_TEMPLATES에 없는 언어는 자동 NLLB fallback.
    lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang
    if lang_key in _LANG_TEMPLATES:
        stype = _classify_sentence(text)

        # 2a) 준비물 label 패턴 — "준비물은 A, B, C입니다" (동사 트리거 없는 info형)
        if stype == "info":
            supply_zone = _get_supply_label_zone(text)
            if supply_zone:
                glossary = _get_glossary()
                _build_role_sets(glossary)
                # P3: TC 슬롯에서 time_context 추출 — "내일 준비물은..." 의 내일 보존
                # _mask_protected_entities에서 "TC:" 접두로 stash된 슬롯을 탐색
                tc_str_s, _ = _extract_time_context_token(masked, placeholders)
                supply_items = _extract_template_items(supply_zone, glossary, lang_key)
                if supply_items:
                    items_joined = _join_items([tr for _, tr in supply_items], lang_key)
                    if tc_str_s:
                        tpl = _LANG_SUPPLY_LABEL_TIME.get(lang_key, "")
                        if tpl:
                            result = tpl.format(time_context=tc_str_s, items=items_joined)
                            return _restore_protected_entities(result, placeholders)
                    tpl = _LANG_SUPPLY_LABEL.get(lang_key, "")
                    if tpl:
                        result = tpl.format(items=items_joined)
                        return _restore_protected_entities(result, placeholders)

        if stype != "info":
            glossary = _get_glossary()
            _build_role_sets(glossary)
            # 납부 수단 표현("스쿨뱅킹을 통해" 등) 먼저 제거: item으로 오분류 방지
            method_str: str | None = None
            if stype == "pay":
                method_str, masked = _extract_payment_method(masked, lang_key)
            # P3: TC 슬롯에서 시점·빈도 부사 추출 — item 오분류 방지
            # masked에서 "TC:" 접두 슬롯을 찾아 제거; 제거 후 masked에는 해당 슬롯 없음
            time_context_str: str | None
            time_context_str, masked = _extract_time_context_token(masked, placeholders)
            if time_context_str is None:
                # fallback: masked에 Korean TC 표현이 그대로 있는 경우 (ko_easy 등 예외)
                time_context_str, masked = _extract_time_context(masked, lang_key)
            # masked 기준으로 item_zone 추출: 요일/날짜/금액/수단/시점이 __SLOTn__ 또는
            # 제거된 상태이므로 item 오염 방지.
            item_zone = _get_item_zone(masked, stype)
            items = _extract_template_items(item_zone, glossary, lang_key)
            if not items:
                # glossary 미감지 + 슬롯 없음 → 명사구만 NLLB 단독 번역 후 템플릿 채움
                noun = _extract_noun_for_template(masked, stype)
                if noun and re.search(r"[가-힣]", noun):
                    try:
                        noun_tr = _translate(noun, target_nllb=LANG_TO_NLLB.get(lang_key, "vie_Latn"))
                        if noun_tr:
                            items = [(noun, noun_tr)]
                    except Exception:
                        pass
            if items:
                audience = _extract_audience(text, lang_key)
                recipient = _extract_recipient(text, lang_key)
                deadline = _extract_deadline_token(masked)
                start_date = _extract_start_date_token(masked) if stype == "apply" else None
                amount = _extract_amount_token(masked) if stype == "pay" else None
                result = _build_from_template(stype, items, lang_key, audience, recipient, deadline=deadline, amount=amount, method=method_str, time_context=time_context_str, start_date=start_date)
                if result:
                    result = _apply_p11e(lang_key, text, result)  # P11-E: 역전/드롭 교정
                    return _restore_protected_entities(result, placeholders)

    # 3) NLLB fallback — info 유형, 템플릿 미지원 언어, glossary 항목 미감지
    # P10: min_len=2 — 2자 이하 일반 단어(학생, 귀가 등)가 슬롯화되면 NLLB mixed-text 오역 유발.
    # 3자 도메인 용어(급식비 등)는 주입 필요하므로 min_len을 3→2로 조정.
    glossary = _get_glossary()
    hits = _find_glossary_hits_safe(masked, glossary, target_lang, min_len=2)
    # glossary 용어를 __SLOT__으로 보호: "스쿨뱅킹(School Banking)" 주입 방식은
    # NLLB가 한국어 음역 + 괄호 힌트를 둘 다 번역해 "School Banking (School Banking)"
    # 중복 출력하는 문제 발생. 대신 번역어를 restore 값으로 stash해 NLLB 통과 후 복원.
    injected = masked
    for hit in sorted(hits, key=lambda h: len(h["korean"]), reverse=True):
        korean = hit["korean"]
        preferred = hit["preferred_term"]
        while korean in injected:
            idx = len(placeholders)
            placeholders.append(preferred)
            injected = injected.replace(korean, f"__SLOT{idx}__", 1)

    target_nllb = LANG_TO_NLLB.get(target_lang, "vie_Latn")
    try:
        translated = _translate(injected, target_nllb=target_nllb)
        translated = _post_process(target_lang, text, translated)
    except Exception as error:
        print(f"[translator] translate_short_sentence failed: {error}")
        return ""

    # P7: URL 슬롯 복원 — NLLB가 __SLOTn__ URL 플레이스홀더를 제거한 경우 문장 끝에 재삽입.
    _referenced = {int(m.group(1)) for m in re.finditer(r"__SLOT(\d+)__", translated)}
    _url_suffix: list[str] = []
    for _i, _val in enumerate(placeholders):
        if _i not in _referenced and re.match(r"https?://|www\.", _val):
            _url_suffix.append(f"({_val})")
    if _url_suffix:
        translated = translated.rstrip("。.") + " " + " ".join(_url_suffix)

    return _restore_protected_entities(translated, placeholders)


def translate_short_sentence_reviewed(text: str, target_lang: str) -> dict:
    """review_required 메타데이터 포함 번역.

    반환:
        {
            "translated_text": str,
            "review_required": bool,
            "review_reason": "NON_PARENT_TARGET" | "RISKY_CONTEXT" | None,
        }

    - NON_PARENT_TARGET: 교사/행정실 대상 문장 → 부모 앱 자동 확정 금지
    - RISKY_CONTEXT: 부정문/조건문/선택사항 → 템플릿 결과라도 검수 필요
    번역은 항상 실행 (앱 화면 보존). review_required=True이면 UI에서 검수 표시.
    """
    if not text or not text.strip():
        return {"translated_text": "", "review_required": False, "review_reason": None}
    if target_lang == "ko_easy":
        return {"translated_text": text, "review_required": False, "review_reason": None}

    review_required = False
    review_reason: str | None = None

    if detect_non_parent_target(text):
        review_required = True
        review_reason = "NON_PARENT_TARGET"
    else:
        risky = detect_risky_context(text)
        if risky:
            review_required = True
            review_reason = "RISKY_CONTEXT"

    translated = translate_short_sentence(text, target_lang)
    if review_required and translated:
        lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang
        warning = _REVIEW_WARNING.get(lang_key, "")
        if warning:
            translated = translated.rstrip() + warning
    return {
        "translated_text": translated,
        "review_required": review_required,
        "review_reason": review_reason,
    }


def translate_short_sentence_batch(texts: list[str], target_lang: str) -> list[str]:
    """`translate_short_sentence`의 batch 버전.

    각 텍스트별 mask + vi 템플릿 시도 후, NLLB로 가야 할 것만 한 번에 batch generate.
    14건 단일 호출(70~75초) → 1회 batch(20~30초) 단축.
    입력 순서 유지 — `texts[i]` ↔ `result[i]`.
    """
    if not texts:
        return []
    if target_lang == "ko_easy":
        return list(texts)

    n = len(texts)
    results: list[str] = [""] * n

    nllb_indices: list[int] = []
    nllb_inputs: list[str] = []
    nllb_placeholders: list[list[str]] = []
    nllb_originals: list[str] = []

    glossary = _get_glossary()
    lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang
    if lang_key in _LANG_TEMPLATES:
        _build_role_sets(glossary)

    for i, text in enumerate(texts):
        if not text or not text.strip():
            continue
        cleaned = _clean_for_translation(text)[:MAX_TRANSLATE_CHARS]
        masked, placeholders = _mask_protected_entities(cleaned, target_lang)

        # 한국어·알파벳 없으면 NLLB 불필요 → 바로 복원 (단일 버전과 동일 처리)
        _non_slot = re.sub(r"(?:_{0,2})\s*SLOT\s*\d+\s*_*", "", masked, flags=re.IGNORECASE)
        if not re.search(r"[가-힣a-zA-Z]", _non_slot):
            results[i] = _restore_protected_entities(masked, placeholders)
            continue

        # 템플릿 분기 (모든 언어) — 매칭되면 NLLB 우회
        if lang_key in _LANG_TEMPLATES:
            stype = _classify_sentence(cleaned)

            # 준비물 label 패턴 (info형) — "준비물은 A, B, C입니다"
            if stype == "info":
                supply_zone = _get_supply_label_zone(cleaned)
                if supply_zone:
                    # P3: TC 슬롯에서 time_context 추출 — "내일 준비물은..." 의 내일 보존
                    tc_str_b, _ = _extract_time_context_token(masked, placeholders)
                    supply_items = _extract_template_items(supply_zone, glossary, lang_key)
                    if supply_items:
                        items_joined_b = _join_items([tr for _, tr in supply_items], lang_key)
                        if tc_str_b:
                            tpl = _LANG_SUPPLY_LABEL_TIME.get(lang_key, "")
                            if tpl:
                                template_result = tpl.format(time_context=tc_str_b, items=items_joined_b)
                                results[i] = _restore_protected_entities(template_result, placeholders)
                                continue
                        tpl = _LANG_SUPPLY_LABEL.get(lang_key, "")
                        if tpl:
                            template_result = tpl.format(items=items_joined_b)
                            results[i] = _restore_protected_entities(template_result, placeholders)
                            continue

            if stype != "info":
                method_str_b: str | None = None
                if stype == "pay":
                    method_str_b, masked = _extract_payment_method(masked, lang_key)
                # P3: TC 슬롯에서 시점·빈도 부사 추출 — item 오분류 방지
                time_context_str_b: str | None
                time_context_str_b, masked = _extract_time_context_token(masked, placeholders)
                if time_context_str_b is None:
                    time_context_str_b, masked = _extract_time_context(masked, lang_key)
                item_zone = _get_item_zone(masked, stype)
                items = _extract_template_items(item_zone, glossary, lang_key)
                if not items:
                    noun = _extract_noun_for_template(masked, stype)
                    if noun and re.search(r"[가-힣]", noun):
                        try:
                            noun_tr = _translate(noun, target_nllb=LANG_TO_NLLB.get(lang_key, "vie_Latn"))
                            if noun_tr:
                                items = [(noun, noun_tr)]
                        except Exception:
                            pass
                if items:
                    audience = _extract_audience(cleaned, lang_key)
                    recipient = _extract_recipient(cleaned, lang_key)
                    deadline = _extract_deadline_token(masked)
                    start_date = _extract_start_date_token(masked) if stype == "apply" else None
                    amount = _extract_amount_token(masked) if stype == "pay" else None
                    template_result = _build_from_template(stype, items, lang_key, audience, recipient, deadline=deadline, amount=amount, method=method_str_b, time_context=time_context_str_b, start_date=start_date)
                    if template_result:
                        results[i] = _restore_protected_entities(template_result, placeholders)
                        continue

        # NLLB 행 — glossary 용어를 __SLOT__ 으로 보호 후 batch 입력에 추가
        # P10: min_len=2 — 2자 이하 단어 슬롯화 차단; 3자 도메인 용어(급식비 등)는 주입
        hits = _find_glossary_hits_safe(masked, glossary, target_lang, min_len=2)
        injected = masked
        for hit in sorted(hits, key=lambda h: len(h["korean"]), reverse=True):
            korean = hit["korean"]
            preferred = hit["preferred_term"]
            while korean in injected:
                slot_idx = len(placeholders)
                placeholders.append(preferred)
                injected = injected.replace(korean, f"__SLOT{slot_idx}__", 1)

        nllb_indices.append(i)
        nllb_inputs.append(injected)
        nllb_placeholders.append(placeholders)
        nllb_originals.append(cleaned)

    if nllb_inputs:
        target_nllb = LANG_TO_NLLB.get(target_lang, "vie_Latn")
        try:
            translated_batch = _translate_batch_cached(nllb_inputs, target_nllb=target_nllb)
        except Exception as error:
            print(f"[translator] translate_short_sentence_batch failed: {error}")
            translated_batch = ["" for _ in nllb_inputs]

        for idx, translated, ph, original in zip(
            nllb_indices, translated_batch, nllb_placeholders, nllb_originals,
        ):
            translated = _post_process(target_lang, original, translated)
            results[idx] = _restore_protected_entities(translated, ph)

    return results


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
        translated = _post_process(target_lang, easy_ko_text, translated)
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

