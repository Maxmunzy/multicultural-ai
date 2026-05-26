"""평가자별 번역 품질 점수 취합 및 요약 생성

scores/ 디렉토리의 scores_*.jsonl 파일을 읽어:
- 평가자별 평균 점수
- 평가자 간 점수 편차 (신뢰도 지표)
- raw NLLB vs SchoolBridge 개선폭
- Template / Fallback / Risk 카테고리별 평균
- critical_error_rate
- review_required_rate (eval_inputs.jsonl 기준)

사용법:
    python model/translation_tts/run_collect_scores.py
    python model/translation_tts/run_collect_scores.py --lang vi en
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
SCORES_DIR   = HERE / "scores"
INPUTS_FILE  = HERE / "eval_inputs.jsonl"
OUT_DIR      = HERE / "outputs" / "quality_eval_multi"

SCORE_FIELDS = ["meaning_score", "action_score", "slot_score", "term_score",
                "naturalness_score", "total_score"]
SCORE_MAX    = {"meaning_score": 30, "action_score": 25, "slot_score": 20,
                "term_score": 15, "naturalness_score": 10, "total_score": 100}


# ── 데이터 로딩 ────────────────────────────────────────────────────────────────

def load_inputs(lang_filter: list[str] | None = None) -> dict[str, dict]:
    if not INPUTS_FILE.exists():
        return {}
    inputs = {}
    for line in INPUTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if lang_filter and r["target_lang"] not in lang_filter:
            continue
        inputs[r["id"]] = r
    return inputs


def load_all_scores(lang_filter: list[str] | None = None) -> list[dict]:
    if not SCORES_DIR.exists():
        return []
    records = []
    for path in sorted(SCORES_DIR.glob("scores_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            eval_id = r.get("eval_id", "")
            lang = eval_id.rsplit("_", 1)[-1] if "_" in eval_id else ""
            if lang_filter and lang not in lang_filter:
                continue
            records.append(r)
    return records


# ── 통계 헬퍼 ─────────────────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return (sum((x - m) ** 2 for x in values) / len(values)) ** 0.5


def _fmt(v: float) -> str:
    return f"{v:.1f}"


# ── 집계 ──────────────────────────────────────────────────────────────────────

def aggregate(scores: list[dict], inputs: dict[str, dict]) -> dict:
    """key 구조: {eval_id → {evaluator → {target → row}}}"""

    # eval_id × evaluator × target 인덱스
    idx: dict[str, dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for r in scores:
        idx[r["eval_id"]][r["evaluator"]][r["target"]] = r

    evaluators = sorted({r["evaluator"] for r in scores})
    targets    = sorted({r["target"] for r in scores})
    categories = ["template", "fallback", "risk"]
    lang_filter = sorted({r["eval_id"].rsplit("_", 1)[-1] for r in scores})

    return {
        "idx": idx,
        "evaluators": evaluators,
        "targets": targets,
        "categories": categories,
        "langs": lang_filter,
        "inputs": inputs,
        "raw_scores": scores,
    }


# ── 출력 ──────────────────────────────────────────────────────────────────────

def print_and_save(agg: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = _build_summary(agg)
    text = "\n".join(lines)

    summary_path = OUT_DIR / "summary.md"
    summary_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[저장] {summary_path}")

    # results_summary.md (발표용 간결 버전)
    _write_results_summary(agg)


def _build_summary(agg: dict) -> list[str]:
    idx        = agg["idx"]
    evaluators = agg["evaluators"]
    targets    = agg["targets"]
    categories = agg["categories"]
    langs      = agg["langs"]
    inputs     = agg["inputs"]

    lines = [
        "# 번역 품질 평가 결과 — 멀티-LLM 취합",
        "",
        "> **LLM 기반 내부 평가 결과이며, 원어민 검수 점수가 아님.**",
        "",
        f"평가자: {', '.join(evaluators)}",
        f"평가 대상 언어: {', '.join(langs)}",
        f"번역 버전: {', '.join(targets)}",
        "",
    ]

    # ── 1. 평가자별 전체 평균
    lines += ["## 1. 평가자별 전체 평균 (total_score)", "",
              "| 평가자 | " + " | ".join(t.upper() for t in targets) + " |",
              "|---|" + "---|" * len(targets)]
    for ev in evaluators:
        cells = []
        for tgt in targets:
            vals = [
                r["total_score"]
                for r in agg["raw_scores"]
                if r["evaluator"] == ev and r["target"] == tgt
            ]
            cells.append(_fmt(_mean(vals)) if vals else "—")
        lines.append(f"| {ev} | " + " | ".join(cells) + " |")
    lines.append("")

    # ── 2. 평가자 간 편차 (inter-evaluator variance)
    lines += ["## 2. 평가자 간 점수 편차 (신뢰도 지표)", "",
              "편차가 클수록 해당 문장/언어의 평가가 불일치 → review_required 후보",
              "",
              "| eval_id | target | 평균 | 표준편차 | min | max |",
              "|---|---|---|---|---|---|"]
    # eval_id × target 별로 모든 평가자 점수 수집
    id_target_scores: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in agg["raw_scores"]:
        id_target_scores[(r["eval_id"], r["target"])].append(r["total_score"])
    for (eid, tgt), vals in sorted(id_target_scores.items()):
        if len(vals) < 2:
            continue
        lines.append(
            f"| {eid} | {tgt} | {_fmt(_mean(vals))} | **{_fmt(_std(vals))}** "
            f"| {min(vals)} | {max(vals)} |"
        )
    lines.append("")

    # ── 3. raw NLLB vs SchoolBridge 개선폭
    if "raw_nllb" in targets and "schoolbridge" in targets:
        lines += ["## 3. raw NLLB → SchoolBridge 개선폭", "",
                  "| 언어 | 카테고리 | raw NLLB 평균 | SchoolBridge 평균 | 개선폭 |",
                  "|---|---|---|---|---|"]
        for lang in langs:
            for cat in categories:
                raw_vals = [
                    r["total_score"] for r in agg["raw_scores"]
                    if r["target"] == "raw_nllb"
                    and r["eval_id"].endswith(f"_{lang}")
                    and inputs.get(r["eval_id"], {}).get("type") == cat
                ]
                sb_vals = [
                    r["total_score"] for r in agg["raw_scores"]
                    if r["target"] == "schoolbridge"
                    and r["eval_id"].endswith(f"_{lang}")
                    and inputs.get(r["eval_id"], {}).get("type") == cat
                ]
                if not raw_vals or not sb_vals:
                    continue
                delta = _mean(sb_vals) - _mean(raw_vals)
                sign = "+" if delta >= 0 else ""
                lines.append(
                    f"| {lang} | {cat} | {_fmt(_mean(raw_vals))} "
                    f"| {_fmt(_mean(sb_vals))} | **{sign}{_fmt(delta)}** |"
                )
        lines.append("")

    # ── 4. 카테고리별 평균 (전 평가자 합산)
    lines += ["## 4. 카테고리별 평균 점수 (전 평가자 합산)", "",
              "| 카테고리 | 언어 | " + " | ".join(t.upper() for t in targets) + " |",
              "|---|---|" + "---|" * len(targets)]
    for cat in categories:
        for lang in langs:
            cells = []
            for tgt in targets:
                vals = [
                    r["total_score"] for r in agg["raw_scores"]
                    if r["target"] == tgt
                    and r["eval_id"].endswith(f"_{lang}")
                    and inputs.get(r["eval_id"], {}).get("type") == cat
                ]
                cells.append(_fmt(_mean(vals)) if vals else "—")
            lines.append(f"| {cat} | {lang} | " + " | ".join(cells) + " |")
    lines.append("")

    # ── 5. Critical error rate
    lines += ["## 5. Critical Error Rate", "",
              "| 언어 | 카테고리 | target | critical 건수 / 전체 | 비율 |",
              "|---|---|---|---|---|"]
    for lang in langs:
        for cat in categories:
            for tgt in targets:
                rows = [
                    r for r in agg["raw_scores"]
                    if r["target"] == tgt
                    and r["eval_id"].endswith(f"_{lang}")
                    and inputs.get(r["eval_id"], {}).get("type") == cat
                ]
                if not rows:
                    continue
                crit = sum(1 for r in rows if r.get("critical_errors"))
                pct = crit / len(rows) * 100
                lines.append(f"| {lang} | {cat} | {tgt} | {crit}/{len(rows)} | {pct:.0f}% |")
    lines.append("")

    # ── 6. review_required rate (inputs 기준)
    if inputs:
        lines += ["## 6. Review Required Rate (가드 시스템)", "",
                  "| 언어 | 카테고리 | review_required 건수 / 전체 | 비율 |",
                  "|---|---|---|---|"]
        for lang in langs:
            for cat in categories:
                rows = [
                    v for v in inputs.values()
                    if v["target_lang"] == lang and v["type"] == cat
                ]
                if not rows:
                    continue
                rr = sum(1 for r in rows if r.get("review_required"))
                lines.append(f"| {lang} | {cat} | {rr}/{len(rows)} | {rr/len(rows)*100:.0f}% |")
        lines.append("")

    return lines


def _write_results_summary(agg: dict) -> None:
    evaluators = agg["evaluators"]
    targets    = agg["targets"]
    langs      = agg["langs"]
    inputs     = agg["inputs"]

    # 전 평가자 · 전 언어 · raw NLLB 평균
    raw_all = [r["total_score"] for r in agg["raw_scores"] if r["target"] == "raw_nllb"]
    sb_all  = [r["total_score"] for r in agg["raw_scores"] if r["target"] == "schoolbridge"]

    cat_avgs = {}
    for cat in ["template", "fallback", "risk"]:
        vals = [
            r["total_score"] for r in agg["raw_scores"]
            if r["target"] in ("schoolbridge", "raw_nllb")
            and inputs.get(r["eval_id"], {}).get("type") == cat
        ]
        cat_avgs[cat] = _mean(vals) if vals else 0.0

    rr_count = sum(1 for v in inputs.values() if v.get("review_required"))
    rr_total = len(inputs)

    crit_all  = sum(1 for r in agg["raw_scores"] if r.get("critical_errors"))
    crit_total = len(agg["raw_scores"])

    delta_str = ""
    if raw_all and sb_all:
        delta = _mean(sb_all) - _mean(raw_all)
        delta_str = f"\n- SchoolBridge 파이프라인 적용 후 평균 개선폭: **{delta:+.1f}점**"

    md = f"""# SchoolBridge 번역 품질 평가 요약

