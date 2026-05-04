"""카테고리 자동 라벨링 v5_full — v3_dual_labeled.jsonl 28,890행 중 is_todo=True만.

이전 v5는 윤정님 val split(5,330)만 사용 → 양 부족 (특히 준비물 70개).
v5_full은 28,890 전체의 is_todo=True 7,843개에 적용해서 학습 데이터 확장.

출력 (v4 양식 = UTF-8-BOM + CRLF + QUOTE_ALL):
  - model/classification/data/notice_sample_v5_full_20260504.csv
    v3 수동 142 + 자동 라벨 합본 (none 제외)
  - model/classification/data/v5_full_auto_only_20260504.jsonl (자동 라벨 검증용)
"""
import json, csv, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import Counter

import anthropic

PRICE_IN = 0.80 / 1_000_000
PRICE_OUT = 4.00 / 1_000_000
CACHE_READ = 0.08 / 1_000_000

BATCH = 20
MODEL = "claude-haiku-4-5-20251001"
LABELS = {"일정", "준비물", "제출", "비용", "건강·안전", "기타"}

INPUT_JSONL = Path('model/extraction/data/train/v3_dual_labeled.jsonl')
V3_CSV = Path('model/classification/data/notice_sample_v3.csv')
OUT_CSV = Path('model/classification/data/notice_sample_v5_full_20260504.csv')
OUT_JSONL = Path('model/classification/data/v5_full_auto_only_20260504.jsonl')

api_key = None
for line in Path('backend/.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        api_key = line.split('=', 1)[1].strip()
        break
client = anthropic.Anthropic(api_key=api_key)


FEWSHOT = """예시:
- "현장체험학습 참가비 3만 원을 3월 20일까지 납부해 주세요." → 비용
- "마스크와 도시락을 챙겨주세요." → 준비물
- "동의서를 4월 5일까지 담임 선생님께 제출 부탁드립니다." → 제출
- "5월 28일(목) 오전 9시 운동회를 개최합니다." → 일정
- "발열 증상이 있을 경우 가정에서 자가진단 후 등교하지 마세요." → 건강·안전
- "본 통신문 관련 문의는 학교(02-XXX-XXXX)로 연락 주시기 바랍니다." → 기타
- "학부모님 안녕하십니까? 가정에 평안이 가득하시기를 기원합니다." → none
- "꿈을 키우며 함께 성장하는 학교" → none
"""

SYSTEM = f"""당신은 한국 가정통신문 텍스트를 분류하는 라벨러입니다.
각 입력 텍스트가 학부모가 행동·인지해야 할 todo인지 판단하고, 맞으면 6개 카테고리 중 하나로 분류하세요.

카테고리 (todo인 경우):
- 일정: 날짜·시간·행사·운영기간 등 시간/장소 안내
- 준비물: 학생이 챙겨야 할 물건/복장/도구
- 제출: 서류·동의서·설문·신청서·작성·회신·등록·동의
- 비용: 납부·입금·수강료·금액 관련
- 건강·안전: 예방접종·증상·자가진단·안전수칙·복약·금지행동
- 기타: 학부모가 인지·행동해야 하지만 위 5개 어디에도 명확히 안 맞는 todo

none (todo 아님):
- 인사말, 본문 설명, 학교 슬로건, 표 헤더, 메타정보, 링크 단독
- 학부모가 "행동·인지해야 할 정보"가 아닌 일반 안내

{FEWSHOT}

입력: [{{"i":0,"text":"..."}},...]
출력: [{{"i":0,"category":"일정"}},{{"i":1,"category":"none"}},...]
JSON 배열로만, 설명 없이. category는 정확히 "일정"/"준비물"/"제출"/"비용"/"건강·안전"/"기타"/"none" 중 하나."""


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return json.loads(text)


def call_api(items):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content': json.dumps(items, ensure_ascii=False)}],
    )
    usage = resp.usage
    cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
    cost = (
        usage.input_tokens * PRICE_IN
        + usage.output_tokens * PRICE_OUT
        + cache_read * CACHE_READ
    )
    return parse_json(resp.content[0].text), cost


# 1. 입력 로드 — is_todo=True만
rows = []
n_skip_not_todo = 0
with open(INPUT_JSONL, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            r = json.loads(l)
            if r.get('is_todo'):
                rows.append({'text': r['text'], 'is_todo': True})
            else:
                n_skip_not_todo += 1
print(f"입력: {len(rows)}행 (is_todo=True), 제외: {n_skip_not_todo}행 (is_todo=False)")

# 2. 배치 라벨링 + incremental 저장
auto_labels = []
n_batch = (len(rows) + BATCH - 1) // BATCH
total_cost = 0
t0 = time.time()
err_count = 0

for bi in range(n_batch):
    batch = rows[bi * BATCH:(bi + 1) * BATCH]
    items = [{"i": i, "text": r["text"]} for i, r in enumerate(batch)]
    try:
        result, cost = call_api(items)
        total_cost += cost
        for item in result:
            if isinstance(item, dict) and 'i' in item and 'category' in item:
                li = item['i']
                if 0 <= li < len(batch):
                    auto_labels.append({
                        'text': batch[li]['text'],
                        'category': item['category'],
                        'is_todo': batch[li]['is_todo'],
                    })
    except Exception as e:
        err_count += 1
        print(f"  배치 {bi+1} 오류: {str(e)[:80]}", flush=True)

    if (bi + 1) % 50 == 0 or bi == n_batch - 1:
        print(f"    {bi+1}/{n_batch} | ${total_cost:.4f} (₩{total_cost*1380:.0f}) | {time.time()-t0:.0f}s | 오류 {err_count}", flush=True)

    # 100 batch마다 incremental 저장
    if (bi + 1) % 100 == 0:
        with open(OUT_JSONL, 'w', encoding='utf-8') as f:
            for r in auto_labels:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

# 3. 최종 jsonl 저장
with open(OUT_JSONL, 'w', encoding='utf-8') as f:
    for r in auto_labels:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

# 4. 분포 통계
dist = Counter(r['category'] for r in auto_labels)
print(f"\n=== 자동 라벨 분포 (총 {len(auto_labels)}/{len(rows)}) ===")
for cat in ['일정', '준비물', '제출', '비용', '건강·안전', '기타', 'none']:
    print(f"  {cat}: {dist.get(cat, 0)}")

# 5. v3 + 자동 라벨 합본 (none 제외)
labeled = []
seen = set()
with open(V3_CSV, encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        text = row.get('text', '').strip()
        cat = row.get('category', '').strip()
        if text and cat in LABELS:
            labeled.append((text, cat))
            seen.add(text)

auto_added = 0
for r in auto_labels:
    if r['category'] in LABELS and r['text'] not in seen:
        labeled.append((r['text'], r['category']))
        seen.add(r['text'])
        auto_added += 1

# 6. csv 저장 (UTF-8-BOM)
with open(OUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f, quoting=csv.QUOTE_ALL)
    w.writerow(['text', 'category'])
    for text, cat in labeled:
        w.writerow([text, cat])

final_dist = Counter(c for _, c in labeled)
print(f"\n=== v5_full csv 최종 ({OUT_CSV.name}) ===")
print(f"  v3 수동 142 + 자동 추가 {auto_added} = {len(labeled)}행")
for cat in ['일정', '준비물', '제출', '비용', '건강·안전', '기타']:
    print(f"  {cat}: {final_dist.get(cat, 0)}")

print(f"\n총 비용: ${total_cost:.4f} (₩{total_cost*1380:.0f})")
print(f"총 시간: {time.time()-t0:.0f}s")
print(f"오류: {err_count}/{n_batch}")
