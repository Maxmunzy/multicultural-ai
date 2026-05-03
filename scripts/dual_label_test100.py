"""dual_label 100행 테스트 — 수정된 버전 검증."""
import json, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import anthropic

BATCH = 20
PRICE_IN = 0.80 / 1_000_000
PRICE_OUT = 4.00 / 1_000_000

api_key = None
for line in Path('backend/.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        api_key = line.split('=', 1)[1].strip()
client = anthropic.Anthropic(api_key=api_key)

with open('model/extraction/data/label_sample.jsonl', encoding='utf-8') as f:
    sample = [json.loads(l) for l in f if l.strip()]
true_ex = [s for s in sample if s.get('is_todo')][:5]
false_ex = [s for s in sample if not s.get('is_todo')][:5]
fewshot_text = '참고 예시 (is_todo 기준):\n'
for ex in true_ex + false_ex:
    label = 'TRUE' if ex['is_todo'] else 'FALSE'
    fewshot_text += f'  [{label}] {ex["text"]}\n'

SYSTEM = f"""가정통신문 문장 리스트 → 각 문장에 [is_todo, is_title] 라벨.

is_todo: 학부모가 직접 행동(제출/납부/준비/신청/참가/확인)해야 할 문장이면 true. 단순 정보/안내/배경 설명은 false.
is_title: 통신문 전체를 한 줄로 압축한 표제(제목)이면 true. 본문/표/안내 문구는 false.

{fewshot_text}

JSON 배열로만, 설명 없이. 각 문장마다 정확히 [bool, bool] 한 개씩, 입력 개수와 출력 개수가 반드시 일치해야 함."""

def parse(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return json.loads(text)

# 입력
rows = []
with open('model/extraction/data/v3_school_split_fixed_v2.jsonl', encoding='utf-8', errors='replace') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

test_rows = rows[:100]
n_batches = (len(test_rows) + BATCH - 1) // BATCH

total_cost = 0
mismatch = 0
all_labels = []
t0 = time.time()

for bi in range(n_batches):
    batch = test_rows[bi*BATCH : (bi+1)*BATCH]
    texts = [r['text'] for r in batch]

    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2048,
            system=[{'type':'text','text':SYSTEM,'cache_control':{'type':'ephemeral'}}],
            messages=[{'role':'user','content':json.dumps(texts, ensure_ascii=False)}],
        )
        labels = parse(resp.content[0].text)
        cost = resp.usage.input_tokens*PRICE_IN + resp.usage.output_tokens*PRICE_OUT
        total_cost += cost

        if len(labels) != len(texts):
            mismatch += 1
            print(f"배치 {bi+1}: 개수 불일치 ({len(texts)} → {len(labels)})", flush=True)
            if len(labels) < len(texts):
                labels.extend([[False, False]] * (len(texts) - len(labels)))
            else:
                labels = labels[:len(texts)]
        else:
            print(f"배치 {bi+1}: ✅ {len(labels)}개", flush=True)

        for text, lab in zip(texts, labels):
            all_labels.append({'text': text, 'is_todo': bool(lab[0]), 'is_title': bool(lab[1])})

    except Exception as e:
        print(f"배치 {bi+1}: ❌ 오류 — {str(e)[:60]}", flush=True)
        for text in texts:
            all_labels.append({'text': text, 'is_todo': False, 'is_title': False})

elapsed = time.time() - t0
todo_n = sum(1 for r in all_labels if r['is_todo'])
title_n = sum(1 for r in all_labels if r['is_title'])

print(f"\n=== 결과 ===")
print(f"전체: {len(all_labels)}행 | 비용: ${total_cost:.4f} | {elapsed:.0f}s")
print(f"개수 불일치 배치: {mismatch}/{n_batches}")
print(f"is_todo=True: {todo_n} ({todo_n/len(all_labels)*100:.1f}%)")
print(f"is_title=True: {title_n} ({title_n/len(all_labels)*100:.1f}%)")
print(f"\n=== 첫 30행 샘플 ===")
for r in all_labels[:30]:
    todo = 'T' if r['is_todo'] else 'F'
    title = 'T' if r['is_title'] else 'F'
    print(f"  [{todo}/{title}] {r['text'][:60]}")
