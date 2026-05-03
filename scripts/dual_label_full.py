"""v3_school_split_fixed_v2.jsonl 전체에 is_todo + is_title 라벨링."""
import json, random, sys, re, time, os
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import anthropic

INPUT = Path('model/extraction/data/v3_school_split_fixed_v2.jsonl')
OUTPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
BATCH = 10
BUDGET_STOP = 6.0
START_ROW = 22060  # 이어서 시작 (이전 중단 지점)
PRICE_IN = 0.80 / 1_000_000
PRICE_OUT = 4.00 / 1_000_000

# API 키
api_key = None
for line in Path('backend/.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        api_key = line.split('=', 1)[1].strip()
client = anthropic.Anthropic(api_key=api_key)

# label_sample에서 few-shot 예시 (균형 있게)
with open('model/extraction/data/label_sample.jsonl', encoding='utf-8') as f:
    sample = [json.loads(l) for l in f if l.strip()]
true_ex = [s for s in sample if s.get('is_todo')][:5]
false_ex = [s for s in sample if not s.get('is_todo')][:5]
fewshot = true_ex + false_ex
fewshot_text = '참고 예시 (is_todo 기준):\n'
for ex in fewshot:
    label = 'TRUE' if ex['is_todo'] else 'FALSE'
    fewshot_text += f'  [{label}] {ex["text"]}\n'

SYSTEM = f"""가정통신문 문장에 라벨 부여.

입력: [{{"i": 0, "text": "..."}}, {{"i": 1, "text": "..."}}, ...]
출력: [{{"i": 0, "todo": false, "title": true}}, {{"i": 1, "todo": true, "title": false}}, ...]

is_todo: 학부모가 직접 행동(제출/납부/준비/신청/참가/확인)해야 할 문장이면 true. 단순 정보/안내/배경 설명은 false.
is_title: 통신문 전체를 한 줄로 압축한 표제(제목)이면 true. 본문/표/안내 문구는 false.

{fewshot_text}

JSON 배열로만, 설명 없이. 각 입력의 i를 그대로 출력에 포함."""


def parse(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return json.loads(text)


def main():
    rows = []
    with open(INPUT, encoding='utf-8', errors='replace') as f:
        for l in f:
            if l.strip():
                try: rows.append(json.loads(l))
                except: pass

    n = len(rows)
    # 이어서 시작
    rows = rows[START_ROW:]
    n = len(rows)
    n_batches = (n + BATCH - 1) // BATCH
    print(f'이어서 시작 row {START_ROW} → 남은 {n}행 / {n_batches}배치 / 예산 ${BUDGET_STOP}', flush=True)

    total_cost = 0.0
    errors = 0
    t0 = time.time()

    out = open(OUTPUT, 'a', encoding='utf-8')  # append (이어쓰기)

    for bi in range(n_batches):
        batch_rows = rows[bi*BATCH : (bi+1)*BATCH]
        # 인덱스 부여한 입력
        indexed_input = [{"i": i, "text": r['text']} for i, r in enumerate(batch_rows)]

        # 인덱스 → 라벨 매핑 (기본 [F,F])
        labels_map = {i: [False, False] for i in range(len(batch_rows))}

        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=2048,
                system=[{'type':'text','text':SYSTEM,'cache_control':{'type':'ephemeral'}}],
                messages=[{'role':'user','content':json.dumps(indexed_input, ensure_ascii=False)}],
            )
            response_data = parse(resp.content[0].text)
            cost = resp.usage.input_tokens*PRICE_IN + resp.usage.output_tokens*PRICE_OUT
            total_cost += cost

            # 인덱스 기반 매핑 — 누락된 건 자동으로 [F,F] 유지
            missing = 0
            for item in response_data:
                if isinstance(item, dict) and 'i' in item:
                    idx = item['i']
                    if 0 <= idx < len(batch_rows):
                        labels_map[idx] = [bool(item.get('todo', False)), bool(item.get('title', False))]
            missing = sum(1 for i in range(len(batch_rows)) if i not in {x.get('i') for x in response_data if isinstance(x, dict)})
            if missing > 0:
                errors += missing

        except Exception as e:
            errors += len(batch_rows)
            if (bi+1) <= 5 or (bi+1) % 100 == 0:
                print(f'  배치 {bi+1} 오류: {str(e)[:80]}', flush=True)

        # 원본 순서대로 저장
        for i, row in enumerate(batch_rows):
            lab = labels_map[i]
            out.write(json.dumps({'text': row['text'], 'is_todo': lab[0], 'is_title': lab[1]}, ensure_ascii=False) + '\n')
        out.flush()

        if (bi+1) % 20 == 0:
            elapsed = time.time() - t0
            pct = (bi+1) / n_batches * 100
            print(f'  {bi+1}/{n_batches} ({pct:.1f}%) | ${total_cost:.3f} | {elapsed:.0f}s | 오류:{errors}', flush=True)

        if total_cost >= BUDGET_STOP:
            print(f'예산 ${BUDGET_STOP} 도달 — 중단', flush=True)
            break

    out.close()
    elapsed = time.time() - t0

    # 통계
    todo_n = title_n = 0
    with open(OUTPUT, encoding='utf-8') as f:
        for l in f:
            obj = json.loads(l)
            if obj.get('is_todo'): todo_n += 1
            if obj.get('is_title'): title_n += 1

    print(f'\n완료', flush=True)
    print(f'  비용: ${total_cost:.4f}', flush=True)
    print(f'  소요: {elapsed:.0f}s ({elapsed/60:.1f}분)', flush=True)
    print(f'  오류: {errors}', flush=True)
    print(f'  is_todo=True: {todo_n}', flush=True)
    print(f'  is_title=True: {title_n}', flush=True)
    print(f'  저장: {OUTPUT}', flush=True)


if __name__ == '__main__':
    main()
