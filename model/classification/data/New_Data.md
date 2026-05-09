# 첫번째 v4_merged_train.jsonl파일에서 "is_todo": true만 데이터를 가져온다.
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\extraction\data\train\v4_merged_train.jsonl

# 두번째 is_todo_label.py 아래 파일은 is_todo에 왜 True 또는 False를 줬는지에 대한 근거이다. 이를 참고한다.
C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\extraction\file\is_todo_label.py

# 세번째 결과: notice_sample_v5_clean_full_20260504.csv (C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\data\20260505\notice_sample_v5_clean_full_20260504.csv)와 같은 형식으로 나와야 한다. 
다시말해서, 두번째에 이어서 scripts 폴더: C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\scripts 에서 notice_sample_v5_clean_full_20260504.csv와 같은 결과물을 만들어 줄 수 있는 파일을 찾고  
"text" <-- 첫번째 v4_merged_train.jsonl파일에서 "is_todo": true만 
"category" <-- text가 6가지 분류 {"일정", "준비물", "제출", "비용", "건강·안전", "기타"}중에서 가장 적절한 분류 하나만 정한다. 결국,  notice_sample_v5_clean_full_20260504.csv 형식처럼 나와야 한다. 