# 각각의 목적이 다른 두가지 방법의 베이스라인
베이스라인은 보통 “내가 만든 고급 모델이 정말 필요한가?”를 증명하기 위한 가장 단순하고 합리적인 기준 모델이며 ML에서 baseline은 무엇을 증명하려고 하느냐에 따라 의미가 달라짐.

1. 메인비교의 목적 Simple (TF-IDF + LogReg) vs KcELECTRA v3_2 
목적: "왜 굳이 무겁고 비용이 드는 딥러닝(트랜스포머) 모델을 써야 하는가?"에 대한 당위성 증명 (Global Baseline) VS. 딥러닝(트랜스포머) --> 최종 성능 입증용이며 투자 및 아키텍처 정당화

실무에서 새로운 AI 모델을 도입할 때 가장 먼저 받는 질문은 "그냥 간단한 머신러닝 돌리면 안 돼?"입니다.
TF-IDF와 Logistic Regression은 가볍고, 빠르며, 연산 비용이 거의 들지 않는 전통적인 자연어 처리(NLP) 기법입니다. 이것을 글로벌 베이스라인(최소한의 기준점)으로 삼는 것은 AI 업계의 표준 방식.
==> 의사결정자 설득용으로 활용


2. 탐색 과정 추적: v1→v2→v3 추이
목적: "모델 성능을 높이기 위해 어떤 최적화(Tuning)를 거쳤는가?"에 대한 증명 (Iterative/Experimental Baseline) --> “튜닝 과정/개선 이력”

여기서 말하는 v1은 실험적 베이스라인입니다. "트랜스포머 모델을 가져와서 아무런 튜닝 없이(혹은 초기 설정으로) 돌렸을 때"의 성능을 기준으로 잡고, 이후 진행한 실험들이 얼마나 유효했는지 보여줍니다.

단, 각 버전에서 정확히 무엇이 바뀌었는지 명시해야 합니다 (모델 크기, LR, 데이터 양 모두)
결론: "v3가 최적 설정이라는 것을 체계적 탐색으로 도달했다"
이건 "파인튜닝 효과 증명"이 아니라 "우리의 의사결정 과정이 합리적이었다"는 의미로 포지셔닝.

참고파일 :
1. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\01_train_kcelectra_v1_2_20260430.ipynb
2. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\03_train_kcelectra_v2_2_20260509.ipynb
3. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\12_train_kcelectra_v3_2_20260509.ipynb

4. 
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\02_evaluate_compare_v1_2_20260430.ipynb
5. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\04_visualize_comparison_v2_2_20260509.ipynb
6. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\13_visualize_comparison_v3_2_20260509.ipynb

7. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\20260509

8. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\20260503

9. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\20260430
-------------------------------------------------------------------------------------------------

# 담당 기능 설명: 
카테고리 분류 담당-경이님
6개 카테고리 {`일정`, `준비물`, `제출`, `비용`, `건강·안전`, `기타`}

# 입력/ 처리/ 출력 구조: 
데이터 입력 관련 참고 파일: 
1. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\20260509\notice_sample_v6_2_20260509.csv
2. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\split_v3_1_20260509.csv
3. 
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\scripts\auto_label_from_new_data_20260504.py
4. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\scripts\auto_label_categories_v5_full.py
5. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_2026-05-04_자동라벨링.md


# 사용모델/구현 방식: - 핵심 기능:
참고 파일: 
1. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\01_train_kcelectra_v1_2_20260430.ipynb
2. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\03_train_kcelectra_v2_2_20260509.ipynb
3. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\12_train_kcelectra_v3_2_20260509.ipynb

# 정량 지표: -accuracy보다 macro F1 지표를 왜 사용했는지.
참고 파일: 
1. 
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\02_evaluate_compare_v1_2_20260430.ipynb
2. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\04_visualize_comparison_v2_2_20260509.ipynb
3. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\13_visualize_comparison_v3_2_20260509.ipynb

# 성공 사례: 
1. 파인튜닝된 Kcelectra 모델이 베이스 모델보다 성능이 좋다는것을 입증. 맨 위에 제시된 # 각각의 목적이 다른 두가지 방법의 베이스라인 내용 보고 참조.

# 실패 사례: 
참고 파일:
1. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_2026-05-04_자동라벨링.md
2. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_20260510.md

# 한계와 향후 개선점:
참고 파일:
1. C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_20260510.md
