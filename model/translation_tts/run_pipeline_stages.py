#!/usr/bin/env python3
"""단계별 번역 + 파이프라인 내부 진단 (multilingual_v1, vi + en)

캡처 항목:
  masked       - 슬롯 마스킹 후 NLLB에 들어가는 텍스트
  stype        - _classify_sentence 결과 (prepare/submit/pay/.../info)
  path         - T(template) / F(NLLB fallback)
  raw_nllb     - 슬롯 보호 없이 원문 직접 NLLB
  slot_masked  - 슬롯 보호 후 NLLB (용어집 없음)
  glossary     - 슬롯 보호 + 용어집 injection 후 NLLB
  schoolbridge - 풀 파이프라인 (eval_chunks에 이미 있는 값)

실행:
  docker exec multicultural-ai-backend-1 \
    python /app/external_model/translation_tts/run_pipeline_stages.py
"""
import json, sys, os, re

sys.path.insert(0, "/app")

from app.services.translator import (
    _translate,
    _get_translator,
    _mask_protected_entities,
    _restore_protected_entities,
    _clean_for_translation,
    _get_glossary,
    _find_glossary_hits_safe,
    _classify_sentence,
    _build_role_sets,
    _extract_payment_method,
    _extract_time_context_token,
    _extract_time_context,
    _get_item_zone,
    _extract_template_items,
    _extract_audience,
    _extract_recipient,
    _extract_deadline_token,
    _extract_start_date_token,
    _extract_amount_token,
    _build_from_template,
    _post_process,
    _restore_protected_entities,
    LANG_TO_NLLB,
    _LANG_TEMPLATES,
    translate_short_sentence,
)

EVAL_DIR = "/app/external_model/translation_tts/eval_chunks"
OUTPUT   = "/app/external_model/translation_tts/eval_chunks/pipeline_stages_vi_en.jsonl"
LANGS    = ["vi", "en"]
MAX_CHARS = 100


def diagnose_pipeline(ko: str, lang: str) -> dict:
    """파이프라인 내부 분기를 추적하며 각 단계 출력을 반환."""
    text = _clean_for_translation(ko)[:MAX_CHARS]
    lang_key = lang.split("_")[0] if "_" in lang else lang
    target_nllb = LANG_TO_NLLB.get(lang, "vie_Latn")

    # ── 슬롯 마스킹 ──────────────────────────────────────────────
    masked, placeholders = _mask_protected_entities(text, lang)

    # ── 문장 유형 분류 ────────────────────────────────────────────
    stype = _classify_sentence(text) if lang_key in _LANG_TEMPLATES else "n/a"

    # ── Stage 1: raw NLLB (마스킹 없음) ──────────────────────────
    try:
        raw = _translate(text, target_nllb)
    except Exception as e:
        raw = f"ERROR:{e}"

    # ── Stage 2: slot-masked NLLB ────────────────────────────────
    try:
        slot_tr = _translate(masked, target_nllb)
        slot_out = _restore_protected_entities(slot_tr, list(placeholders))
    except Exception as e:
        slot_out = f"ERROR:{e}"

    # ── Stage 3: glossary injection NLLB ────────────────────────
    glossary = _get_glossary()
    _build_role_sets(glossary)
    hits = _find_glossary_hits_safe(masked, glossary, lang, min_len=3)
    injected = masked
    ph_gloss = list(placeholders)
    for hit in sorted(hits, key=lambda h: len(h["korean"]), reverse=True):
        korean = hit["korean"]
        preferred = hit["preferred_term"]
        while korean in injected:
            idx = len(ph_gloss)
            ph_gloss.append(preferred)
            injected = injected.replace(korean, f"__SLOT{idx}__", 1)
    try:
        gloss_tr = _translate(injected, target_nllb)
        gloss_tr = _post_process(lang, text, gloss_tr)
        gloss_out = _restore_protected_entities(gloss_tr, ph_gloss)
    except Exception as e:
        gloss_out = f"ERROR:{e}"

    # ── Template path 판정 ────────────────────────────────────────
    # 실제 파이프라인과 동일 로직으로 T/F 결정
    path = "F"  # default: NLLB fallback
    if lang_key in _LANG_TEMPLATES and stype not in ("info", "n/a"):
        _m2 = masked  # 판정 전용 복사
        _ph2 = list(placeholders)
        _method = None
        if stype == "pay":
            _method, _m2 = _extract_payment_method(_m2, lang_key)
        _tc, _m2 = _extract_time_context_token(_m2, _ph2)
        if _tc is None:
            _tc, _m2 = _extract_time_context(_m2, lang_key)
        item_zone = _get_item_zone(_m2, stype)
        items = _extract_template_items(item_zone, glossary, lang_key)
        if not items:
            # noun fallback via NLLB (pipeline does this too)
            pass
        if items:
            deadline = _extract_deadline_token(_m2)
            start_date = _extract_start_date_token(_m2) if stype == "apply" else None
            amount = _extract_amount_token(_m2) if stype == "pay" else None
            result = _build_from_template(
                stype, items, lang_key,
                _extract_audience(text, lang_key),
                _extract_recipient(text, lang_key),
                deadline=deadline, amount=amount,
                method=_method, time_context=_tc,
                start_date=start_date,
            )
            if result:
                path = "T"

    return {
        "masked": masked,
        "stype": stype,
        "path": path,
        "raw_nllb": raw,
        "slot_masked_nllb": slot_out,
        "glossary_nllb": gloss_out,
    }


def main():
    print("[INFO] NLLB 모델 로딩 중...")
    _get_translator()
    print("[INFO] 모델 로딩 완료\n")

    rows = []

    for lang in LANGS:
        chunk_path = os.path.join(EVAL_DIR, f"{lang}_multilingual_v1.json")
        print(f"\n{'='*60}")
        print(f"  언어: {lang.upper()}  |  파일: {chunk_path}")
        print(f"{'='*60}")

        with open(chunk_path, encoding="utf-8") as f:
            sentences = json.load(f)

        for item in sentences:
            sid = item["id"]
            ko  = item["text_ko"]
            sb  = item.get("schoolbridge_output", "")

            print(f"\n[{sid}] {ko}")

            diag = diagnose_pipeline(ko, lang)

            print(f"  masked      : {diag['masked']}")
            print(f"  stype       : {diag['stype']}  |  path: {diag['path']}")
            print(f"  raw_nllb    : {diag['raw_nllb']}")
            print(f"  slot_masked : {diag['slot_masked_nllb']}")
            print(f"  glossary    : {diag['glossary_nllb']}")
            print(f"  schoolbridge: {sb}")

            rows.append({
                "id":              sid,
                "lang":            lang,
                "text_ko":         ko,
                "masked":          diag["masked"],
                "stype":           diag["stype"],
                "path":            diag["path"],
                "raw_nllb":        diag["raw_nllb"],
                "slot_masked_nllb": diag["slot_masked_nllb"],
                "glossary_nllb":   diag["glossary_nllb"],
                "schoolbridge":    sb,
            })

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n[DONE] {len(rows)}개 저장 → {OUTPUT}")


if __name__ == "__main__":
    main()
