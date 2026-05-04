# 윤정님(2026년 05월 04일):

-새로운 데이터 추가
model/extraction/data/train/test_data.jsonl    모델 통과 전 — {text, is_todo} 5,560행
data/processed/predict_output_testset.jsonl    모델 통과 후 — {text, source, due_date, amount, confidence, action_hint, true_is_todo} 5,330행 (정규식 필터 제외 230행)

##  로컬에서 비교 평가 실행

(ai_env) C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification>python scripts/evaluate_compare_v2_20260504.py
평가 시작 — split: test, 데이터: v4_20260504

[Simple] 분류 리포트
              precision    recall  f1-score   support

          일정       0.79      0.85      0.81        13
         준비물       0.86      0.75      0.80         8
          제출       0.69      0.69      0.69        13
          비용       1.00      0.90      0.95        10
       건강·안전       0.75      0.82      0.78        11
          기타       0.71      0.71      0.71        14

    accuracy                           0.78        69
   macro avg       0.80      0.79      0.79        69
weighted avg       0.79      0.78      0.78        69

[kcelectra] 기존 JSON 재활용: eval_results_kcelectra_20260504.json

[저장] eval_results_simple_20260504.json
[저장] eval_results_kcelectra_20260504.json
[저장] eval_comparison_summary_20260504.csv

==================================================
  성능 비교 결과
==================================================
  Simple    Macro F1 : 0.7919
  KcELECTRA Macro F1 : 0.6938
  Delta              : -0.0981
  >> Simple 유지 권장
