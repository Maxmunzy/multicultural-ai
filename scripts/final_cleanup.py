"""v3_dual_labeled.jsonl 최종 정제: dedup + 토막 → False + API 재검토."""
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


def parse(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return json.loads(text)


# 로드
rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_n = len(rows)
print(f"시작: {before_n}행")

# ============== 1. DEDUP ==============
print("\n[1] 중복 제거")
seen = {}
deduped = []
removed = 0
for r in rows:
    key = r['text']
    if key in seen:
        # 이미 본 텍스트 — 라벨 OR 처리 (둘 중 하나라도 True면 True 유지)
        existing = seen[key]
        existing['is_todo'] = existing['is_todo'] or r['is_todo']
        existing['is_title'] = existing['is_title'] or r['is_title']
        removed += 1
    else:
        seen[key] = r
        deduped.append(r)
print(f"  제거: {removed}행 ({before_n} → {len(deduped)})")
rows = deduped


# ============== 2. is_title 10자 미만 → False ==============
print("\n[2] is_title 10자 미만 → False")
short_title_count = 0
for r in rows:
    if r.get('is_title') and len(r['text']) < 10:
        r['is_title'] = False
        short_title_count += 1
print(f"  False로 변경: {short_title_count}")


# ============== 3. is_title False Negative + 인사말 끝 → API 재검토 ==============
print("\n[3] API 재검토")

# 후보 1: is_title=False인데 짧고 '안내/모집/공고'로 끝남
title_re = re.compile(r'(안내|모집|공고|개최|실시\s*안내)$')
fn_indices = [i for i, r in enumerate(rows)
              if not r.get('is_title') and 10 <= len(r['text']) <= 50
              and title_re.search(r['text'])]

# 후보 2: is_title=True인데 '안녕하십니까?'로 끝남
greet_end_re = re.compile(r'안녕하(십니까|세요)\??$')
greet_indices = [i for i, r in enumerate(rows)
                 if r.get('is_title') and greet_end_re.search(r['text'])]

target_idx = list(set(fn_indices + greet_indices))
print(f"  대상: {len(target_idx)}개 (FN {len(fn_indices)} + 인사말끝 {len(greet_indices)})")

SYSTEM = """가정통신문 문장이 진짜 '제목'인지 엄격하게 판정.

제목 = 통신문의 표제 (예: "겨울방학 생활안내", "운동회 개최 안내")
- 헤드라인 형태, 보통 짧음 (10-50자)
- "제목 + 안녕하십니까?" 합쳐진 경우도 제목 부분이 있으면 true

제목 아님 = 본문, 표 데이터, 인사말 단독, 번호 없는 부속 정보

입력: [{"i":0,"text":"..."},...]
출력: [{"i":0,"title":true/false},...]
JSON 배열로만, 설명 없이."""

if target_idx:
    n_batches = (len(target_idx) + BATCH - 1) // BATCH
    total_cost = 0
    changed = 0
    t0 = time.time()

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
            print(f"    {bi+1}/{n_batches} | ${total_cost:.4f} | {time.time()-t0:.0f}s | 변경:{changed}", flush=True)

    print(f"\n  비용: ${total_cost:.4f}, 변경: {changed}")


# ============== 저장 ==============
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

# 최종 통계
print(f"\n=== 최종 ===")
print(f"  전체: {before_n} → {len(rows)} (-{before_n-len(rows)})")
todo_t = sum(1 for r in rows if r.get('is_todo'))
title_t = sum(1 for r in rows if r.get('is_title'))
print(f"  is_todo=True: {todo_t}")
print(f"  is_title=True: {title_t}")