> **LLM 기반 내부 평가 결과이며, 원어민 검수 점수가 아닙니다.**
> 평가자: {', '.join(evaluators) if evaluators else '미입력'}
> 평가 언어: {', '.join(langs)}

## 핵심 지표

| 항목 | 값 |
|---|---|
| 평가 문장 수 | {rr_total}건 ({', '.join(langs)} 각 {rr_total // len(langs) if langs else 0}문장) |
| 평가자 수 | {len(evaluators)}개 |
| raw NLLB 전체 평균 | {_fmt(_mean(raw_all)) if raw_all else '—'}점 / 100점 |
| SchoolBridge 전체 평균 | {_fmt(_mean(sb_all)) if sb_all else '—'}점 / 100점 |
| Critical Error Rate | {crit_all}/{crit_total} ({crit_all/crit_total*100:.0f}% 오류) |
| Review Required Rate | {rr_count}/{rr_total} ({rr_count/rr_total*100:.0f}% 검수 대상) |{delta_str}

## 카테고리별 평균

| 카테고리 | 평균 점수 | 설명 |
|---|---|---|
| Template (정형) | {_fmt(cat_avgs['template'])}점 | 제출·준비·납부 등 정형 행동 문장 |
| Fallback (자유문) | {_fmt(cat_avgs['fallback'])}점 | 비정형 안내·정보 문장 |
| Risk (위험) | {_fmt(cat_avgs['risk'])}점 | 조건부·부정문·비학부모 대상 문장 |

## 점수 해석 기준

| 점수 | 등급 | 처리 방침 |
|---|---|---|
| 90~100 | 자동 제공 가능 | 학부모에게 바로 전송 |
| 80~89 | 검수 권장 | 핵심 정보 전달은 되나 일부 확인 |
| 70~79 | 검수 필요 | 오류 가능성 있음 |
| 60~69 | 자동 제공 위험 | review_required 처리 권장 |
| 0~59 | 자동 제공 불가 | review_required 처리 필수 |

## 평가 한계 및 주의사항

- 이 점수는 GPT/Claude/Gemini 등 LLM을 심사위원으로 사용한 **내부 평가**입니다.
- 원어민 또는 해당 언어권 교육 전문가 검수가 아닙니다.
- 특히 태국어·몽골어 등 소수 언어의 경우 LLM 평가 신뢰도가 낮을 수 있습니다.
- 평가자 간 점수 편차(std)가 ±10점 이상인 항목은 경계 사례로 별도 관리합니다.
- 자연스러움 점수(10점)는 현지 실사용 표현 여부까지 반영하기 어렵습니다.

---
*생성: run_collect_scores.py*
"""
    results_path = OUT_DIR / "results_summary.md"
    results_path.write_text(md, encoding="utf-8")
    print(f"[저장] {results_path}")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lang", nargs="+", default=None, help="언어 필터 (없으면 전체)")
    return p.parse_args()


def main():
    args = parse_args()

    inputs = load_inputs(args.lang)
    if not inputs:
        print(f"[경고] {INPUTS_FILE} 없음 또는 비어 있음.")
        print("  run_prepare_eval_inputs.py를 먼저 실행하세요.")

    scores = load_all_scores(args.lang)
    if not scores:
        print(f"[오류] {SCORES_DIR} 에 scores_*.jsonl 파일이 없습니다.")
        print("  evaluator_prompt.md 참고하여 평가 결과를 저장 후 재실행하세요.")
        return

    evaluators = sorted({r["evaluator"] for r in scores})
    print(f"평가자: {', '.join(evaluators)}")
    print(f"점수 레코드: {len(scores)}건\n")

    agg = aggregate(scores, inputs)
    print_and_save(agg)


if __name__ == "__main__":
    main()
