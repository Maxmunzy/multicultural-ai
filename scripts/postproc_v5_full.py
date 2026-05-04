"""v5_full csv 후처리 — 검증에서 발견한 명백 오라벨 패턴 정리.

룰 (false positive 최소화):
  R1. 준비물 → none: 학습 syllabus 본문 ("교 재" + "주 주제" + "비고" 다 있음)
  R2. 준비물 → 기타: 단말기 등록·앱 설치 안내
  R3. 준비물 → 제출: 구비서류·지원서·재직증명서·취학통지서
  R4. 준비물 → 건강·안전: 예방접종 수첩 지참, 마스크 착용 등교
  R5. 기타 → 건강·안전: 아동학대 신고·학교폭력 대처 패턴
  R6. 기타 → none: 단순 인사·감사·메타 (15자 내외 짧은 줄)

출력:
  - model/classification/data/notice_sample_v5_clean_full_20260504.csv
  - model/classification/data/v5_postproc_changes_20260504.csv (변경 로그)
"""
import csv, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import Counter, defaultdict

INPUT = Path('model/classification/data/notice_sample_v5_full_20260504.csv')
OUTPUT = Path('model/classification/data/notice_sample_v5_clean_full_20260504.csv')
CHANGES = Path('model/classification/data/v5_postproc_changes_20260504.csv')

# === 룰 정의 ===

def classify_change(text, current):
    """현재 카테고리에서 다른 카테고리(또는 'none' = 제거)로 옮길지 판단."""
    t = text

    # R1. 준비물 → none: 학습 syllabus 본문
    if current == '준비물':
        if ('교 재' in t or '교재명 :' in t) and '준비사항' in t and ('주 주제' in t or '비고' in t):
            return 'none', 'R1_syllabus'
        if ('로블록스 스튜디오 설치' in t) or ('메타버스' in t and ('스튜디오' in t or '플레이스' in t)):
            return 'none', 'R1_syllabus'

    # R2. 준비물 → 기타: 단말기/앱 설치
    if current == '준비물':
        # 단말기 관련
        if '단말기' in t and re.search(r'(가방|등록|부착|착용|수령)', t):
            return '기타', 'R2_device'
        # 앱/소프트웨어 설치
        if re.search(r'(키즈콜|T안심알리미|안심존|그린아이넷|안전Dream|디비디비스쿨|e알리미|마인크래프트\s*에듀케이션)', t) and re.search(r'(설치|다운로드|검색)', t):
            return '기타', 'R2_app'
        # ZOOM 설치 (학습용 줌 본문 제외 — 이미 R1에서 잡힘)
        if re.search(r'(ZOOM|Zoom Cloud Meetings|줌\(zoom\))', t) and re.search(r'(설치|다운로드)', t) and not ('주 주제' in t or '비고' in t):
            return '기타', 'R2_zoom'
        # 사이버안심존/스마트안심드림 등 부모 설치
        if re.search(r'(사이버안심존|스마트안심드림|모바일펜스|구글\s*패밀리|블렌더3D|마인크래프트)', t) and '다운로드' in t:
            return '기타', 'R2_app'

    # R3. 준비물 → 제출: 구비서류
    if current == '준비물':
        if re.search(r'구비\s*서류', t):
            return '제출', 'R3_documents'
        if t.strip() in {'맞벌이: 재직증명서', '한부모가정: 주민센터 발급증명서(가족관계증명서 등)'}:
            return '제출', 'R3_documents'
        if re.search(r'주민센터.*납입.*관련', t) or '저소득층: 주민센터' in t:
            return '제출', 'R3_documents'
        if '지원서 사진' in t and '첨부' in t:
            return '제출', 'R3_documents'
        if '동사무소에서 발부한 취학통지서' in t:
            return '제출', 'R3_documents'
        # 작품 출품 양식 (서식, 작품설명서 등)
        if re.search(r'서식\d+\s*작품', t) or '작품설명서 작성' in t or '면담\s*심사' in t and '준비' in t:
            return '제출', 'R3_documents'
        if '작품 시연 준비' in t or '연구과정 포트폴리오' in t:
            return '제출', 'R3_documents'

    # R4. 준비물 → 건강·안전
    if current == '준비물':
        if '예방접종 수첩' in t and '지참' in t:
            return '건강·안전', 'R4_health'
        # "등교시 마스크 착용" 단독
        if re.match(r'^[\s\d.]*등교\s*시?\s*마스크\s*착용', t.strip()) and len(t) < 50:
            return '건강·안전', 'R4_health'

    # R5. 기타 → 건강·안전
    if current == '기타':
        # 아동학대 신고 패턴
        if '신고 시' in t and re.search(r'(아동|신고자|학대행위자)', t):
            return '건강·안전', 'R5_safety_reporting'
        # "아동학대 신고:" 시작
        if t.strip().startswith('아동학대 신고:'):
            return '건강·안전', 'R5_safety_reporting'
        # 학교폭력 대처 단계 ("1) 보복하지 마세요" 등 짧은 단계)
        if re.match(r'^\s*\d+\)\s*(보복하지|부인하지|잘못을\s*인정|정당화하지|포기하지|진심으로\s*사과)', t):
            return '건강·안전', 'R5_violence_steps'

    # R6. 기타 → none: 단순 인사·감사·메타
    if current == '기타':
        stripped = t.strip()
        if len(stripped) < 30:
            if re.search(r'(감사드립니다|환영합니다|기원합니다|발송해\s*드리겠습니다|공지해\s*드립니다)', stripped):
                return 'none', 'R6_meta'

    return None, None


