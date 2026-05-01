"""가정통신문 문장의 todo 라벨 검수 초안을 생성하는 스크립트.

이 스크립트는 정답 라벨을 만드는 도구가 아니라, 사람이 빠르게 검수할 수
있는 draft_is_todo와 review_required 초안을 만드는 보조 파이프라인이다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TODO_KEYWORDS = {
    "제출": "제출 행동",
    "신청": "신청 행동",
    "준비": "준비 행동",
    "준비물": "준비물 목록",
    "가져": "가져오기 행동",
    "지참": "지참 행동",
    "납부": "납부 행동",
    "입금": "납부 행동",
    "참석": "참석 행동",
    "참가": "참가 행동",
    "확인": "확인 행동",
    "알림": "알림 행동",
    "문의": "문의 행동",
    "상담": "상담 행동",
    "동의": "동의 행동",
    "서명": "서명 행동",
    "회신": "회신 행동",
    "복용": "복용 행동",
    "금지": "금지 행동",
    "지도": "가정 지도",
    "협조": "협조 요청",
}

FALSE_HINTS = {
    "안녕하십니까": "인사말",
    "가득하시길": "인사말",
    "실시합니다": "행사 실시 안내",
    "운영합니다": "운영 안내",
    "장소": "장소 정보",
    "예상 경비": "비용 정보",
    "경비": "비용 정보",
    "비용": "비용 정보",
    "학교 예산": "지원금 안내",
    "지원": "지원금/지원 안내",
    "안내 말씀": "안내 문구",
    "목적": "목적 설명",
    "참고": "참고사항",
}

CONDITIONAL_HINTS = {
    "경우": "조건부 표현",
    "필요하신 경우": "조건부 표현",
    "희망": "희망자 대상",
    "원하": "선택/희망 표현",
    "가능": "가능 여부 안내",
    "협의": "협의 필요",
}

DEADLINE_RE = re.compile(
    r"(\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}/\d{1,2}|까지|기한)"
)
ITEM_LIST_RE = re.compile(r"(준비물|지참물|개인 준비물)\s*[:：]")
MONEY_ONLY_RE = re.compile(r"^\s*(예상\s*)?(경비|비용|금액)\s*[:：]?.*\d[\d,]*\s*원\s*$")
GEMINI_MIXED_HINTS = ("준비물:", "준비물：", "기타:", "기타：", "검사", "주의", "제출", "신청")
GEMINI_DEFAULT_MODEL = "gemini-1.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

OUTPUT_FIELDS = [
    "id",
    "original_text",
    "split_text",
    "original_is_todo",
    "draft_is_todo",
    "reason",
    "review_required",
    "segment_source",
    "segment_index",
    "gemini_segment_reason",
]

GEMINI_SEGMENT_PROMPT = """너는 초등학교 가정통신문 원문을 학습 데이터용 의미 단위로 분리하고, 각 단위가 학부모/학생의 할 일인지 분류하는 데이터 라벨러다.

목표:
원문 한 줄을 그대로 학습에 넣지 말고, 하나의 행동 또는 하나의 정보가 담긴 단위로 나눈다.

분리 기준:
- 하나의 행동은 하나의 단위로 분리한다.
- 하나의 안내 정보는 하나의 단위로 분리한다.
- 인사말, 장소, 비용, 준비물, 제출 요청, 주의사항은 서로 다른 단위로 분리한다.
- 괄호 안 설명은 앞 문장에 붙여도 된다.
- 너무 잘게 자르지 말고, 사람이 검수하기 좋은 단위로 나눈다.
- 원문에 없는 내용을 새로 만들지 않는다.
- 원문 표현을 최대한 유지한다.

is_todo=true 기준:
- 제출, 신청, 준비, 가져오기, 납부, 참석, 확인, 서명, 회신, 문의, 상담
- 선생님께 알리기
- 검사 전날 하지 말아야 할 행동
- 약 복용/금지/주의사항
- 준비물 목록
- 가정에서 지도하거나 알려줘야 하는 내용

is_todo=false 기준:
- 인사말
- 행사 목적/배경 설명
- 장소 안내
- 비용/지원금 안내
- 단순 참고사항
- 학교에서 자체적으로 처리하는 내용

출력은 반드시 JSON 배열 하나로만 반환한다.

