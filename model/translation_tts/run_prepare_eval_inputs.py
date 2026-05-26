"""번역 품질 평가 입력 데이터 생성 — 4단계 번역 비교

Stage 1  raw_nllb          순수 NLLB (보정 없음)
Stage 2  slot_masked_nllb  날짜·금액·URL 슬롯 마스킹 후 NLLB + 복원
Stage 3  glossary_nllb     슬롯 마스킹 + 용어사전 주입 후 NLLB + 복원
Stage 4  schoolbridge      현재 파이프라인 (백엔드 연결 시 자동, 없으면 null)

산출물:
  eval_inputs_8lang.jsonl          100문장 × 8언어 × 4단계 = 800 레코드
  eval_chunks/{lang}_chunk_NN.json 10문장 단위 수동 평가 묶음

체크포인트 자동 저장 → 중단 후 재실행 시 이어서 진행.

사용법:
    python model/translation_tts/run_prepare_eval_inputs.py
    python model/translation_tts/run_prepare_eval_inputs.py --lang vi en
    python model/translation_tts/run_prepare_eval_inputs.py --stages 1 2
    python model/translation_tts/run_prepare_eval_inputs.py --chunk-size 15
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

TESTSET_FILE   = HERE / "translation_quality_eval_v1_100.jsonl"
GLOSSARY_FILE  = HERE / "term_glossary.csv"
OUT_FILE       = HERE / "eval_inputs_8lang.jsonl"
CHECKPOINT     = HERE / "eval_inputs_checkpoint.jsonl"
CHUNK_DIR      = HERE / "eval_chunks"

TRANSLATION_MODEL = "facebook/nllb-200-distilled-600M"
SOURCE_LANG = "kor_Hang"

# ── backend 임포트 (SchoolBridge 파이프라인용) ──────────────────────────────────
_guard_loaded, _translate_sb = False, None
_detect_non_parent, _detect_risky = None, None

try:
    _saved = list(sys.path)
    if str(HERE) in sys.path:
        sys.path.remove(str(HERE))
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.translator import (  # noqa: E402
        detect_non_parent_target as _dpt,
        detect_risky_context as _drc,
    )
    _detect_non_parent, _detect_risky = _dpt, _drc
    _guard_loaded = True
    try:
        from app.services.translator import translate_short_sentence as _tss  # noqa: E402
        _translate_sb = _tss
    except Exception:
        pass
except Exception as e:
    print(f"[경고] backend 임포트 실패 ({e}) — review_required 생략\n")

sys.path.insert(0, str(HERE))
from languages import LANGUAGES  # noqa: E402

ALL_LANGS  = [k for k in LANGUAGES if k != "easy_ko"]
LANG_LABEL = {k: v["label"] for k, v in LANGUAGES.items() if k != "easy_ko"}


# ── 슬롯 마스킹 ────────────────────────────────────────────────────────────────

_SLOT_PATTERNS = [
    (r'\d[\d,]*원',                          'AMT'),   # 15,000원
    (r'\d{1,2}월\s*\d{1,2}일',              'DATE'),  # 4월 28일
    (r'오[전후]\s*\d{1,2}시(?:\s*\d{1,2}분)?', 'TIME'), # 오전 10시
    (r'\d{2,3}-\d{3,4}-\d{4}',              'PHONE'), # 02-1234-5678
    (r'[a-zA-Z][a-zA-Z0-9-]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?(?:/[^\s]*)?', 'URL'),
]

def mask_slots(text: str) -> tuple[str, dict[str, str]]:
    slot_map: dict[str, str] = {}
    result = text
    n = 0
    for pat, prefix in _SLOT_PATTERNS:
        while True:
            m = re.search(pat, result)
            if not m:
                break
            token = f"KS{prefix}{n:02d}"
            slot_map[token] = m.group()
            result = result[:m.start()] + token + result[m.end():]
            n += 1
    return result, slot_map


def unmask(text: str, slot_map: dict[str, str]) -> str:
    for token, original in slot_map.items():
        text = text.replace(token, original)
    return text


# ── 용어사전 로딩 & 주입 ────────────────────────────────────────────────────────

def load_glossary() -> list[dict]:
    import csv
    if not GLOSSARY_FILE.exists():
        return []
    with GLOSSARY_FILE.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("korean","").strip()]


def mask_glossary_terms(text: str, glossary: list[dict], lang: str,
                        offset: int = 0) -> tuple[str, dict[str, str]]:
    """glossary 용어를 KGTERMnn 토큰으로 치환. slot_map과 동일 구조 반환."""
    gterm_map: dict[str, str] = {}
    result = text
    n = offset
    pref_key = f"preferred_{lang}"
    for row in glossary:
        korean = row.get("korean","").strip()
        preferred = row.get(pref_key,"").strip()
        if not korean or not preferred:
            continue
        if korean in result:
            token = f"KGTERM{n:02d}"
            gterm_map[token] = preferred
            result = result.replace(korean, token, 1)
            n += 1
    return result, gterm_map


# ── NLLB 모델 ─────────────────────────────────────────────────────────────────

def load_model(device: str):
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    print(f"[모델 로딩] {TRANSLATION_MODEL} ({device}) ...", flush=True)
    t0 = time.time()
    tok   = AutoTokenizer.from_pretrained(TRANSLATION_MODEL, src_lang=SOURCE_LANG)
    model = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATION_MODEL).to(device)
    model.eval()
    print(f"[완료] {time.time()-t0:.1f}초\n", flush=True)
    return tok, model


def nllb_translate(text: str, tok, model, device: str, nllb_code: str) -> str:
    import torch
    target_id = tok.convert_tokens_to_ids(nllb_code)
    inputs = tok(text, return_tensors="pt", truncation=True, max_length=384).to(device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            forced_bos_token_id=target_id,
            max_new_tokens=512,
            num_beams=4,
        )
    return tok.decode(out[0], skip_special_tokens=True)


# ── 가드 함수 ─────────────────────────────────────────────────────────────────

def check_review_guard(text: str) -> tuple[bool, str | None]:
    if not _guard_loaded:
        return False, None
    if _detect_non_parent(text):
        return True, "NON_PARENT_TARGET"
    risky = _detect_risky(text)
    return (True, "RISKY_CONTEXT") if risky else (False, None)


def get_schoolbridge_output(text: str, lang: str) -> str | None:
    if _translate_sb is None:
        return None
    try:
        return _translate_sb(text, lang)
    except Exception:
        return None


# ── 4단계 번역 ─────────────────────────────────────────────────────────────────

def translate_all_stages(
    text: str, lang: str, nllb_code: str,
    tok, model, device: str,
    glossary: list[dict],
    enabled_stages: set[int],
) -> dict[str, str | None]:
    stages: dict[str, str | None] = {
        "raw_nllb":         None,
        "slot_masked_nllb": None,
        "glossary_nllb":    None,
        "schoolbridge":     None,
    }

    if 1 in enabled_stages:
        stages["raw_nllb"] = nllb_translate(text, tok, model, device, nllb_code)

    if 2 in enabled_stages:
        masked, slot_map = mask_slots(text)
        translated = nllb_translate(masked, tok, model, device, nllb_code)
        stages["slot_masked_nllb"] = unmask(translated, slot_map)

    if 3 in enabled_stages:
        masked, slot_map = mask_slots(text)
        masked, gterm_map = mask_glossary_terms(masked, glossary, lang, offset=len(slot_map))
        combined_map = {**slot_map, **gterm_map}
        translated = nllb_translate(masked, tok, model, device, nllb_code)
        stages["glossary_nllb"] = unmask(translated, combined_map)

    if 4 in enabled_stages:
        stages["schoolbridge"] = get_schoolbridge_output(text, lang)

    return stages


# ── 체크포인트 ─────────────────────────────────────────────────────────────────

def load_checkpoint() -> dict[str, dict]:
    if not CHECKPOINT.exists():
        return {}
    done: dict[str, dict] = {}
    for line in CHECKPOINT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            done[r["id"]] = r
    return done


def append_checkpoint(record: dict) -> None:
    with CHECKPOINT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── 청크 저장 ─────────────────────────────────────────────────────────────────

def save_chunks(records: list[dict], chunk_size: int) -> None:
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    by_lang: dict[str, list[dict]] = {}
    for r in records:
        by_lang.setdefault(r["target_lang"], []).append(r)

    total = 0
    for lang, rows in sorted(by_lang.items()):
        for ci, start in enumerate(range(0, len(rows), chunk_size), 1):
            chunk = rows[start:start + chunk_size]
            path  = CHUNK_DIR / f"{lang}_chunk_{ci:02d}.json"
            path.write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")
            total += 1
    print(f"[청크] {CHUNK_DIR}/  →  {total}개 파일 (언어당 {chunk_size}문장 단위)")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lang", nargs="+", default=ALL_LANGS, choices=ALL_LANGS)
    p.add_argument("--stages", nargs="+", type=int, default=[1,2,3,4],
                   choices=[1,2,3,4], help="실행할 단계 (기본: 1 2 3 4)")
    p.add_argument("--chunk-size", type=int, default=10)
    p.add_argument("--no-gpu", action="store_true")
    p.add_argument("--reset", action="store_true", help="체크포인트 무시 후 처음부터")
    return p.parse_args()


def main():
    args = parse_args()

    import torch
    device = "cpu" if args.no_gpu or not torch.cuda.is_available() else "cuda"
    enabled_stages: set[int] = set(args.stages)

    # 테스트셋 로딩
    if not TESTSET_FILE.exists():
        print(f"[오류] {TESTSET_FILE} 없음.")
        sys.exit(1)
    cases = [json.loads(l) for l in TESTSET_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"[테스트셋] {len(cases)}문장  언어: {args.lang}  단계: {args.stages}\n")

    # 용어사전
    glossary = load_glossary()
    print(f"[용어사전] {len(glossary)}개 로드\n")

    # 체크포인트
    if args.reset and CHECKPOINT.exists():
        CHECKPOINT.unlink()
    done = load_checkpoint()
    print(f"[체크포인트] 이미 완료: {len(done)}건\n")

    tok, model = load_model(device)

    target_langs = args.lang
    total = len(cases) * len(target_langs)
    records: list[dict] = list(done.values())
    job = len(done)

    for case in cases:
        rr, rr_reason = check_review_guard(case["text_ko"])
        for lang in target_langs:
            record_id = f"{case['id']}_{lang}"
            if record_id in done:
                continue

            job += 1
            nllb_code = LANGUAGES[lang]["nllb_code"]
            print(f"[{job:>4}/{total}] {case['id']} ({case['type']:<12}) → {lang} ...",
                  end=" ", flush=True)

            s_stages = translate_all_stages(
                case["text_ko"], lang, nllb_code,
                tok, model, device, glossary, enabled_stages,
            )
            print("OK", flush=True)

            record = {
                "id":                      record_id,
                "source_id":               case["id"],
                "type":                    case["type"],
                "difficulty":              case.get("difficulty","medium"),
                "text_ko":                 case["text_ko"],
                "target_lang":             lang,
                # ── 4단계 출력 ──────────────────────────────────────
                "raw_nllb_output":         s_stages["raw_nllb"],
                "slot_masked_nllb_output": s_stages["slot_masked_nllb"],
                "glossary_nllb_output":    s_stages["glossary_nllb"],
                "schoolbridge_output":     s_stages["schoolbridge"],
                # ── 메타 ────────────────────────────────────────────
                "review_required":         rr,
                "review_reason":           rr_reason,
                "expected_action":         case.get("expected_action",""),
                "expected_slots":          case.get("expected_slots",[]),
                "expected_terms":          case.get("expected_terms",[]),
                "expected_risk":           case.get("expected_risk",False),
                "should_review_required":  case.get("should_review_required",False),
            }
            records.append(record)
            append_checkpoint(record)

    # 최종 파일 저장
    OUT_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8",
    )
    if CHECKPOINT.exists():
        CHECKPOINT.unlink()
    print(f"\n[저장] {OUT_FILE}  ({len(records)}건)")

    if _translate_sb is None:
        print("[참고] schoolbridge_output = null — 백엔드 연결 시 채워짐")

    save_chunks(records, args.chunk_size)

    # 분포 요약
    print("\n[분포 요약]")
    type_counts: dict[str, int] = {}
    for c in cases:
        type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1
    for t, n in sorted(type_counts.items()):
        print(f"  {t:15} {n}문장")
    nllb_calls = len([s for s in enabled_stages if s in {1,2,3}])
    print(f"\n예상 NLLB 호출 수: {len(records) - len(done)}건 × {nllb_calls}회 = "
          f"{(len(records)-len(done))*nllb_calls}건")


if __name__ == "__main__":
    main()
