"""Claude Haiku API로 v3_school_dedup.jsonl 문장 분할 교정.

안전장치:
- 입력 파일 절대 수정 안 함 (출력은 별도 파일)
- API 오류 / 파싱 실패 / 이상한 출력 → 원본 그대로 유지
- incremental 저장 (배치마다 flush)
- --start-batch N 으로 중간 재개 가능
- $18 초과 시 자동 중단

사용:
  python scripts/split_fix_api.py
  python scripts/split_fix_api.py --start-batch 200
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic

BATCH_SIZE = 30
BUDGET_STOP_USD = 18.0
INPUT_FILE = Path(r"C:\Users\ashle\AppData\Local\Temp\v3_clean.jsonl")
OUTPUT_FILE = Path("model/extraction/data/v3_school_split_fixed.jsonl")
PROGRESS_EVERY = 50

PRICE_IN  = 0.80 / 1_000_000
PRICE_OUT = 4.00 / 1_000_000

SYSTEM_PROMPT = """너는 한국어 가정통신문 학습 데이터 전처리 전문가야.
문장 리스트를 JSON 배열로 받아, 잘못 합쳐진 항목만 분리하고 JSON 배열로 반환해.

규칙:
1. 여러 항목이 한 줄에 합쳐진 경우 항목별로 분리
2. 의미 없는 토막(10자 미만, 번호/기호만) 제거
3. 정상적인 문장은 그대로 유지 (수정 최소화)
4. JSON 배열로만 응답. 설명 없이."""


def load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env = Path("backend/.env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def parse_response(text: str) -> list[str]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    result = json.loads(text.strip())
    if not isinstance(result, list):
        raise ValueError("응답이 배열이 아님")
    return result


def validate(original: list[str], fixed: list[str]) -> bool:
    """이상한 출력 감지."""
    if not fixed:
        return False
    # 출력이 입력보다 10배 이상 많으면 이상
    if len(fixed) > len(original) * 10:
        return False
    # 한글이 거의 없는 문자열이 절반 이상이면 이상
    hangul_re = re.compile(r'[가-힣]')
    bad = sum(1 for t in fixed if len(hangul_re.findall(t)) < 2)
    if bad > len(fixed) * 0.5:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-batch", type=int, default=0)
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key:
        print("ANTHROPIC_API_KEY 없음. backend/.env 확인")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    rows = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    total = len(rows)
    n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"입력: {total}개 | 배치: {n_batches}개 | 예산 상한: ${BUDGET_STOP_USD}")

    mode = "a" if args.start_batch > 0 else "w"
    total_cost = 0.0
    total_in = total_out = 0
    api_errors = fallback_used = 0
    t0 = time.time()

    with open(OUTPUT_FILE, mode, encoding="utf-8") as out_f:
        for batch_idx in range(args.start_batch, n_batches):
            start = batch_idx * BATCH_SIZE
            batch_rows = rows[start: start + BATCH_SIZE]
            texts = [r["text"] for r in batch_rows]

            try:
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=4096,
                    system=[{
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=[{"role": "user", "content": json.dumps(texts, ensure_ascii=False)}],
                )

                fixed = parse_response(resp.content[0].text)
                cost = resp.usage.input_tokens * PRICE_IN + resp.usage.output_tokens * PRICE_OUT
                total_cost += cost
                total_in += resp.usage.input_tokens
                total_out += resp.usage.output_tokens

                if not validate(texts, fixed):
                    raise ValueError(f"검증 실패: in={len(texts)}, out={len(fixed)}")

                output = fixed

            except Exception as e:
                api_errors += 1
                fallback_used += len(texts)
                output = texts  # 원본 유지

            for text in output:
                text = text.strip()
                if text and len(text) >= 5:
                    out_f.write(json.dumps({"text": text, "is_todo": False}, ensure_ascii=False) + "\n")
            out_f.flush()

            if (batch_idx + 1) % PROGRESS_EVERY == 0 or batch_idx == n_batches - 1:
                elapsed = time.time() - t0
                pct = (batch_idx + 1) / n_batches * 100
                print(f"  배치 {batch_idx+1}/{n_batches} ({pct:.1f}%) | ${total_cost:.2f} | {elapsed:.0f}s | 오류:{api_errors}")

            if total_cost >= BUDGET_STOP_USD:
                print(f"\n예산 ${BUDGET_STOP_USD} 도달 → 중단 (배치 {batch_idx})")
                print(f"재개: python scripts/split_fix_api.py --start-batch {batch_idx+1}")
                break

    elapsed = time.time() - t0
    print(f"\n완료")
    print(f"  비용: ${total_cost:.4f} (in={total_in:,}, out={total_out:,})")
    print(f"  API 오류: {api_errors}건 (원본 유지: {fallback_used}줄)")
    print(f"  소요: {elapsed:.0f}s")
    print(f"  저장: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
