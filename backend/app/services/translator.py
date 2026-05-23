"""세종님 NLLB 번역 + 용어 검수 wrapper.

run_mvp_pipeline.py의 가벼운 함수들(easy_korean, glossary)은 직접 호출.
NLLB 번역은 매번 모델 새로 로드하지 않게 캐싱.

URL/전화는 NLLB가 토큰화하면서 깨먹는 패턴이라 placeholder 치환 + 복원으로 보호.
세종님 요청(2026-04-29).

성능 최적화 (2026-05-06, 시연 ~10s 목표):
- num_beams 4 → 1 (greedy): -50% latency, 학교 공지 도메인은 beam 효과 미미
- @lru_cache: 분석 1번에 같은 한국어 슬롯/카드 헤더가 반복 등장 → 재호출 방지
"""
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


def _get_glossary():
    """raw 사전 rows를 1회 로드. 언어별 컬럼 선택은 find_glossary_hits에서 처리."""
    global _glossary_rows
    if _glossary_rows is None:
        if _sejong is None:
            _glossary_rows = []
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


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalize_glossary_key(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


# ── Review Required Guard ─────────────────────────────────────────────────────
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
    "선택 사항",
)

# item_zone 오염 방어 — 절 경계 이후만 item으로 인정
# "작성하여", "서명 후", "표시하여"는 오탐 가능성으로 제외
SAFE_CLAUSE_BOUNDARIES: tuple[str, ...] = (
    ",",
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
    return "info"


def _get_item_zone(text: str, stype: str) -> str:
    """동사 트리거 이전 텍스트 반환. 조사 정리.

    ISSUE-03: 조사 제거 후 1자 이하가 되면 원형 유지.
    Glossary-first: 복합 glossary 항목의 구성 단어(_GLOSSARY_WORD_PARTS)이면
      조사 제거 없이 원형 유지. 예) '생활지도' → 도 제거 안 함.
    """
    for trigger in _SENTENCE_TYPES.get(stype, []):
        idx = text.find(trigger)
        if idx == -1:
            continue
        before = text[:idx]
        # safe boundary: 절 경계 이후만 item zone으로 인정 (item_zone 오염 방어)
        last_pos = -1
        for boundary in SAFE_CLAUSE_BOUNDARIES:
            pos = before.rfind(boundary)
            if pos != -1:
                last_pos = max(last_pos, pos + len(boundary))
        zone = (before[last_pos:] if last_pos != -1 else before).strip()
        tokens = zone.split()
        cleaned = []
        for t in tokens:
            # Glossary-first: 복합 용어 구성 단어는 조사 제거 금지
            if t in _GLOSSARY_WORD_PARTS:
                cleaned.append(t)
                continue
            s = _KO_PARTICLES.sub("", t).strip()
            if len(s) >= 2:
                cleaned.append(s)
            elif len(t) >= 2:
                cleaned.append(t)
            # else: 단독 1자 조사 토큰 → 버림
        return " ".join(cleaned)
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
) -> str | None:
    if stype == "info" or not items:
        return None
    lang_templates = _LANG_TEMPLATES.get(lang, {})
    tpl = lang_templates.get(stype)
    if tpl is None:
        return None
    sentence = tpl.format(items=_join_items([tr for _, tr in items], lang))
    if recipient and stype == "submit":
        suffix_tpl = _LANG_RECIPIENT_SUFFIX.get(lang, "")
        if suffix_tpl:
            # 언어별 문장 종결자 제거 후 수신인 접미 붙이기
            sentence = sentence.rstrip(".。") + suffix_tpl.format(recipient=recipient)
            if lang not in ("zh", "ja", "th", "mn"):
                sentence += "."
    if audience:
        prefix_tpl = _LANG_AUDIENCE_PREFIX.get(lang, "")
        if prefix_tpl:
            sentence = prefix_tpl.format(audience=audience) + sentence
    return sentence


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


def _find_glossary_hits_safe(text: str, glossary: list, target_lang: str) -> list[dict]:
    """Find glossary hits with whitespace normalization and 1-char term guard."""
    lang_key = target_lang.split("_")[0] if "_" in target_lang else target_lang
    preferred_col = f"preferred_{lang_key}"
    text_norm = _normalize_glossary_key(text)
    hits: list[dict] = []
    seen: set[str] = set()
    for row in glossary:
        korean = row.get("korean", "").strip()
        preferred = row.get(preferred_col, "").strip()
        if not korean or not preferred or len(korean) <= 1:
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

    masked = _URL.sub(stash_match, text)
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
        slot_values: list[tuple[str, str]] = []
        slot_values.extend((d["ko"], format_date(d, target_lang)) for d in extract_dates(masked))
        slot_values.extend((t["ko"], format_time(t, target_lang)) for t in extract_times(masked))
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
        return placeholders[idx] if idx < len(placeholders) else ""

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
        if stype != "info":
            glossary = _get_glossary()
            _build_role_sets(glossary)
            item_zone = _get_item_zone(text, stype)
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
                result = _build_from_template(stype, items, lang_key, audience, recipient)
                if result:
                    return _restore_protected_entities(result, placeholders)

    # 3) NLLB fallback — info 유형, 템플릿 미지원 언어, glossary 항목 미감지
    glossary = _get_glossary()
    hits = _find_glossary_hits_safe(masked, glossary, target_lang)
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
            if stype != "info":
                item_zone = _get_item_zone(cleaned, stype)
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
                    template_result = _build_from_template(stype, items, lang_key, audience, recipient)
                    if template_result:
                        results[i] = _restore_protected_entities(template_result, placeholders)
                        continue

        # NLLB 행 — glossary 용어를 __SLOT__ 으로 보호 후 batch 입력에 추가
        hits = _find_glossary_hits_safe(masked, glossary, target_lang)
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