형식:
[
  {
    "split_text": "의미 단위 문장",
    "is_todo": true,
    "reason": "짧은 판단 이유",
    "review_required": false,
    "segment_reason": "분리 이유"
  }
]

예시:
원문:
"검사 전날 지나치게 많은 야채나 과일, 비타민 C를 섭취하지 않습니다. 심하게 운동하지 않습니다.(검사 결과에 영향을 줄 수 있습니다) 소변은 처음과 마지막 소변이 아닌 중간에 나오는 소변을 컵에 받습니다."

출력:
[
  {
    "split_text": "검사 전날 지나치게 많은 야채나 과일, 비타민 C를 섭취하지 않습니다.",
    "is_todo": true,
    "reason": "검사 전날 피해야 할 행동이 있음",
    "review_required": false,
    "segment_reason": "금지 행동 하나를 별도 단위로 분리"
  },
  {
    "split_text": "심하게 운동하지 않습니다.(검사 결과에 영향을 줄 수 있습니다)",
    "is_todo": true,
    "reason": "검사 전날 피해야 할 행동이 있음",
    "review_required": false,
    "segment_reason": "금지 행동과 그 이유를 하나의 단위로 분리"
  },
  {
    "split_text": "소변은 처음과 마지막 소변이 아닌 중간에 나오는 소변을 컵에 받습니다.",
    "is_todo": true,
    "reason": "검사 시 학생이 수행해야 할 행동이 있음",
    "review_required": false,
    "segment_reason": "검사 수행 행동을 별도 단위로 분리"
  }
]
"""


def split_text_units(text: str) -> list[str]:
    """괄호 안 구두점은 최대한 보존하면서 검수용 의미 단위로 나눈다."""
    if not text:
        return []

    units: list[str] = []
    current: list[str] = []
    paren_depth = 0
    bracket_pairs = {"(": ")", "[": "]", "{": "}", "（": "）"}
    closing_brackets = set(bracket_pairs.values())

    for char in text:
        current.append(char)

        if char in bracket_pairs:
            paren_depth += 1
            continue
        if char in closing_brackets and paren_depth > 0:
            paren_depth -= 1
            continue

        if paren_depth == 0 and char in ".?!。？！\n":
            unit = "".join(current).strip()
            if unit:
                units.append(unit)
            current = []

    tail = "".join(current).strip()
    if tail:
        units.append(tail)

    return [unit for unit in units if unit]


def build_draft_label(split_text: str) -> tuple[bool, str, bool]:
    """문장 하나에 대해 검수용 초안 라벨과 판단 근거를 만든다."""
    text = normalize_space(split_text)
    todo_reasons = [reason for keyword, reason in TODO_KEYWORDS.items() if keyword in text]
    false_reasons = [reason for keyword, reason in FALSE_HINTS.items() if keyword in text]
    conditional_reasons = [reason for keyword, reason in CONDITIONAL_HINTS.items() if keyword in text]

    if ITEM_LIST_RE.search(text):
        todo_reasons.append("준비물/지참물 목록")

    has_deadline = bool(DEADLINE_RE.search(text))
    has_action = bool(todo_reasons)
    if has_deadline and has_action:
        todo_reasons.append("마감일과 행동 단서 동시 포함")

    if MONEY_ONLY_RE.search(text) and not has_action:
        false_reasons.append("비용 정보만 포함")

    draft_is_todo = bool(todo_reasons)
    review_required = False
    reason_parts: list[str] = []

    if todo_reasons:
        reason_parts.append("todo 단서: " + unique_join(todo_reasons))
    if false_reasons:
        reason_parts.append("안내 단서: " + unique_join(false_reasons))
    if conditional_reasons:
        reason_parts.append("검수 필요 단서: " + unique_join(conditional_reasons))

    if conditional_reasons:
        review_required = True
    if todo_reasons and false_reasons:
        review_required = True
    if not todo_reasons and not false_reasons:
        reason_parts.append("명확한 행동/안내 단서 없음")
        review_required = True

    return draft_is_todo, " | ".join(reason_parts), review_required


def should_use_gemini_segment(original_text: str) -> bool:
    """Gemini 의미 단위 분리가 도움이 될 가능성이 큰 원문인지 판단한다."""
    text = original_text or ""
    if len(text) >= 80:
        return True
    if text.count(".") >= 2:
        return True
    return any(hint in text for hint in GEMINI_MIXED_HINTS)


def gemini_api_key() -> str:
    """Gemini API 키를 환경변수에서 가져온다."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def load_dotenv_if_available() -> None:
    """python-dotenv가 있으면 .env를 읽고, 없으면 기존 환경변수만 사용한다."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def call_gemini_segment(original_text: str, api_key: str, model: str, timeout: int) -> list[dict[str, Any]]:
    """원문 한 줄을 Gemini에 보내 의미 단위와 draft 라벨을 받는다."""
    prompt = GEMINI_SEGMENT_PROMPT + "\n\n원문:\n" + original_text
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        GEMINI_API_URL.format(model=model) + "?key=" + api_key,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Gemini HTTP 오류: status={exc.code}, body={detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Gemini 연결 오류: {exc.reason}") from exc

    data = json.loads(response_body)
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini 응답에 candidates가 없음")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise ValueError("Gemini 응답 text가 비어 있음")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:500].replace("\n", "\\n")
        print(f"[WARN] Gemini JSON 파싱 실패. 응답 일부: {preview}", file=sys.stderr)
        raise ValueError("Gemini JSON 파싱 실패") from exc

    if not isinstance(parsed, list):
        raise ValueError("Gemini 응답이 JSON 배열이 아님")
    return [item for item in parsed if isinstance(item, dict)]


def normalize_gemini_segments(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gemini 응답을 출력 row 생성에 쓸 수 있는 형태로 정리한다."""
    segments: list[dict[str, Any]] = []
    for item in items:
        split_text = normalize_space(str(item.get("split_text", "") or ""))
        if not split_text:
            continue
        segments.append(
            {
                "split_text": split_text,
                "draft_is_todo": coerce_bool(item.get("is_todo", False)),
                "reason": normalize_space(str(item.get("reason", "") or "Gemini draft 라벨")),
                "review_required": coerce_bool(item.get("review_required", False)),
                "gemini_segment_reason": normalize_space(str(item.get("segment_reason", "") or "")),
            }
        )
    return segments


