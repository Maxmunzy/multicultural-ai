"""윤정님 기준 위반 행만 API로 재분할.

위반 조건 (OR):
  1. 길이 180자 초과 (윤정님 label_sample max 179자)
  2. 헤더 콜론 패턴 2개+ ("일시: ~ 장소: ~" 같이 항목 합쳐진 것)

입력: v3_school_split_fixed.jsonl (전체)
출력: v3_school_split_fixed_v2.jsonl (위반 행만 교체)
"""
import json, os, re, sys, time
from pathlib import Path
import anthropic

INPUT_FILE = Path("model/extraction/data/v3_school_split_fixed.jsonl")
OUTPUT_FILE = Path("model/extraction/data/v3_school_split_fixed_v2.jsonl")
LEN_THRESHOLD = 180  # 윤정님 label_sample max 179자
HEADER_COLON_RE = re.compile(
    r'(일시|장소|비용|준비물|기간|대상|신청|방법|연락처|문의|참가비|회비|수납|납부|기타|일정|시간)\s*[:：]'
)
BATCH_SIZE = 10
PRICE_IN = 0.80 / 1_000_000
PRICE_OUT = 4.00 / 1_000_000

SYSTEM = """한국어 가정통신문 문장 리스트를 받아 합쳐진 항목을 분리해 JSON 배열로 반환.
- 표/시간표/정보가 한 줄에 합쳐진 경우 항목별로 분리
- 의미 없는 토막(10자 미만) 제거
- 정상 문장은 그대로
- JSON 배열로만 응답."""


def load_key():
    for line in Path("backend/.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def parse(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def main():
    rows = []
    with open(INPUT_FILE, encoding="utf-8", errors="replace") as f:
        for l in f:
            if l.strip():
                try: rows.append(json.loads(l))
                except: pass

    def is_violation(text):
        if len(text) > LEN_THRESHOLD:
            return True
        if len(HEADER_COLON_RE.findall(text)) >= 2:
            return True
        return False

    long_idx = [i for i, r in enumerate(rows) if is_violation(r["text"])]
    n_long = sum(1 for i in long_idx if len(rows[i]["text"]) > LEN_THRESHOLD)
    n_header = len(long_idx) - n_long
    print(f"전체: {len(rows)}행 | 위반: {len(long_idx)}개 (길이 {n_long} + 헤더콜론 {n_header})", flush=True)

    client = anthropic.Anthropic(api_key=load_key())

    # 인덱스별 결과 저장: orig_idx -> [new_texts] (정상 처리 시) or None (실패)
    fixed = {}
    total_cost = 0.0
    errors = 0
    t0 = time.time()

    n_batches = (len(long_idx) + BATCH_SIZE - 1) // BATCH_SIZE

    for bi in range(n_batches):
        batch = long_idx[bi*BATCH_SIZE : (bi+1)*BATCH_SIZE]
        texts = [rows[i]["text"] for i in batch]

        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=SYSTEM,
                messages=[{"role":"user","content":json.dumps(texts, ensure_ascii=False)}],
            )
            result = parse(resp.content[0].text)
            cost = resp.usage.input_tokens*PRICE_IN + resp.usage.output_tokens*PRICE_OUT
            total_cost += cost

            # 배치 내 input N개 → output M개. 첫 인덱스에 전체 결과 저장,
            # 나머지 인덱스는 None으로 표시(스킵용)
            fixed[batch[0]] = result
            for i in batch[1:]:
                fixed[i] = None  # skip marker
        except Exception as e:
            errors += 1
            print(f"  [{bi+1}/{n_batches}] 오류: {str(e)[:60]}", flush=True)

        if (bi+1) % 5 == 0:
            elapsed = time.time() - t0
            print(f"  {bi+1}/{n_batches} ({(bi+1)/n_batches*100:.0f}%) | ${total_cost:.3f} | {elapsed:.0f}s | 오류:{errors}", flush=True)

    # 결과 합치기: 원본 순서 유지, 200자+ 행은 fixed 결과로 교체
    written = 0
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for i, row in enumerate(rows):
            if i not in fixed:
                # 일반 행 (200자 미만)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            elif fixed[i] is None:
                # 배치 내 첫 인덱스 아님 → 이미 처리됨, 스킵
                continue
            else:
                # 배치 첫 인덱스 → fixed 결과 씀
                for t in fixed[i]:
                    t = t.strip()
                    if t and len(t) >= 5:
                        out.write(json.dumps({"text": t, "is_todo": False}, ensure_ascii=False) + "\n")
                        written += 1

    long_after = sum(1 for r in [json.loads(l) for l in open(OUTPUT_FILE, encoding="utf-8") if l.strip()] if len(r["text"]) >= THRESHOLD)
    print(f"\n완료: {len(rows)}행 → {written}행", flush=True)
    print(f"  200자+ 잔여: {long_after}개 (이전 {len(long_idx)}개)", flush=True)
    print(f"  비용: ${total_cost:.4f}", flush=True)
    print(f"  오류: {errors}/{n_batches} 배치", flush=True)


if __name__ == "__main__":
    main()
