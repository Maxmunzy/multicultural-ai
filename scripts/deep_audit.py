"""rule_cleanup 후 잔여 이슈를 패턴별로 전수 분석."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict, Counter

INPUT = Path('model/extraction/data/v3_dual_labeled.jsonl')
OUT = Path('C:/Users/ashle/AppData/Local/Temp/deep_audit.txt')

rows = []
with open(INPUT, encoding='utf-8') as f:
    for l in f:
        if l.strip():
            try: rows.append(json.loads(l))
            except: pass

n = len(rows)
todos = [(i, r) for i, r in enumerate(rows) if r.get('is_todo')]
titles = [(i, r) for i, r in enumerate(rows) if r.get('is_title')]
both_f = [(i, r) for i, r in enumerate(rows) if not r.get('is_todo') and not r.get('is_title')]
both_t = [(i, r) for i, r in enumerate(rows) if r.get('is_todo') and r.get('is_title')]

print(f"전체: {n}")
print(f"is_todo=True: {len(todos)}")
print(f"is_title=True: {len(titles)}")
print(f"둘 다 False: {len(both_f)}")
print(f"둘 다 True: {len(both_t)}")

# ========== 1. is_todo=True 의심 패턴 전수 ==========
todo_issues = defaultdict(list)
for i, r in todos:
    text = r['text'].strip()
    L = len(text)

    # A. 슬로건 + 본문 머지 (HAPPY & SAFE, 모두가 행복한 등)
    if re.match(r'^(HAPPY\s*&\s*SAFE\s*SCHOOL|모두가 행복한|꿈을\s*키우며|공동체)', text):
        todo_issues['A_슬로건시작'].append((i, text))

    # B. "제목:" 접두사
    elif re.match(r'^제\s*목\s*[:：]', text):
        todo_issues['B_제목접두사'].append((i, text))

    # C. 일시/장소/대상 등 정보 안내 (액션 동사 없음)
    elif re.match(r'^(일시|시간|장소|대상|기간|비용|금액|연락처|주소|전화|문의|운영시간|모집인원|접수기간)\s*[:：]', text):
        if not re.search(r'(제출|납부|준비|신청|참가|확인|작성|동의|동봉|보내|회신|등록)', text):
            todo_issues['C_정보안내'].append((i, text))

    # D. 본문 머지 (300자 이상)
    elif L >= 300:
        todo_issues['D_본문머지300+'].append((i, text))

    # E. 학습 평가 키워드 ("관찰평가", "지필평가", "수행평가" 포함)
    elif re.search(r'(관찰평가|지필평가|수행평가|서술평가|실기\s*평가)', text):
        todo_issues['E_평가표현'].append((i, text))

    # F. 표 헤더/짧은 명사구 (10자 미만, 동사 없음)
    elif L < 10 and not re.search(r'(주세요|바랍니다|하세요|기를|드립니다|니다)', text):
        if not re.search(r'(제출|납부|준비|신청|참가|확인|작성|동봉)', text):
            todo_issues['F_짧은명사구'].append((i, text))

    # G. 인사말/맺음말만 단독
    elif re.match(r'^(안녕|반갑|감사|고맙|행복|건강).{0,30}(니까\??|세요\??|드립니다\.?|기원합니다\.?)\s*$', text) and L < 40:
        todo_issues['G_인사말'].append((i, text))

    # H. 학교명/날짜만
    elif re.match(r'^\d{4}[\.\s년]', text) and L < 30:
        todo_issues['H_날짜시작'].append((i, text))

# ========== 2. is_title=True 의심 패턴 전수 ==========
title_issues = defaultdict(list)
for i, r in titles:
    text = r['text'].strip()
    L = len(text)

    # A. 슬로건 시작 (HAPPY & SAFE SCHOOL, 모두가 행복한)
    if re.match(r'^(HAPPY\s*&\s*SAFE\s*SCHOOL|모두가 행복한|공동체|꿈을 키우며)', text):
        title_issues['A_슬로건시작'].append((i, text))

    # B. "제목:" 접두사
    elif re.match(r'^제\s*목\s*[:：]', text):
        title_issues['B_제목접두사'].append((i, text))

    # C. 본문/표 머지 (150자 이상)
    elif L > 150:
        title_issues['C_본문머지150+'].append((i, text))

    # D. 학교명/날짜 시작 (예: "2025. 3. 31. 검 단 초 등 학 교 장 ...")
    elif re.match(r'^\d{4}[\.\s년]', text) and re.search(r'학\s*교\s*장', text):
        title_issues['D_학교장명시'].append((i, text))

    # E. 짧은 캠페인 슬로건 (느낌표 끝, 안내/모집 없음)
    elif L < 20 and re.search(r'!\s*$', text):
        if not re.search(r'(안내|모집|개최|공고)', text):
            title_issues['E_슬로건'].append((i, text))

    # F. 5자 이하 (너무 짧음)
    elif L <= 5:
        title_issues['F_초단축'].append((i, text))

    # G. 회차/번호 시작 (예: "16. 3학년 ...", "35. 17. ...")
    elif re.match(r'^\d+[\.,]\s*\d+[\.,]', text):
        title_issues['G_중복번호'].append((i, text))

# ========== 3. 둘 다 False 인데 todo/title 가능성 (False Negative) ==========
fn_todo_candidates = []
fn_title_candidates = []
for i, r in both_f:
    text = r['text'].strip()
    L = len(text)
    # 명백 todo 누락 후보
    if re.search(r'(제출해\s*주|납부\s*바랍|신청\s*바랍|참가\s*신청|동의서를\s*작성|회신\s*바랍|작성하여\s*제출)', text):
        fn_todo_candidates.append((i, text))
    # 명백 title 누락 후보 (안내/모집/공고로 끝나면서 짧음)
    if 10 <= L <= 50 and re.search(r'(안내$|모집\s*안내$|개최\s*안내$|공고$|실시\s*안내$)', text):
        fn_title_candidates.append((i, text))

# ========== 4. 둘 다 True 전수 ==========
# (이미 plot)

# ========== 출력 ==========
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(f"전체: {n} | todo={len(todos)} | title={len(titles)} | 둘다T={len(both_t)}\n\n")

    f.write("=" * 70 + "\n")
    f.write("[is_todo=True 잔여 의심]\n")
    f.write("=" * 70 + "\n")
    for cat in sorted(todo_issues.keys()):
        items = todo_issues[cat]
        f.write(f"\n--- {cat}: {len(items)}건 ---\n")
        for i, t in items[:50]:
            f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
        if len(items) > 50:
            f.write(f"  ... +{len(items)-50}건 더\n")

    f.write("\n\n" + "=" * 70 + "\n")
    f.write("[is_title=True 잔여 의심]\n")
    f.write("=" * 70 + "\n")
    for cat in sorted(title_issues.keys()):
        items = title_issues[cat]
        f.write(f"\n--- {cat}: {len(items)}건 ---\n")
        for i, t in items[:50]:
            f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
        if len(items) > 50:
            f.write(f"  ... +{len(items)-50}건 더\n")

    f.write("\n\n" + "=" * 70 + "\n")
    f.write("[False Negative 후보 (둘 다 False인데 todo/title일 듯)]\n")
    f.write("=" * 70 + "\n")
    f.write(f"\n--- todo 누락 후보: {len(fn_todo_candidates)}건 ---\n")
    for i, t in fn_todo_candidates[:50]:
        f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
    if len(fn_todo_candidates) > 50:
        f.write(f"  ... +{len(fn_todo_candidates)-50}건 더\n")
    f.write(f"\n--- title 누락 후보: {len(fn_title_candidates)}건 ---\n")
    for i, t in fn_title_candidates[:50]:
        f.write(f"  {i}: [{len(t)}자] {t[:120]}\n")
    if len(fn_title_candidates) > 50:
        f.write(f"  ... +{len(fn_title_candidates)-50}건 더\n")

    f.write("\n\n" + "=" * 70 + "\n")
    f.write(f"[둘 다 True {len(both_t)}건 전체]\n")
    f.write("=" * 70 + "\n")
    for i, r in both_t:
        f.write(f"  {i}: [{len(r['text'])}자] {r['text'][:120]}\n")

# 콘솔에 요약
print("\n=== is_todo 잔여 의심 ===")
for cat in sorted(todo_issues.keys()):
    print(f"  {cat}: {len(todo_issues[cat])}건")
print("\n=== is_title 잔여 의심 ===")
for cat in sorted(title_issues.keys()):
    print(f"  {cat}: {len(title_issues[cat])}건")
print(f"\n=== False Negative 후보 ===")
print(f"  todo 누락: {len(fn_todo_candidates)}건")
print(f"  title 누락: {len(fn_title_candidates)}건")
print(f"\n둘 다 True: {len(both_t)}건")
print(f"\n→ {OUT}")
