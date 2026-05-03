"""dual_label_full 진단 — 5배치 raw 응답 출력."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import anthropic

api_key = None
for line in Path('backend/.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        api_key = line.split('=', 1)[1].strip()
client = anthropic.Anthropic(api_key=api_key)

# 동일한 system prompt
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

JSON 배열로만, 설명 없이.
예: [[false, true], [true, false], ...]"""

# 입력 데이터 로드
rows = []
with open('model/extraction/data/v3_school_split_fixed_v2.jsonl', encoding='utf-8', errors='replace') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

# 5배치 (150행) 테스트
for bi in range(5):
    batch = rows[bi*20 : (bi+1)*20]
    texts = [r['text'] for r in batch]

    print(f"\n{'='*80}")
    print(f"=== 배치 {bi+1} ===")
    print(f"{'='*80}")

    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2048,
            system=[{'type':'text','text':SYSTEM,'cache_control':{'type':'ephemeral'}}],
            messages=[{'role':'user','content':json.dumps(texts, ensure_ascii=False)}],
        )
        raw = resp.content[0].text

        print(f"입력 토큰: {resp.usage.input_tokens}")
        print(f"출력 토큰: {resp.usage.output_tokens}")
        print(f"max_tokens: 2048")
        print(f"응답 길이: {len(raw)}자")
        print(f"\n--- RAW 응답 (처음 500자) ---")
        print(raw[:500])
        print(f"\n--- RAW 응답 (마지막 200자) ---")
        print(raw[-200:])

        # 파싱 시도
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        try:
            labels = json.loads(cleaned)
            print(f"\n✅ 파싱 성공 — {len(labels)}개 라벨 (입력 {len(texts)}개)")
            if len(labels) != len(texts):
                print(f"⚠️  개수 불일치!")
        except Exception as e:
            print(f"\n❌ 파싱 실패: {e}")

    except Exception as e:
        print(f"❌ API 오류: {e}")
