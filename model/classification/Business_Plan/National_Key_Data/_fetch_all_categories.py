import requests, json, sys, urllib3
sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings()

BASE = 'https://data.nypi.re.kr/api/mcltAoePnlInfo'

# SchoolBridge 관련 전체 카테고리
TARGETS = [
    ('다문화적 특성(▶[외국인 학부모]만)', '언어 능력'),
    ('다문화적 특성(▶[외국인 학부모]만)', '문화 적응'),
    ('자녀양육', '자녀교육 및 양육'),
    ('자녀양육', '양육 관련 특성'),
    ('자녀양육', '자녀 진학/진로 및 향후 희망 거주'),
    ('개인요인', '심리사회적응 및 건강'),
    ('다문화 지원 정책', '지원정책 태도'),
    ('배경 변인', '보호자 특성'),
]

all_data = {}

for large, small in TARGETS:
    r = requests.get(BASE, params={
        'ornuNm': '2기', 'srvyYr': '2023', 'rspnsMnbdNm': '학부모',
        'large': large, 'small': small,
        'pageNo': 1, 'numOfRows': 300,
    }, timeout=15, verify=False)
    d = r.json()
    total = d.get('totalCount', 0)
    items = d.get('items', [])
    key = f'{large} > {small}'
    all_data[key] = items
    print(f'[{key}] {total}건')

    # 전체(svbnClsfCd=BANN020100) 항목만 출력
    total_items = [x for x in items if x.get('svbnClsfCd') == 'BANN020100']

    # 고유 설문 항목별 요약
    seen = {}
    for item in total_items:
        qid = item['srvyQitemId']
        if qid not in seen:
            seen[qid] = {'question': item['cbookQitemCn'], 'responses': []}
        seen[qid]['responses'].append(
            f'{item["rspnsNm"]} ({item["caseCnt"]}명, {item["freqRt"]}%)'
        )

    for qid, info in seen.items():
        print(f'  [{qid}] {info["question"]}')
        for resp in info['responses']:
            print(f'    - {resp}')
    print()

# 전체 저장
out = r'C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\Business_Plan\National_Key_Data\real_data_all_categories.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(all_data, f, ensure_ascii=False, indent=2)
print(f'저장 완료: {out}')
