import requests, json, sys, urllib3
sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings()

BASE = 'https://data.nypi.re.kr/api/mcltAoePnlInfo'
SMALL_CATEGORIES = ['언어 능력', '자녀양육']

all_results = {}

for small in SMALL_CATEGORIES:
    params = {
        'ornuNm': '2기',
        'srvyYr': '2023',
        'rspnsMnbdNm': '학부모',
        'large': '다문화적 특성(▶[외국인 학부모]만)',
        'small': small,
        'pageNo': 1,
        'numOfRows': 200,
    }
    r = requests.get(BASE, params=params, timeout=15, verify=False)
    data = r.json()
    all_results[small] = data
    print(f'[{small}] totalCount={data["totalCount"]}, items={len(data["items"])}')

print()

# 언어 능력 데이터 상세 분석
lang_items = all_results['언어 능력']['items']

# 전체(svbnClsfCd=BANN020100)만 필터
total_items = [x for x in lang_items if x['svbnClsfCd'] == 'BANN020100']

print('=== 언어 능력 항목 목록 (전체 기준) ===')
seen_questions = {}
for item in total_items:
    qid = item['srvyQitemId']
    qnm = item['cbookQitemCn']
    rsp = item['rspnsNm']
    cnt = item['caseCnt']
    pct = item['freqRt']
    if qid not in seen_questions:
        seen_questions[qid] = qnm
        print(f'\n[{qid}] {qnm}')
    print(f'  응답={rsp}, 케이스={cnt}, 비율={pct}%')

print()
print('=== 전체 고유 설문 항목 ID ===')
for qid, qnm in seen_questions.items():
    print(f'  {qid}: {qnm}')

# JSON 파일로 저장
out_path = r'C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\Business_Plan\National_Key_Data\real_data_language.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)
print(f'\n데이터 저장: {out_path}')