# === 실행 ===

with open(INPUT, encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))

n_total = len(rows)
new_rows = []
changes = []
rule_counts = Counter()
move_matrix = defaultdict(lambda: Counter())

for i, r in enumerate(rows):
    text = r['text']
    current = r['category']
    new_cat, rule = classify_change(text, current)
    if new_cat is None:
        new_rows.append(r)
        continue
    rule_counts[rule] += 1
    move_matrix[current][new_cat] += 1
    changes.append({'row_idx': i, 'text': text, 'before': current, 'after': new_cat, 'rule': rule})
    if new_cat == 'none':
        # 제거
        continue
    new_rows.append({'text': text, 'category': new_cat})

# 출력 csv (v4 양식)
with open(OUTPUT, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f, quoting=csv.QUOTE_ALL)
    w.writerow(['text', 'category'])
    for r in new_rows:
        w.writerow([r['text'], r['category']])

# 변경 로그
with open(CHANGES, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['row_idx', 'before', 'after', 'rule', 'text'], quoting=csv.QUOTE_ALL)
    w.writeheader()
    for c in changes:
        w.writerow(c)

print(f"=== 후처리 결과 ===")
print(f"입력: {n_total}행")
print(f"출력: {len(new_rows)}행 (제거: {n_total - len(new_rows)}건)")
print()
print(f"=== 룰별 적용 ===")
for rule, n in sorted(rule_counts.items()):
    print(f"  {rule}: {n}건")
print()
print(f"=== 이동 매트릭스 ===")
for src, tgts in move_matrix.items():
    for tgt, n in tgts.items():
        print(f"  {src} → {tgt}: {n}건")
print()

# 분포 비교
old_dist = Counter(r['category'] for r in rows)
new_dist = Counter(r['category'] for r in new_rows)
print(f"=== 카테고리 분포 변화 ===")
print(f"  cat       before     after     diff")
for cat in ['일정','준비물','제출','비용','건강·안전','기타']:
    diff = new_dist.get(cat, 0) - old_dist.get(cat, 0)
    sign = '+' if diff >= 0 else ''
    print(f"  {cat:<8} {old_dist.get(cat,0):>8}  {new_dist.get(cat,0):>8}  {sign}{diff}")
print()
print(f"파일: {OUTPUT.name}")
print(f"변경 로그: {CHANGES.name}")
