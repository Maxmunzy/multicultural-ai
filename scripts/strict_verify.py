"""is_title=True 전체 + is_todo 의심 케이스 엄격 재검증."""
import json, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import anthropic

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
BATCH = 15
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


def call_api(items, system):
    resp = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=2048,
        system=[{'type':'text','text':system,'cache_control':{'type':'ephemeral'}}],
        messages=[{'role':'user','content':json.dumps(items, ensure_ascii=False)}],
    )
    cost = resp.usage.input_tokens*PRICE_IN + resp.usage.output_tokens*PRICE_OUT
    return parse(resp.content[0].text), cost


# 로드
rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass
print(f"전체: {len(rows)}행")

# ========================== is_title 엄격 재검증 ==========================
print("\n[A] is_title=True 전체 엄격 재검증")

TITLE_SYSTEM = """가정통신문의 제목인지 엄격하게 판정.

제목 = TRUE:
- 통신문의 표제 (예: "겨울방학 생활 안내", "운동회 개최 안내", "OO 모집")
- 헤드라인 형태, 통신문 전체 내용을 한 줄로 압축
- "제목 + 안녕하십니까?" 합쳐진 경우 OK

제목 아님 = FALSE:
- 교과 단원명 ("여러 가지 기체", "생물 분류하기", "1. 운동(운동) 건강의 뜻")
- 학칙 조항 ("제N조 ...")
- 학습 목표/활동 설명
- 강좌명 ("강좌명 석 달 후엔...")
- 표 헤더 ("내용 어떤 일?-사건과 이유")
- 학교 슬로건 ("HAPPY & SAFE SCHOOL", "공간감각 쑥쑥!")
- 본문 첫 문장 ("본교에서는 ...을 실시합니다")
- 일자/장소 정보 ("일시: ...", "장소: ...")

입력: [{"i":0,"text":"..."},...]
출력: [{"i":0,"is_title":true/false},...]
JSON 배열로만, 설명 없이."""

title_idx = [i for i, r in enumerate(rows) if r.get('is_title')]
print(f"  대상: {len(title_idx)}개")

n_b = (len(title_idx) + BATCH - 1) // BATCH
total_cost = 0
changed_title = 0
t0 = time.time()

for bi in range(n_b):
    bidx = title_idx[bi*BATCH : (bi+1)*BATCH]
    items = [{"i": i, "text": rows[oi]['text']} for i, oi in enumerate(bidx)]
    try:
        result, cost = call_api(items, TITLE_SYSTEM)
        total_cost += cost
        for item in result:
            if isinstance(item, dict) and 'i' in item:
                li = item['i']
                if 0 <= li < len(bidx):
                    oi = bidx[li]
                    new = bool(item.get('is_title', False))
                    if rows[oi]['is_title'] != new:
                        rows[oi]['is_title'] = new
                        changed_title += 1
    except Exception as e:
        print(f"    배치 {bi+1} 오류: {str(e)[:60]}", flush=True)

    if (bi+1) % 10 == 0 or bi == n_b-1:
        print(f"    {bi+1}/{n_b} | ${total_cost:.3f} | {time.time()-t0:.0f}s | False로 변경:{changed_title}", flush=True)

print(f"  is_title 변경 (True→False): {changed_title}")

# ========================== is_todo 의심 케이스 ==========================
print("\n[B] is_todo 의심 케이스 재검증")

# 의심 패턴: URL, 단원명, 짧은 정보, 표 헤더
url_re = re.compile(r'^https?://')
info_re = re.compile(r'^(일시|시간|장소|대상|기간|비용|금액|연락처)\s*[:：]')
unit_re = re.compile(r'^\d+\s*[가-힣]\d+-\d+|^\d+\.\s*[가-힣]+\([가-힣]+\)')

todo_idx = [i for i, r in enumerate(rows) if r.get('is_todo') and (
    url_re.search(r['text']) or
    info_re.match(r['text']) or
    unit_re.search(r['text']) or
    len(r['text']) < 8
)]
print(f"  대상: {len(todo_idx)}개")

TODO_SYSTEM = """가정통신문 문장이 학부모가 행동(제출/납부/준비/신청/참가/확인/작성)해야 하는 todo인지 엄격 판정.

is_todo = TRUE:
- 학부모가 직접 행동해야 하는 문장
- "제출해 주세요", "납부 바랍니다", "신청하세요" 등
- 폼 작성 필요 ("학년 반 이름:")
- 준비물 ("준비물: 도시락, 물병")
- 마감일 + 액션 ("4월 5일까지 제출")

is_todo = FALSE:
- 단순 정보 ("일시: 5월 28일", "장소: 부산문화회관")
- URL만 ("https://...")
- 교과 단원/학습목표
- 학칙 조항
- 표 헤더/구조 텍스트

입력: [{"i":0,"text":"..."},...]
출력: [{"i":0,"is_todo":true/false},...]
JSON 배열로만."""

n_b = (len(todo_idx) + BATCH - 1) // BATCH
changed_todo = 0
t0 = time.time()

for bi in range(n_b):
    bidx = todo_idx[bi*BATCH : (bi+1)*BATCH]
    items = [{"i": i, "text": rows[oi]['text']} for i, oi in enumerate(bidx)]
    try:
        result, cost = call_api(items, TODO_SYSTEM)
        total_cost += cost
        for item in result:
            if isinstance(item, dict) and 'i' in item:
                li = item['i']
                if 0 <= li < len(bidx):
                    oi = bidx[li]
                    new = bool(item.get('is_todo', False))
                    if rows[oi]['is_todo'] != new:
                        rows[oi]['is_todo'] = new
                        changed_todo += 1
    except Exception as e:
        print(f"    배치 {bi+1} 오류: {str(e)[:60]}", flush=True)

    if (bi+1) % 10 == 0 or bi == n_b-1:
        print(f"    {bi+1}/{n_b} | ${total_cost:.3f} | {time.time()-t0:.0f}s | 변경:{changed_todo}", flush=True)

print(f"  is_todo 변경: {changed_todo}")

# 저장
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

# 최종 통계
print(f"\n=== 최종 ===")
print(f"  비용: ${total_cost:.4f}")
print(f"  is_todo=True: {sum(1 for r in rows if r.get('is_todo'))}")
print(f"  is_title=True: {sum(1 for r in rows if r.get('is_title'))}")
