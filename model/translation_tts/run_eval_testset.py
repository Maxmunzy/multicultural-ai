"""SchoolBridge eval testset runner.

사용법:
    python run_eval_testset.py
    python run_eval_testset.py --category submit
    python run_eval_testset.py --difficulty hard adversarial
    python run_eval_testset.py --shuffle

출력 메트릭:
    template_hit_rate      : should_match_template=true 중 실제 매칭된 비율
    template_fp_rate       : should_match_template=false 중 잘못 매칭된 비율 (낮을수록 좋음)
    item_capture_rate      : expected_item_keywords 중 하나라도 item_zone에 등장한 비율
    place_capture_rate     : should_extract_place=true 중 expected_place가 슬롯된 비율
    place_fp_rate          : should_extract_place=false 중 잘못 슬롯된 비율
"""
from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import csv

HERE = Path(__file__).resolve().parent
TESTSET_PATH = HERE / "eval_testset_v1.jsonl"
GLOSSARY_PATH = HERE / "term_glossary.csv"

# ── 테스트용 경량 구현 (실제 translator.py 없이도 동작) ──────────────────────────
# translator.py를 import할 수 없을 때 fallback으로 사용
_SENTENCE_TYPES: dict[str, list[str]] = {
    "prepare": ["준비해 주세요", "준비해주세요", "준비하세요", "준비 바랍니다"],
    "bring":   ["가져오세요", "챙겨 주세요", "챙겨주세요", "지참해 주세요", "지참하세요", "지참 바랍니다"],
    "submit":  ["제출해 주세요", "제출해주세요", "제출하세요", "내 주세요", "내주세요",
                "보내 주세요", "보내주세요", "제출 바랍니다", "제출바랍니다",
                "제출 부탁드립니다", "제출해 주시기"],
    "attend":  ["참석해 주세요", "참석해주세요", "참석하세요", "참여해 주세요", "참여해주세요", "참여하세요"],
    "pay":     ["납부해 주세요", "납부해주세요", "납부하세요", "입금해 주세요", "입금해주세요", "입금하세요"],
    "check":   ["확인해 주세요", "확인해주세요", "확인하세요", "확인 바랍니다", "확인해 주시기 바랍니다"],
    "fill":    ["작성해 주세요", "작성해주세요", "작성하세요", "작성 바랍니다", "기재해 주세요", "기재해주세요"],
    "apply":   ["신청해 주세요", "신청해주세요", "신청하세요", "신청 바랍니다", "접수해 주세요", "접수해주세요"],
}

_SUFFIX = (
    "(?:박물관|미술관|과학관|천문대|체험관|기념관|생태관|역사관"
    "|동물원|식물원|수목원|전시관|문화관|문화원|문화회관|기념회관"
    "|공연장|체육관|빙상장|수영장|야영장|캠핑장|공원|정원|회관|센터)"
)
_KO = "[가-힣a-zA-Z]"
_PROPER_PLACE = re.compile(
    "(?:국립|시립|도립|구립|군립|사립|공립)[가-힣]{1,12}" + _SUFFIX
    + "|" + _KO + "{1,12}(?:\\s" + _KO + "{1,8})?\\s?" + _SUFFIX
)
_PLACE_NON_PREFIX = frozenset([
    "금일", "오늘", "내일", "모레", "이번", "다음", "당일", "매일", "매주", "매월",
    "현재", "현장", "해당", "관련", "각종", "여러", "일부", "방문", "견학",
])
_JOSA_ENDING = re.compile(r"[은는이가을를도]$")
_KO_PARTICLES = re.compile(r"[을를이가은는도의에게로부터과와]$|까지$|으로$")

# 복합 glossary 항목의 구성 단어 — glossary 로드 후 populate
_GLOSSARY_WORD_PARTS: frozenset[str] = frozenset()


