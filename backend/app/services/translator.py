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
from functools import lru_cache
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

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


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalize_glossary_key(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


# ── Template-based translation (vi) ───────────────────────────────────────────
# 준비물/제출물 문장은 NLLB 대신 구조 분석 + glossary로 직접 번역.
# 용어 보존율: NLLB 직접 입력 6% → 템플릿 100% (2026-05-07 실험)

_SENTENCE_TYPES: dict[str, list[str]] = {
    "prepare": ["준비해 주세요", "준비해주세요", "준비하세요", "준비 바랍니다"],
    "bring":   ["가져오세요", "챙겨 주세요", "챙겨주세요", "지참해 주세요", "지참하세요", "지참 바랍니다"],
    "submit":  ["제출해 주세요", "제출해주세요", "제출하세요", "내 주세요", "내주세요", "보내 주세요", "보내주세요"],
    "attend":  ["참석해 주세요", "참석해주세요", "참석하세요", "참여해 주세요", "참여해주세요", "참여하세요"],
    "pay":     ["납부해 주세요", "납부해주세요", "납부하세요", "입금해 주세요", "입금해주세요", "입금하세요"],
}

_VI_TEMPLATES: dict[str, str] = {
    "prepare": "Vui lòng chuẩn bị {items}.",
    "bring":   "Vui lòng mang theo {items}.",
    "submit":  "Vui lòng nộp {items}.",
    "attend":  "Vui lòng tham gia {items}.",
    "pay":     "Vui lòng thanh toán {items}.",
}

# supply item이 아닌 청중/제출처는 template item 목록에서 분리해 구조 정보로 활용.
_AUDIENCE_KO: dict[str, str] = {
    "전교생": "toàn thể học sinh",
    "재학생": "học sinh",
}
_RECIPIENT_KO: dict[str, str] = {
    "담임선생님": "giáo viên chủ nhiệm",
    "담임 선생님": "giáo viên chủ nhiệm",
    "담임교사": "giáo viên chủ nhiệm",
}
_TEMPLATE_EXCLUDE_KO: frozenset[str] = frozenset(_AUDIENCE_KO) | frozenset(_RECIPIENT_KO)


def _classify_sentence(text: str) -> str:
    for stype, keywords in _SENTENCE_TYPES.items():
        for kw in keywords:
            if kw in text:
                return stype
    return "info"


def _extract_template_items(text: str, glossary: list, target_lang: str) -> list[tuple[str, str]]:
    """공급 용어(청중/제출처 제외)를 텍스트에서 추출, 출현 순서대로 반환."""
    preferred_col = f"preferred_{target_lang}"
    text_norm = _normalize_glossary_key(text)
    spans: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for row in sorted(glossary, key=lambda r: -len(r.get("korean", ""))):
        korean = row.get("korean", "").strip()
        preferred = row.get(preferred_col, "").strip()
        if not korean or not preferred or len(korean) <= 1 or korean in _TEMPLATE_EXCLUDE_KO:
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


def _extract_audience_vi(text: str) -> str | None:
    for ko, vi in _AUDIENCE_KO.items():
        if ko in text:
            return vi
    return None


def _extract_recipient_vi(text: str) -> str | None:
    for ko, vi in _RECIPIENT_KO.items():
        if ko in text:
            return vi
    return None


def _join_vi_items(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " và " + items[-1]


def _build_from_template_vi(
    stype: str,
    items: list[tuple[str, str]],
    audience: str | None,
    recipient: str | None,
) -> str | None:
    if stype == "info" or not items:
        return None
    tpl = _VI_TEMPLATES.get(stype)
    if tpl is None:
        return None
    sentence = tpl.format(items=_join_vi_items([vi for _, vi in items]))
    if recipient and stype == "submit":
        sentence = sentence[:-1] + f" cho {recipient}."
    if audience:
        sentence = f"Dành cho {audience}: {sentence}"
    return sentence


def _find_glossary_hits_safe(text: str, glossary: list, target_lang: str) -> list[dict]:
    """Find glossary hits with whitespace normalization and 1-char term guard."""
    preferred_col = f"preferred_{target_lang}"
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
_PROTECT_TOKEN = re.compile(r"__SLOT(\d+)__")


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

    if target_lang and target_lang != "ko_easy":
        slot_values: list[tuple[str, str]] = []
        slot_values.extend((d["ko"], format_date(d, target_lang)) for d in extract_dates(masked))
        slot_values.extend((t["ko"], format_time(t, target_lang)) for t in extract_times(masked))
        slot_values.extend((a["ko"], format_amount(a, target_lang)) for a in extract_amounts(masked))

        for source, translated in sorted(slot_values, key=lambda item: len(item[0]), reverse=True):
            if source and source in masked:
                masked = masked.replace(source, stash_value(translated or source))
    return masked, placeholders


def _restore_protected_entities(text: str, placeholders: list[str]) -> str:
    if not placeholders:
        return text

    def restore(match: re.Match) -> str:
        idx = int(match.group(1))
        return placeholders[idx] if idx < len(placeholders) else match.group(0)

    return _PROTECT_TOKEN.sub(restore, text)


def _is_url_or_phone(text: str) -> bool:
    """슬롯 단위 번역 시 URL/전화면 NLLB 안 거치고 ko 그대로 반환하기 위한 가드."""
    s = text.strip()
    return bool(_URL.fullmatch(s) or _PHONE.fullmatch(s))


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

    glossary = _get_glossary()
    term_norm = re.sub(r"\s+", "", text.strip())
    for row in glossary:
        if re.sub(r"\s+", "", row.get("korean", "")) == term_norm:
            translated = row.get(f"preferred_{target_lang}", "").strip()
            if translated:
                return translated
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

    # 2) Template-based (vi only): 문장 유형 분류 → glossary 직접 매핑 → 템플릿 조립
    if target_lang == "vi":
        stype = _classify_sentence(text)
        if stype != "info":
            glossary = _get_glossary()
            items = _extract_template_items(text, glossary, target_lang)
            if items:
                audience = _extract_audience_vi(text)
                recipient = _extract_recipient_vi(text)
                result = _build_from_template_vi(stype, items, audience, recipient)
                if result:
                    return _restore_protected_entities(result, placeholders)

    # 3) NLLB fallback — info 유형, 비vi 언어, glossary 항목 미감지
    glossary = _get_glossary()
    hits = _find_glossary_hits_safe(masked, glossary, target_lang)
    injected = masked
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

    return _restore_protected_entities(translated, placeholders)


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

