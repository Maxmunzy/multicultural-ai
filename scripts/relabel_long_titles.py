"""80자+ is_title=True 행 재라벨링 — 더 엄격한 기준."""
import json, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import anthropic

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
BATCH = 10
PRICE_IN = 0.80 / 1_000_000
PRICE_OUT = 4.00 / 1_000_000

api_key = None
for line in Path('backend/.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        api_key = line.split('=', 1)[1].strip()
client = anthropic.Anthropic(api_key=api_key)

SYSTEM = """가정통신문 문장이 진짜 '제목'인지 엄격하게 판정.

제목 = 통신문의 표제 (예: "겨울방학 생활안내", "운동회 개최 안내", "2026 학부모 공개수업")
- 보통 짧음 (10-50자)
- 헤드라인 형태
- 본문 설명문장 X

제목이 아님 = 다음은 모두 false:
- "본교에서는 ~~을 실시합니다" 같은 본문 첫 문장
- "그동안 학교에서 가정으로~" 같은 인삿말 후 본문
- "아이들의 건강과 행복을 기원하며~" 같은 도입부
- 학교 슬로건/관용구
- 본문 설명/배경

입력: [{"i":0,"text":"..."},...]
출력: [{"i":0,"title":true},{"i":1,"title":false},...]
JSON 배열로만, 설명 없이."""


def parse(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return json.loads(text)


def main():
    rows = []
    with open(INPUT, encoding='utf-8') as f:
        for l in f:
            if l.strip():
                try: rows.append(json.loads(l))
                except: pass

    # 80자+ is_title=True 인덱스 수집
    target_idx = [i for i, r in enumerate(rows) if r.get('is_title') and len(r['text']) > 80]
    print(f"재라벨링 대상: {len(target_idx)}개", flush=True)

    # 변경 추적
    changed = 0
    total_cost = 0.0
    t0 = time.time()
    n_batches = (len(target_idx) + BATCH - 1) // BATCH

    for bi in range(n_batches):
        batch_idx = target_idx[bi*BATCH : (bi+1)*BATCH]
        indexed_input = [{"i": i, "text": rows[orig_i]['text']} for i, orig_i in enumerate(batch_idx)]

        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=1024,
                system=[{'type':'text','text':SYSTEM,'cache_control':{'type':'ephemeral'}}],
                messages=[{'role':'user','content':json.dumps(indexed_input, ensure_ascii=False)}],
            )
            result = parse(resp.content[0].text)
            cost = resp.usage.input_tokens*PRICE_IN + resp.usage.output_tokens*PRICE_OUT
            total_cost += cost

            for item in result:
                if isinstance(item, dict) and 'i' in item:
                    local_i = item['i']
                    if 0 <= local_i < len(batch_idx):
                        orig_i = batch_idx[local_i]
                        new_title = bool(item.get('title', False))
                        if rows[orig_i]['is_title'] != new_title:
                            rows[orig_i]['is_title'] = new_title
                            changed += 1
        except Exception as e:
            print(f"  배치 {bi+1} 오류: {str(e)[:60]}", flush=True)

        if (bi+1) % 5 == 0 or bi == n_batches-1:
            print(f"  {bi+1}/{n_batches} | ${total_cost:.4f} | {time.time()-t0:.0f}s | 변경:{changed}", flush=True)

    # 다시 저장
    with open(INPUT, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print(f"\n완료", flush=True)
    print(f"  비용: ${total_cost:.4f}", flush=True)
    print(f"  False로 변경: {changed}/{len(target_idx)}", flush=True)
    print(f"  is_title=True 잔여: {sum(1 for r in rows if r.get('is_title'))}", flush=True)


if __name__ == '__main__':
    main()
