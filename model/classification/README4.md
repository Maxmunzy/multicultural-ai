# README.md
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\README.md

전체 파이프라인 (확정 버전)
[4] 카테고리 분류  (services/classifier.py — 경이님 6-class wrapper)
입력:  각 todo.text
출력:  category ∈ {일정, 준비물, 제출, 비용, 건강·안전, 기타}

- 카테고리 분류-경이님

`일정`, `준비물`, `제출`, `비용`, `건강·안전`, `기타`


- 가장 중요한 핵심과제: 모델 성능 비교 (베이스라인 VS. 파인튜닝)
1. 조건: 베이스라인 모델, 파인튜닝한 모델에 들어가는 input data가 동일한 데이터셋 및 동일한 조건에서 두 모델의 성능을 비교. 다시 말해서, 기존에 있던 모델을 가지고 동일한 조건을 맞춰서 일정, 준비물, 제출, 비용, 건강·안전, 기타에 대한 분류 성능 점수가 나와야하고 파인튜닝한 모델을 동일한 조건으로 6가지 분류 성능 점수가 나와야 비교가 가능. 그래서 파인튜닝된 모델이 베이스라인모델보다 성능이 좋다라는 지표가 나와야 성능의 우수함을 입증할 수 있음. 근거 자료를 만들어야 함. 

2. 두 모델(베이스라인 모델, 파인튜닝한 모델)에 들어가는 기존의 데이터는 답안지가 없기 때문에 accuracy가 아닌 그 모델의 맞는 평가 방식 및 성능 지표를 뽑아야 함. 그래서 자동라벨링(C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\scripts\auto_label_from_new_data_20260504.py)을 해서 notice_sample_v4_20260504.csv (C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\20260504\notice_sample_v4_20260504.csv) 696행 학습 데이터를 만들었다. 그러나 2026년 05월 05일에 받은 새로운 학습 데이터 notice_sample_v5_clean_full_20260504.csv (C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\notice_sample_v5_clean_full_20260504.csv) 5001행은 이미 라벨링이 존재함. 그래서 사용하고 있는 모델들의 적절한 평가 및 성능 지표가 나와야 함. 사용하고자 하는 모델 기능들의 자세한 설명 보기.

예시로, Precision이라고 하면 10개 단어 중에 2개 단어만 맞췄다. 그래서 그 모델로 해서 모든 텍스트 데이터 돌아서 몇 프로 맞췄으니까 얘는 성능이 얼마다 라고 얘기하는 것도 있다.

==> 파인튜닝의 성능이 베이스라인 성능보다 좋은 쪽으로 모델이 나와야하고 그 모델에 맞는 평가 지표가 나와야 한다. 글씨로 정리하는 것 뿐만아니라 시각적인 도구를 활용해서 그래프 혹은 직선 사용 등으로 제시할 근거 자료가 필요.

# README2.md
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\README2.md

# README3.md
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\README3.md

# docs 개발일지
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_2026-04-30.md
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_2026-04-30_실행결과.md
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_2026-05-02.md
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\docs\devlog_2026-05-04_자동라벨링.md

# data
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data
-중요: 새로운 학습 데이터 C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\notice_sample_v5_clean_full_20260504.csv --> 주어진 5001행 데이터를 가지고 학습 시켜야 함.

나머지는 기존 데이터

# scripts
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\scripts

# src
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\src

# notebooks
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks
-가상환경 설치 권장: tensorflow, torch
-C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\notebooks\03_train_kcelectra_v2_20260504 (1).ipynb 파일처럼 Colab GPU로 돌릴 수 있는 것은 주피터 노트북 형성해야 한다.