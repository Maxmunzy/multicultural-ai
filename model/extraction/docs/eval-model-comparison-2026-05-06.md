# 모델 성능 비교 — Base vs v2 vs v3

**작성일**: 2026-05-06  
**담당**: 윤정  
**브랜치**: `feature/yunjeong-extraction-v5`

---

## 평가 목적

학습되지 않은 데이터에서 Base 모델, v2 Fine-tuned, v3 Fine-tuned의 이진 분류 성능을 비교한다.

---

## 테스트셋 구성

| 항목 | 내용 |
|------|------|
| 파일 | `data/train/test_data.jsonl` |
| 출처 | `v3_dual_labeled_clean.jsonl`의 20% stratified val split (random_state=42) |
| 재현 방법 | `train_test_split(test_size=0.2, random_state=42, stratify=labels)` |
| 총 문장 수 | 5,560개 |
| is_todo True | 1,554개 (28.0%) |
| is_todo False | 4,006개 (72.0%) |

### 각 모델에 대한 테스트셋 성격

| 모델 | 이 데이터와의 관계 |
|------|-----------------|
| Base 모델 | 완전 unseen |
| v2 Fine-tuned | 완전 unseen (v2는 갈산초 데이터 `v2.1_notices_galsan.jsonl`로만 학습) |
| v3 Fine-tuned | val split — 학습 gradient에는 미사용, 모델 선택(load_best_model_at_end)에만 참여 |

---

## 평가 결과

### 전체 요약

| 모델 | Accuracy | F1 (할 일) | Precision (할 일) | Recall (할 일) |
|------|----------|-----------|-----------------|--------------|
| Base 모델 | 30.22% | 0.4396 | 0.2834 | 0.9794 |
| v2 Fine-tuned | 76.82% | 0.3905 | 0.7362 | 0.2658 |
| **v3 Fine-tuned** | **89.19%** | **0.8078** | **0.8029** | **0.8127** |
| v3 향상 폭 (v2 대비) | +12.37%p | +0.4173 | | |

### Base 모델

```
              precision    recall  f1-score   support

      노이즈(0)     0.8316    0.0394    0.0753      4006
      할 일(1)     0.2834    0.9794    0.4396      1554

    accuracy                         0.3022      5560
   macro avg     0.5575    0.5094    0.2575      5560
weighted avg     0.6784    0.3022    0.1771      5560
```

### v2 Fine-tuned (`checkpoints/koelectra-binary-v2/`)

```
              precision    recall  f1-score   support

      노이즈(0)     0.7718    0.9631    0.8569      4006
      할 일(1)     0.7362    0.2658    0.3905      1554

    accuracy                         0.7682      5560
   macro avg     0.7540    0.6144    0.6237      5560
weighted avg     0.7618    0.7682    0.7265      5560
```

### v3 Fine-tuned (`checkpoints/koelectra-binary/`)

```
              precision    recall  f1-score   support

      노이즈(0)     0.9270    0.9226    0.9248      4006
      할 일(1)     0.8029    0.8127    0.8078      1554

    accuracy                         0.8919      5560
   macro avg     0.8650    0.8677    0.8663      5560
weighted avg     0.8923    0.8919    0.8921      5560
```

---

## 결과 해석

### Base 모델: 거의 전량 양성 예측

recall 0.9794로 거의 모든 문장을 "할 일(1)"로 분류. precision 0.28 → FP 폭증. 파인튜닝 없이는 신뢰할 수 있는 분류 불가.

### v2 Fine-tuned: 노이즈에 강하나 할 일 탐지율 낮음

갈산초 데이터(v2.1_notices_galsan)만으로 학습했기 때문에, 신규 학교 문장 패턴에서 recall이 0.2658로 급락. 노이즈는 잘 걸러내지만(precision 0.74) 실제 할 일을 놓치는 비율이 높음. 갈산초 특화 모델에 가깝다.

### v3 Fine-tuned: 균형 잡힌 성능

신규 학교 데이터 ~27,800문장으로 학습 후 정밀도(0.80)와 재현율(0.81)이 균형을 이룸. Accuracy 89.19%, F1 0.8078로 실용 수준에 도달.

---

## 모델별 비교

| 관점 | Base | v2 | v3 |
|------|------|-----|-----|
| 학습 데이터 | 없음 | 갈산초 5,475문장 | 신규 학교 ~27,800문장 |
| 강점 | — | 노이즈 차단(FP↓) | 할 일 탐지 + 노이즈 차단 균형 |
| 약점 | FP 폭증 | 할 일 탐지율 낮음(FN↑) | 갈산초 특화 패턴 일부 미학습 |
| F1 (할 일) | 0.4396 | 0.3905 | **0.8078** |

---

## 결론

1. **v3가 v2 대비 명확한 개선**: F1 +0.42, Accuracy +12.4%p. 학습 데이터 규모 확대(5,475 → 27,800)와 다양한 학교 패턴 포함이 주요 원인.
2. **v2는 다교 데이터에서 recall 붕괴**: 갈산초에 특화돼 신규 학교 패턴에서 할 일 문장의 73%를 놓침.
3. **v3 val 성능이 신뢰 가능**: 이 테스트셋은 v3 학습 gradient에 포함되지 않은 20% held-out split이며, v2에게도 완전 unseen — 현재 가장 공정한 비교 기준.

---

## 다음 작업

| 항목 | 내용 |
|------|------|
| 고정 테스트셋 별도 확보 | 학습/모델선택 양쪽 모두 미참여한 진짜 held-out셋 구성 필요 |
| 갈산초 True 샘플 보강 | v3 학습셋에 galsan True 730개 혼합 후 v4 재학습 → galsan 일반화 개선 |
| 신청기간/운영시간 패턴 | FN 주원인으로 추정 — 해당 패턴 50개 이상 라벨링 후 재학습 |

---

## 재현 방법

```bash
# 평가 실행
python file/evaluate_model.py \
  --test_data data/train/test_data.jsonl \
  --v2_model checkpoints/koelectra-binary-v2 \
  --v3_model checkpoints/koelectra-binary
```

실행 환경: `conda activate multicultural`, PYTHONIOENCODING=utf-8

```python
# test_data.jsonl 생성 재현 (참고용)
from sklearn.model_selection import train_test_split
_, val_texts, _, val_labels = train_test_split(
    texts, labels, test_size=0.2, random_state=42, stratify=labels
)
# val_texts == test_data.jsonl 의 text 집합과 완전 일치 확인
```
