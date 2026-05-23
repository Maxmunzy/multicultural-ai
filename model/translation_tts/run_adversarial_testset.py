"""Adversarial 60문장 테스트.

성공 기준: 위험 문장이 자동 확정 번역되지 않고 review_required로 빠지는가?
NLLB를 호출하지 않고 가드 로직(detect_* + item_zone)만 검증.

실행:
    python model/translation_tts/run_adversarial_testset.py
"""
from __future__ import annotations

import csv as _csv
import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

# translator.py가 script dir에서 run_mvp_pipeline/gemini_helper를 잘못 찾지 않도록
# script dir을 sys.path에서 제거한 뒤 backend를 삽입
if str(HERE) in sys.path:
    sys.path.remove(str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

from app.services.translator import (  # noqa: E402
    NON_PARENT_TARGET_PATTERNS,
    RISKY_CONTEXT_PATTERNS,
    _build_role_sets,
    _classify_sentence,
    _get_item_zone,
    detect_non_parent_target,
    detect_risky_context,
)

_DOCKER_GLOSSARY = Path("/app/external_model/translation_tts/term_glossary.csv")
_LOCAL_GLOSSARY  = Path(__file__).parent / "term_glossary.csv"
_TESTSET         = Path(__file__).parent / "adversarial_testset_v1.jsonl"


def _load_glossary() -> list:
    path = _DOCKER_GLOSSARY if _DOCKER_GLOSSARY.exists() else _LOCAL_GLOSSARY
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(_csv.DictReader(f))


def _actual_review(text: str) -> tuple[bool, str | None]:
    if detect_non_parent_target(text):
        return True, "NON_PARENT_TARGET"
    risky = detect_risky_context(text)
    if risky:
        return True, "RISKY_CONTEXT"
    return False, None


def _check_safe_boundary(text: str, sb: dict) -> tuple[bool, str]:
    stype = _classify_sentence(text)
    if stype == "info":
        return False, f"classify=info (expected stype for '{sb}')"
    zone = _get_item_zone(text, stype)
    must_have = sb.get("must_contain", [])
    must_not  = sb.get("must_not_contain", [])
    fails = []
    for kw in must_have:
        if kw not in zone:
            fails.append(f"'{kw}' must be in zone but zone='{zone}'")
    for kw in must_not:
        if kw in zone:
            fails.append(f"'{kw}' must NOT be in zone but zone='{zone}'")
    if fails:
        return False, "; ".join(fails)
    return True, f"zone='{zone}'"


def run() -> None:
    glossary = _load_glossary()
    _build_role_sets(glossary)

    cases = []
    with open(_TESTSET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    total = len(cases)
    ok_review = 0       # review_required 가드 정확히 작동
    ok_normal = 0       # review_required=False 정확히
    fail = 0
    known_limit = 0
    sb_pass = 0
    sb_fail = 0

    print("=" * 72)
    print("Adversarial Testset — Review Guard & Safe Boundary")
    print(f"케이스: {total}개")
    print("=" * 72)

    failures = []
    for c in cases:
        cid   = c["id"]
        text  = c["text"]
        exp_r = c["expect_review_required"]
        exp_rn = c.get("expect_review_reason")
        sb    = c.get("safe_boundary")
        kl    = c.get("known_limit", False)
        notes = c.get("notes", "")

        if kl:
            known_limit += 1

        # ── 가드 검사 ────────────────────────────────────────────────────
        act_r, act_rn = _actual_review(text)
        guard_ok = (act_r == exp_r) and (exp_rn is None or act_rn == exp_rn)

        if guard_ok:
            if act_r:
                ok_review += 1
            else:
                ok_normal += 1
        else:
            if not kl:
                fail += 1
                failures.append(
                    f"  {cid}: got review={act_r}/{act_rn}, expected {exp_r}/{exp_rn} | {notes}"
                )

        # ── safe boundary 검사 ───────────────────────────────────────────
        if sb:
            sb_ok, sb_msg = _check_safe_boundary(text, sb)
            if sb_ok:
                sb_pass += 1
                print(f"  [SB-PASS] {cid}: {sb_msg}")
            else:
                sb_fail += 1
                print(f"  [SB-FAIL] {cid}: {sb_msg}")

    print()
    print("=" * 72)
    print("결과 요약")
    print("=" * 72)
    print(f"  자동 처리 가능 (review 불필요, 정확):   {ok_normal}/{total}")
    print(f"  review_required 처리 (가드 정확):       {ok_review}/{total}")
    print(f"  실패 (가드 오작동):                     {fail}/{total}")
    print(f"  known_limit (문서화된 한계):             {known_limit}/{total}")
    if sb_pass + sb_fail > 0:
        print(f"  safe boundary 검사 통과:              {sb_pass}/{sb_pass+sb_fail}")

    if failures:
        print()
        print("── 실패 상세 ──")
        for f_msg in failures:
            print(f_msg)

    print()
    success = ok_review + ok_normal
    print(f"총 가드 검사 통과: {success}/{total}")
    review_total = sum(1 for c in cases if c["expect_review_required"] and not c.get("known_limit"))
    if review_total:
        print(f"review_required 정확도: {ok_review}/{review_total}")


if __name__ == "__main__":
    run()