def _load_glossary_word_parts() -> frozenset[str]:
    if not GLOSSARY_PATH.exists():
        return frozenset()
    parts: set[str] = set()
    with open(GLOSSARY_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ko = row.get("korean", "").strip()
            if ko and len(ko.split()) > 1:
                for w in ko.split():
                    if len(w) >= 2:
                        parts.add(w)
    return frozenset(parts)


def classify_sentence(text: str) -> str | None:
    for stype, keywords in _SENTENCE_TYPES.items():
        for kw in keywords:
            if kw in text:
                return stype
    return None


def extract_places(text: str) -> list[str]:
    results = []

    def sub(m: re.Match) -> str:
        t = m.group(0)
        first = t.split()[0]
        if first in _PLACE_NON_PREFIX:
            return t
        if _JOSA_ENDING.search(first):
            rest = t[len(first):].lstrip()
            results.append(rest)
            return t
        results.append(t)
        return f"__SLOT__"

    _PROPER_PLACE.sub(sub, text)
    return results


def get_item_zone(text: str, stype: str) -> str:
    for trigger in _SENTENCE_TYPES.get(stype, []):
        idx = text.find(trigger)
        if idx == -1:
            continue
        zone = text[:idx].strip()
        tokens = zone.split()
        cleaned = []
        for t in tokens:
            if t in _GLOSSARY_WORD_PARTS:
                cleaned.append(t)
                continue
            s = _KO_PARTICLES.sub("", t).strip()
            cleaned.append(s if len(s) >= 2 else (t if len(t) >= 2 else ""))
        return " ".join(x for x in cleaned if x)
    return ""


# ── 테스트 실행 ────────────────────────────────────────────────────────────────

def run(cases: list[dict], verbose: bool = True) -> dict:
    results = {
        "template_tp": 0, "template_fn": 0,
        "template_fp": 0, "template_tn": 0,
        "item_hit": 0,    "item_miss": 0,
        "place_tp": 0,    "place_fn": 0,
        "place_fp": 0,    "place_tn": 0,
        "failures": [],
    }

    for c in cases:
        cid = c["id"]
        text = c["text"]
        should_tmpl = c["should_match_template"]
        should_place = c["should_extract_place"]
        exp_action = c["expected_action"]
        exp_keywords = c["expected_item_keywords"]
        exp_place = c.get("expected_place")
        is_known_limit = "[KNOWN" in c.get("notes", "")

        actual_action = classify_sentence(text)
        actual_places = extract_places(text)

        # ── template matching ──
        tmpl_ok = True
        if should_tmpl:
            if actual_action == exp_action:
                results["template_tp"] += 1
            else:
                results["template_fn"] += 1
                tmpl_ok = False
        else:
            if actual_action is None:
                results["template_tn"] += 1
            else:
                results["template_fp"] += 1
                tmpl_ok = False

        # ── item keyword capture (template match 된 경우만) ──
        item_ok = True
        if should_tmpl and exp_action and exp_keywords:
            zone = get_item_zone(text, exp_action)
            zone_norm = re.sub(r"\s+", "", zone)
            hit = any(re.sub(r"\s+", "", kw) in zone_norm for kw in exp_keywords)
            if hit:
                results["item_hit"] += 1
            else:
                results["item_miss"] += 1
                item_ok = False

        # ── place extraction ──
        place_ok = True
        if should_place and exp_place:
            if exp_place in actual_places:
                results["place_tp"] += 1
            else:
                results["place_fn"] += 1
                place_ok = False
        else:
            if actual_places:
                results["place_fp"] += 1
                place_ok = False
            else:
                results["place_tn"] += 1

        overall_pass = tmpl_ok and item_ok and place_ok
        if not overall_pass and verbose:
            tag = "[KNOWN-LIMIT]" if is_known_limit else "[FAIL]"
            detail_parts = []
            if not tmpl_ok:
                detail_parts.append(f"tmpl: 기대={exp_action} 실제={actual_action}")
            if not item_ok:
                detail_parts.append(f"item: 기대키워드={exp_keywords} zone={get_item_zone(text, exp_action or '')!r}")
            if not place_ok:
                if should_place:
                    detail_parts.append(f"place: 기대={exp_place} 추출={actual_places}")
                else:
                    detail_parts.append(f"place FP: 추출되면 안 됨, 추출={actual_places}")
            print(f"  {tag} {cid}: {text[:50]}")
            for d in detail_parts:
                print(f"        └ {d}")
            results["failures"].append(cid)

    return results


def print_summary(results: dict, total: int) -> None:
    tp = results["template_tp"]
    fn = results["template_fn"]
    fp = results["template_fp"]
    tn = results["template_tn"]
    tmpl_pos = tp + fn
    tmpl_neg = fp + tn
    ih = results["item_hit"]
    im = results["item_miss"]
    ptp = results["place_tp"]
    pfn = results["place_fn"]
    pfp = results["place_fp"]
    ptn = results["place_tn"]

    print("\n" + "=" * 60)
    print("메트릭 요약")
    print("=" * 60)
    if tmpl_pos:
        print(f"  template_hit_rate   : {tp}/{tmpl_pos} = {tp/tmpl_pos:.0%}  (should_match=true 중 정확 매칭)")
    if tmpl_neg:
        print(f"  template_fp_rate    : {fp}/{tmpl_neg} = {fp/tmpl_neg:.0%}  (should_match=false 중 오매칭, 낮을수록 좋음)")
    item_total = ih + im
    if item_total:
        print(f"  item_capture_rate   : {ih}/{item_total} = {ih/item_total:.0%}  (키워드 1개 이상 item_zone에 포함)")
    place_pos = ptp + pfn
    place_neg = pfp + ptn
    if place_pos:
        print(f"  place_capture_rate  : {ptp}/{place_pos} = {ptp/place_pos:.0%}  (should_extract=true 중 정확 추출)")
    if place_neg:
        print(f"  place_fp_rate       : {pfp}/{place_neg} = {pfp/place_neg:.0%}  (should_extract=false 중 오추출, 낮을수록 좋음)")
    print(f"\n  실패 케이스: {len(results['failures'])}개 / 전체 {total}개")
    if results["failures"]:
        print(f"  실패 ID: {', '.join(results['failures'])}")


def main() -> None:
    global _GLOSSARY_WORD_PARTS
    _GLOSSARY_WORD_PARTS = _load_glossary_word_parts()

    parser = argparse.ArgumentParser()
    parser.add_argument("--category", nargs="+", help="카테고리 필터 (submit prepare bring pay attend schedule place apply fill check negative)")
    parser.add_argument("--difficulty", nargs="+", help="난이도 필터 (easy medium hard adversarial)")
    parser.add_argument("--shuffle", action="store_true", help="케이스 셔플")
    parser.add_argument("--quiet", action="store_true", help="실패 상세 출력 없음")
    args = parser.parse_args()

    cases: list[dict] = []
    with open(TESTSET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.difficulty:
        cases = [c for c in cases if c["difficulty"] in args.difficulty]
    if args.shuffle:
        random.shuffle(cases)

    print(f"테스트 케이스: {len(cases)}개 (전체 {sum(1 for _ in open(TESTSET_PATH, encoding='utf-8'))}개)")
    if args.category:
        print(f"  카테고리 필터: {args.category}")
    if args.difficulty:
        print(f"  난이도 필터: {args.difficulty}")
    if args.shuffle:
        print("  순서 셔플됨")
    print()

    results = run(cases, verbose=not args.quiet)
    print_summary(results, len(cases))


if __name__ == "__main__":
    main()