def normalize_space(value: str) -> str:
    """검수 출력이 흔들리지 않도록 공백을 정리한다."""
    return re.sub(r"\s+", " ", value).strip()


def coerce_bool(value: Any) -> bool:
    """Gemini가 bool을 문자열로 돌려줘도 안전하게 bool로 바꾼다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def unique_join(values: list[str]) -> str:
    """근거 문구의 중복을 제거하되 발견 순서는 유지한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ", ".join(ordered)


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    """잘못된 JSON 라인은 건너뛰고 경고만 출력한다."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[WARN] JSON 파싱 실패: line={line_no}, error={exc}", file=sys.stderr)
                continue
            if not isinstance(data, dict):
                print(f"[WARN] 객체가 아닌 JSON 라인 건너뜀: line={line_no}", file=sys.stderr)
                continue
            rows.append(data)
    return rows


def make_rule_rows(
    original_text: str,
    original_is_todo: Any,
    start_id: int,
) -> tuple[list[dict[str, Any]], int]:
    """기존 rule split 방식으로 draft row를 만든다."""
    split_units = split_text_units(original_text) or [original_text.strip()]
    normalized_original = normalize_space(original_text)
    segment_source = "original" if len(split_units) == 1 and normalize_space(split_units[0]) == normalized_original else "rule_split"
    rows: list[dict[str, Any]] = []
    next_id = start_id

    for segment_index, split_unit in enumerate(split_units):
        split_text = normalize_space(split_unit)
        if not split_text:
            continue
        draft_is_todo, reason, review_required = build_draft_label(split_text)
        rows.append(
            {
                "id": next_id,
                "original_text": original_text,
                "split_text": split_text,
                "original_is_todo": original_is_todo,
                "draft_is_todo": draft_is_todo,
                "reason": reason,
                "review_required": review_required,
                "segment_source": segment_source,
                "segment_index": segment_index,
                "gemini_segment_reason": "",
            }
        )
        next_id += 1

    return rows, next_id


def make_gemini_rows(
    original_text: str,
    original_is_todo: Any,
    start_id: int,
    api_key: str,
    model: str,
    timeout: int,
) -> tuple[list[dict[str, Any]], int]:
    """Gemini 의미 단위 분리 결과를 draft row로 만든다."""
    items = call_gemini_segment(original_text, api_key=api_key, model=model, timeout=timeout)
    segments = normalize_gemini_segments(items)
    if not segments:
        raise ValueError("Gemini segment 결과가 비어 있음")

    rows: list[dict[str, Any]] = []
    next_id = start_id
    for segment_index, segment in enumerate(segments):
        rows.append(
            {
                "id": next_id,
                "original_text": original_text,
                "split_text": segment["split_text"],
                "original_is_todo": original_is_todo,
                "draft_is_todo": segment["draft_is_todo"],
                "reason": segment["reason"],
                "review_required": segment["review_required"],
                "segment_source": "gemini_segment",
                "segment_index": segment_index,
                "gemini_segment_reason": segment["gemini_segment_reason"],
            }
        )
        next_id += 1

    return rows, next_id


def make_draft_rows(
    source_rows: list[dict[str, Any]],
    use_gemini_segment: bool = False,
    gemini_model: str = GEMINI_DEFAULT_MODEL,
    gemini_timeout: int = 30,
) -> list[dict[str, Any]]:
    """원본 row를 문장 단위 draft row로 변환한다."""
    draft_rows: list[dict[str, Any]] = []
    next_id = 1
    api_key = gemini_api_key() if use_gemini_segment else ""

    if use_gemini_segment and not api_key:
        print("[WARN] GEMINI_API_KEY 또는 GOOGLE_API_KEY가 없어 rule_split만 수행합니다.", file=sys.stderr)

    for source in source_rows:
        original_text = str(source.get("text", "") or "")
        original_is_todo = source.get("is_todo")
        use_gemini_for_row = use_gemini_segment and bool(api_key) and should_use_gemini_segment(original_text)

        if use_gemini_for_row:
            try:
                rows, next_id = make_gemini_rows(
                    original_text=original_text,
                    original_is_todo=original_is_todo,
                    start_id=next_id,
                    api_key=api_key,
                    model=gemini_model,
                    timeout=gemini_timeout,
                )
                draft_rows.extend(rows)
                continue
            except Exception as exc:
                preview = original_text[:80].replace("\n", " ")
                print(f"[WARN] Gemini segmentation 실패, rule_split fallback: {exc} | text={preview}", file=sys.stderr)

        rows, next_id = make_rule_rows(
            original_text=original_text,
            original_is_todo=original_is_todo,
            start_id=next_id,
        )
        draft_rows.extend(rows)

    return draft_rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JSONL 문장을 사람이 검수하기 쉬운 todo draft 라벨 파일로 변환합니다."
    )
    parser.add_argument("--input_path", required=True, help="입력 JSONL 경로")
    parser.add_argument("--output_jsonl_path", required=True, help="출력 draft JSONL 경로")
    parser.add_argument("--output_csv_path", required=True, help="출력 draft CSV 경로")
    parser.add_argument(
        "--use_gemini_segment",
        action="store_true",
        help="조건에 맞는 original_text를 Gemini로 의미 단위 분리한 뒤 draft 라벨을 생성",
    )
    parser.add_argument(
        "--gemini_model",
        default=os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL),
        help=f"Gemini 모델명, 기본값: {GEMINI_DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--gemini_timeout",
        type=int,
        default=30,
        help="Gemini API 요청 타임아웃 초",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv_if_available()
    args = parse_args()
    input_path = Path(args.input_path)
    output_jsonl_path = Path(args.output_jsonl_path)
    output_csv_path = Path(args.output_csv_path)

    source_rows = iter_jsonl(input_path)
    draft_rows = make_draft_rows(
        source_rows,
        use_gemini_segment=args.use_gemini_segment,
        gemini_model=args.gemini_model,
        gemini_timeout=args.gemini_timeout,
    )
    write_jsonl(output_jsonl_path, draft_rows)
    write_csv(output_csv_path, draft_rows)

    print(f"[OK] 입력 row: {len(source_rows)}")
    print(f"[OK] draft row: {len(draft_rows)}")
    print(f"[OK] JSONL 저장: {output_jsonl_path}")
    print(f"[OK] CSV 저장: {output_csv_path}")


if __name__ == "__main__":
    main()
