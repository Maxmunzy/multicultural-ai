"""v3_dual_labeled.jsonl에서 학습 부적합 행을 제거하는 정제 스크립트.

제거 기준:
  - text 길이 > 5000자 (학구 안내 등 초대형 원문)
  - text 길이 < 10자 (의미 없는 토막)
  - text가 비어 있거나 공백만 있는 행
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MIN_LEN = 10
MAX_LEN = 5000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="학습 부적합 행을 제거해 깨끗한 JSONL을 생성합니다.")
    parser.add_argument("--input", required=True, help="입력 JSONL 경로 (v3_dual_labeled.jsonl 등)")
    parser.add_argument("--output", required=True, help="출력 JSONL 경로")
    parser.add_argument("--min_len", type=int, default=MIN_LEN, help=f"최소 text 길이 (기본값: {MIN_LEN})")
    parser.add_argument("--max_len", type=int, default=MAX_LEN, help=f"최대 text 길이 (기본값: {MAX_LEN})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    total = removed_empty = removed_short = removed_long = 0
    kept: list[str] = []

    with input_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[WARN] line {line_no} JSON 파싱 실패: {exc}", file=sys.stderr)
                continue

            total += 1
            text = str(obj.get("text", "") or "").strip()

            if not text:
                removed_empty += 1
                continue
            if len(text) < args.min_len:
                removed_short += 1
                continue
            if len(text) > args.max_len:
                removed_long += 1
                continue

            kept.append(json.dumps(obj, ensure_ascii=False))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    removed = removed_empty + removed_short + removed_long
    print(f"[OK] 입력: {total}행")
    print(f"[OK] 제거: {removed}행 (빈 텍스트 {removed_empty} / 짧음(<{args.min_len}자) {removed_short} / 길이({args.max_len}자 초과) {removed_long})")
    print(f"[OK] 보존: {len(kept)}행")
    print(f"[OK] 저장: {output_path}")


if __name__ == "__main__":
    main()
