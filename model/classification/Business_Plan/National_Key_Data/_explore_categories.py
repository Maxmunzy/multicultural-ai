import requests, json, sys, urllib3
sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings()

BASE = 'https://data.nypi.re.kr/api/mcltAoePnlInfo'

# 스크린샷에서 확인된 대분류 목록
LARGE_CATS = [
    '개인요인',
    '다문화 지원 정책',
    '다문화적 특성(▶[외국인 학부모]만)',
    '배경 변인',
    '자녀양육',
    '패널관리',
]

# SchoolBridge 관련 소분류 후보
SMALL_GUESSES = [
    # 다문화적 특성 하위
    '언어 능력', '이중문화 경험', '이중문화 수용태도', '문화 정체성', '이중문화',
    '이중 문화', '정체성', '문화적응',
    # 학교 관련
    '학교생활', '학교 생활', '자녀 학교', '학교참여', '학교 참여',
    '교육참여', '교육 참여', '학부모 참여', '학교 관련',
    # 자녀양육
    '자녀 교육', '자녀교육', '자녀 학교생활', '양육 태도', '자녀 관계',
    # 부모-자녀 관계
    '부모-자녀 관계', '부모자녀 관계', '부모 자녀', '자녀 관계', '부모 관계',
    # 진로
    '진로', '자녀 진로', '진로 지원',
    # 정보 관련
    '정보 접근', '정보접근', '정보격차', '사회적 지지',
]

print('=== 대분류별 데이터 탐색 ===')
print()

results = {}

for large in LARGE_CATS:
    # 소분류 없이 대분류만으로 조회 (모든 소분류 포함)
    r = requests.get(BASE, params={
        'ornuNm': '2기', 'srvyYr': '2023', 'rspnsMnbdNm': '학부모',
        'large': large, 'pageNo': 1, 'numOfRows': 1
    }, timeout=12, verify=False)

    try:
        d = r.json()
        total = d.get('totalCount', 0)
        print(f'[{large}] 총 {total}건')

        if total > 0:
            # 소분류별로 세분화 탐색
            found_smalls = set()
            r2 = requests.get(BASE, params={
                'ornuNm': '2기', 'srvyYr': '2023', 'rspnsMnbdNm': '학부모',
                'large': large, 'pageNo': 1, 'numOfRows': 200
            }, timeout=12, verify=False)
            items = r2.json().get('items', [])
            for item in items:
                cat = item.get('otptCtgryNm', '')
                # 소분류 추출 (대분류-소분류-세분류 구조)
                parts = cat.split('-')
                if len(parts) >= 2:
                    small = parts[1].strip()
                    found_smalls.add(small)
            print(f'  소분류: {sorted(found_smalls)}')
            results[large] = sorted(found_smalls)
        else:
            results[large] = []
    except Exception as e:
        print(f'  오류: {e}')

print()
print('=== SchoolBridge 관련 소분류 직접 탐색 ===')
for small in SMALL_GUESSES:
    r = requests.get(BASE, params={
        'ornuNm': '2기', 'srvyYr': '2023', 'rspnsMnbdNm': '학부모',
        'small': small, 'pageNo': 1, 'numOfRows': 1
    }, timeout=10, verify=False)
    try:
        d = r.json()
        total = d.get('totalCount', 0)
        if total > 0:
            print(f'  [HIT] small={small!r}: {total}건')
    except:
        pass

# 결과 저장
with open(r'C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\Business_Plan\National_Key_Data\category_map.json',
          'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print()
print('카테고리 맵 저장 완료')
