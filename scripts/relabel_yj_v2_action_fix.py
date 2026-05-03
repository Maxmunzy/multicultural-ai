"""relabel_yunjeong_def 후 잘못 잡힌 일반 closing 액션을 False로 되돌림.

윤정님 sample은 구체 액션만 todo, 일반 closing은 false:
- "양해 부탁드립니다" / "관심 부탁드립니다" / "협조해 주시길 부탁드립니다" / "감사드립니다" / "기원합니다" → False
- 구체 대상/날짜/방법 있는 액션 → True 유지
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
DIFF = Path('C:/Users/ashle/AppData/Local/Temp/relabel_yj_v2_diff.txt')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

before_todo = sum(1 for r in rows if r.get('is_todo'))


# ============== 일반 closing 패턴 (todo 아님) ==============

# 명백한 closing/감사/기원/양해 (구체 액션 X)
CLOSING_PATTERNS = [
    re.compile(r'^.{0,80}(감사드립니다|감사합니다|감사를?\s*드립니다)\.?$'),
    re.compile(r'^.{0,80}(기원합니다|기원드립니다|기원드리며)\.?$'),
    re.compile(r'^.{0,80}양해\s*(부탁|바랍|하여\s*주)'),
    re.compile(r'^.{0,150}(관심|협조|참여|성원|격려|이해|동참|배려|응원)\s*(과|와|을|를|이|가|에)?\s*(많이|적극적인|지속적인|꾸준한|꾸준히|항상|늘|언제나)?\s*(부탁드립니다|바랍니다|부탁\s*드립니다|드립니다)\.?$'),
    re.compile(r'^.{0,80}(많은|적극적인|지속적인|꾸준한|항상|늘|언제나)\s*(관심|협조|참여|성원|격려|이해|동참|배려|응원).*?(부탁드립니다|바랍니다|드립니다)\.?$'),
    re.compile(r'^.{0,80}(되시기를?|되길|되도록).{0,30}(바랍니다|기원|부탁)'),
    re.compile(r'^.{0,80}(행복|건강|평안|안녕)(이|을|을\s*기원).{0,40}(바랍니다|드립니다|기원).*?\.?$'),
]


def is_general_closing(text):
    for p in CLOSING_PATTERNS:
        if p.search(text):
            return True
    return False


# ============== 명백 정보가 아닌 false positive 룰 ==============

# 학교 일반 연락처 (todo 아님 — 윤정님 sample 118번)
SCHOOL_CONTACT_RE = re.compile(r'(주소|전화|☎|http|www\.).*?\d')


def is_school_contact(text):
    """학교 자체 연락처 단독 행 (참가/문의처 같은 todo는 제외)"""
    if re.match(r'^전화\s*[:：]', text) and len(text) < 25 and not re.search(r'(문의|연락|신청|예약)', text):
        return True
    if re.match(r'^\(\d{4,5}\)\s', text):  # "(48092) 부산..."
        return True
    return False


# ============== 적용 ==============
changed_to_false = []

for i, r in enumerate(rows):
    if not r.get('is_todo'):
        continue
    text = r['text'].strip()

    # 일반 closing → False
    if is_general_closing(text):
        rows[i]['is_todo'] = False
        changed_to_false.append(('closing', i, text))
        continue

    # 학교 자체 연락처 → False
    if is_school_contact(text):
        rows[i]['is_todo'] = False
        changed_to_false.append(('학교연락처', i, text))
        continue


# 저장
with open(INPUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

with open(DIFF, 'w', encoding='utf-8') as f:
    f.write(f"=== 추가 True→False ({len(changed_to_false)}건) ===\n\n")
    by_cat = {}
    for cat, i, t in changed_to_false:
        by_cat.setdefault(cat, []).append((i, t))
    for cat, items in by_cat.items():
        f.write(f"\n[{cat}] {len(items)}건\n")
        for i, t in items[:80]:
            f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
        if len(items) > 80:
            f.write(f"  ... +{len(items)-80}건 더\n")

after_todo = sum(1 for r in rows if r.get('is_todo'))
print(f"True→False: {len(changed_to_false)}건")
by_cat = {}
for cat, _, _ in changed_to_false:
    by_cat[cat] = by_cat.get(cat, 0) + 1
for cat, n in by_cat.items():
    print(f"  {cat}: {n}건")
print(f"\nis_todo: {before_todo} → {after_todo}")
print(f"diff: {DIFF}")
