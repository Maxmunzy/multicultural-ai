"""is_title=True 전체 + is_todo 의심 케이스 전체 dump."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('model/extraction/data/v3_dual_labeled.jsonl', encoding='utf-8') as f:
    rows = [json.loads(l) for l in f if l.strip()]

# 1. is_title=True 전체 dump
titles = [(i, r) for i, r in enumerate(rows) if r.get('is_title')]
with open('C:/Users/ashle/AppData/Local/Temp/all_titles.txt', 'w', encoding='utf-8') as f:
    f.write(f"=== is_title=True 전체 {len(titles)}개 ===\n\n")
    for idx, (i, r) in enumerate(titles, 1):
        td = ' [+todo]' if r.get('is_todo') else ''
        f.write(f"{idx:4d}. [{len(r['text']):>4}자]{td} {r['text']}\n")

print(f"is_title 770개 → all_titles.txt 저장")

# 2. is_todo=True 의심 패턴 전체 dump
todo_suspicious_patterns = [
    ('URL', re.compile(r'^https?://')),
    ('정보(:로 시작)', re.compile(r'^(일시|시간|장소|대상|기간|비용|금액|연락처|주소|전화)\s*[:：]')),
    ('교과/단원', re.compile(r'\d+[가-힣]\d+-\d+|^\d+\.\s*[가-힣]+\s*\(')),
    ('학습 활동', re.compile(r'(만들기|찾아보기|발표하기|이해하기|학습하기|평가하기)$')),
    ('짧은 토막', None),  # 길이 기반
    ('학칙 조항', re.compile(r'^제\d+조|^제\d+장')),
    ('표 헤더', re.compile(r'^(연번|번호|구분|항목|성명|이름|내용)\s*$')),
]

todos = [(i, r) for i, r in enumerate(rows) if r.get('is_todo')]
suspicious_todos = []
for idx, r in todos:
    text = r['text']
    matched = []
    for name, pat in todo_suspicious_patterns:
        if name == '짧은 토막':
            if len(text) < 8:
                matched.append(name)
        elif pat.search(text):
            matched.append(name)
    if matched:
        suspicious_todos.append((idx, r, matched))

with open('C:/Users/ashle/AppData/Local/Temp/suspicious_todos.txt', 'w', encoding='utf-8') as f:
    f.write(f"=== is_todo=True 의심 케이스 전체 {len(suspicious_todos)}개 ===\n\n")
    for idx, (i, r, matched) in enumerate(suspicious_todos, 1):
        f.write(f"{idx:4d}. [{','.join(matched)}] [{len(r['text'])}자] {r['text']}\n")

print(f"is_todo 의심 {len(suspicious_todos)}개 → suspicious_todos.txt 저장")
