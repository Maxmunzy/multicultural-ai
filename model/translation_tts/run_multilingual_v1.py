"""multilingual_v1 평가 입력 생성

multilingual_v1_source.json의 24개 대표 문장을 8개 언어로 번역하여
eval_chunks/{lang}_multilingual_v1.json의 schoolbridge_output을 채운다.

사용법:
    python model/translation_tts/run_multilingual_v1.py
    python model/translation_tts/run_multilingual_v1.py --lang mn th
    python model/translation_tts/run_multilingual_v1.py --lang vi en zh ja th ms mn ru
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

CHUNK_DIR = HERE / "eval_chunks"
SOURCE_FILE = CHUNK_DIR / "multilingual_v1_source.json"

ALL_LANGS = ["vi", "en", "zh", "ja", "th", "ms", "mn", "ru"]

# ── backend 임포트 ─────────────────────────────────────────────────────────────
_saved = list(sys.path)
if str(HERE) in sys.path:
    sys.path.remove(str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

try:
    from app.services.translator import translate_short_sentence_reviewed as _translate_sb
    print("[OK] SchoolBridge translator loaded from backend/")
except ImportError as e:
    print(f"[ERROR] translator import 실패: {e}")
    print("       backend/ 폴더가 ROOT에 있는지 확인 필요")
    sys.exit(1)

sys.path = _saved


def translate_sentence(text_ko: str, lang: str) -> tuple[str | None, bool, str | None]:
    """(schoolbridge_output, review_required, review_reason) 반환"""
    try:
        result = _translate_sb(text_ko, lang)
        # translate_short_sentence_reviewed returns dict with 'translated', 'review_required', 'review_reason'
        if isinstance(result, dict):
            translated = result.get("translated_text") or result.get("translated") or result.get("translation")
            rr = result.get("review_required", False)
            rr_reason = result.get("review_reason")
            return translated, bool(rr), rr_reason
        if isinstance(result, str):
            return result, False, None
        return None, False, None
    except Exception as ex:
        print(f"  [ERR] {lang} | {text_ko[:40]!r} → {ex}")
        return None, False, None


def run(langs: list[str], force_ids: set[str] | None = None) -> None:
    with open(SOURCE_FILE, encoding="utf-8") as f:
        sources = json.load(f)

    for lang in langs:
        chunk_file = CHUNK_DIR / f"{lang}_multilingual_v1.json"
        if not chunk_file.exists():
            print(f"[SKIP] {chunk_file} 없음 — run_multilingual_v1.py 이전에 eval chunk 파일 생성 필요")
            continue

        with open(chunk_file, encoding="utf-8") as f:
            records = json.load(f)

        # source_id → record 인덱스 매핑
        idx_map = {r["source_id"]: i for i, r in enumerate(records)}

        print(f"\n[{lang.upper()}] {len(sources)}개 번역 중...")
        done = 0
        for s in sources:
            src_id = s["source_id"]
            text_ko = s["text_ko"]

            if src_id not in idx_map:
                print(f"  [WARN] source_id {src_id} 없음 in {chunk_file.name}")
                continue

            idx = idx_map[src_id]
            rec = records[idx]

            # --force-ids 지정 시 해당 ID만 재번역, 나머지 skip
            if force_ids is not None:
                if src_id not in force_ids:
                    continue
            elif rec.get("schoolbridge_output") is not None:
                print(f"  [SKIP] {src_id} — already filled")
                continue

            output, rr, rr_reason = translate_sentence(text_ko, lang)
            rec["schoolbridge_output"] = output
            rec["review_required"] = rr
            rec["review_reason"] = rr_reason

            status = "rr=True" if rr else "ok"
            out_preview = (output or "")[:60]
            print(f"  {src_id:12s} [{status}] {out_preview}")
            done += 1
            time.sleep(0.05)

        with open(chunk_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"  → {chunk_file.name} 저장 ({done}개 신규/갱신, 전체 {len(records)}개)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", nargs="+", default=ALL_LANGS,
                        help=f"번역할 언어 (기본: {' '.join(ALL_LANGS)})")
    parser.add_argument("--force-ids", nargs="+", metavar="SOURCE_ID",
                        help="지정한 source_id만 강제 재번역 (예: F-012 F-001 N-002)")
    args = parser.parse_args()

    invalid = [l for l in args.lang if l not in ALL_LANGS]
    if invalid:
        print(f"[ERROR] 지원하지 않는 언어: {invalid}")
        sys.exit(1)

    force_ids = set(args.force_ids) if args.force_ids else None
    if force_ids:
        print(f"[FORCE] 재번역 대상 IDs: {sorted(force_ids)}")

    run(args.lang, force_ids=force_ids)
    print("\n[완료] multilingual_v1 번역 생성 완료")


if __name__ == "__main__":
    main()
