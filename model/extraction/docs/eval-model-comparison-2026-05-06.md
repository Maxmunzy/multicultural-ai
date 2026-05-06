# 모델 성능 비교 — Base vs v2 vs v3

**작성일**: 2026-05-06  
**담당**: 윤정  
**브랜치**: `feature/yunjeong-extraction-v5`

---

## 평가 목적

학습되지 않은 데이터(unseen)에서 Base 모델, v2 Fine-tuned, v3 Fine-tuned의 이진 분류 성능을 비교한다.

---

## 테스트셋 구성

| 항목 | 내용 |
|------|------|
| 파일 | `data/draft/unseen_test_galsan.jsonl` |
| 출처 | `data/train/v2.1_notices_galsan.jsonl` 중 v3 학습 데이터 미포함 항목 |
| 총 문장 수 | 5,388개 |
| is_todo True | 712개 (13.2%) |
| is_todo False | 4,676개 (86.8%) |
| 생성 방법 | v3_dual_labeled_clean.jsonl(학습셋) text 집합과 교집합 제거 후 저장 |

### 각 모델에 대한 테스트셋 성격

| 모델 | 테스트셋 성격 |
|------|-------------|
| Base 모델 | 완전 unseen |
| **v2 Fine-tuned** | ⚠️ **학습 데이터 (in-distribution)** — v2는 v2.1_notices_galsan 전체로 학습됨 |
| **v3 Fine-tuned** | ✅ **완전 unseen (out-of-distribution)** — v3는 신규 학교 데이터로만 학습, 갈산초 미포함 |

---

## 평가 결과

### 전체 요약

| 모델 | Accuracy | F1 (할 일) | Precision (할 일) | Recall (할 일) |
|------|----------|-----------|-----------------|--------------|
| Base 모델 | 13.21% | 0.2334 | 0.1321 | 1.0000 |
| v2 Fine-tuned | **98.11%** | **0.9304** | 0.9045 | 0.9579 |
| v3 Fine-tuned | 70.69% | 0.4184 | 0.2836 | 0.7978 |

### Base 모델

```
              precision    recall  f1-score   support

      노이즈(0)     0.0000    0.0000    0.0000      4676
      할 일(1)     0.1321    1.0000    0.2334       712

    accuracy                         0.1321      5388
   macro avg     0.0661    0.5000    0.1167      5388
weighted avg     0.0175    0.1321    0.0308      5388
```

### v2 Fine-tuned (`checkpoints/koelectra-binary-v2/`)

```
              precision    recall  f1-score   support

      노이즈(0)     0.9935    0.9846    0.9890      4676
      할 일(1)     0.9045    0.9579    0.9304       712

    accuracy                         0.9811      5388
   macro avg     0.9490    0.9712    0.9597      5388
weighted avg     0.9818    0.9811    0.9813      5388
```

### v3 Fine-tuned (`checkpoints/koelectra-binary/`)

```
              precision    recall  f1-score   support

      노이즈(0)     0.9575    0.6931    0.8041      4676
      할 일(1)     0.2836    0.7978    0.4184       712

    accuracy                         0.7069      5388
   macro avg     0.6205    0.7454    0.6113      5388
weighted avg     0.8684    0.7069    0.7531      5388
```

---

## 결과 해석

### Base 모델: 전량 양성 예측

precision이 13.21% = 테스트셋의 True 비율과 동일. 모든 문장을 "할 일(1)"로 예측하고 있음. 파인튜닝 없이는 가정통신문 분류 불가능함을 확인.

### v2 Fine-tuned: 높은 성능이지만 데이터 오염 주의

F1 0.9304, Accuracy 98.11%로 매우 높지만, **이 테스트셋은 v2의 학습 데이터(v2.1_notices_galsan.jsonl)에서 추출**되었음. 즉, v2에게는 in-distribution 평가이며 이전에 본 패턴이 많이 포함되어 있다. 일반화 성능이 아닌 암기 성능을 반영할 수 있음.

### v3 Fine-tuned: 진정한 unseen 평가

v3는 신규 학교 데이터(v3_dual_labeled_clean.jsonl)로만 학습했고 갈산초 데이터는 학습에 포함되지 않았다. Accuracy 70.69%, F1 0.4184는 v3의 **갈산초에 대한 실제 일반화 성능**.

성능 분해:
- **Recall 0.7978**: 실제 할 일 문장의 약 80%를 포착 (낮지 않음)
- **Precision 0.2836**: 할 일로 예측한 것 중 29%만 실제 할 일 (FP가 많음)

원인: v3가 학습한 신규 학교 데이터의 False 문장 패턴과 갈산초 False 문장 패턴이 달라서, 갈산초의 노이즈 문장을 할 일로 과잉 분류하는 distribution shift 발생.

---

## v2 vs v3 비교 — 공정한 해석

| 관점 | 설명 |
|------|------|
| 수치상 | v2 F1 0.9304 > v3 F1 0.4184 (-0.5120) |
| 실제 의미 | v2는 본 데이터, v3는 못 본 데이터 — 직접 비교 불공정 |
| v3의 의미 | 다른 학교 데이터로 학습 후 갈산초에 0.80 recall 달성 → 기본 패턴 전이 확인 |
| 문제점 | Precision 낮음 → 갈산초 False 패턴을 추가 학습해야 precision 회복 가능 |

---

## 결론 및 다음 작업

### 결론

1. **Base 모델 vs Fine-tuned**: 파인튜닝 효과 명확. Base는 완전히 무작위, v2/v3 모두 유의미한 분류 학습.
2. **v2의 갈산초 특화**: v2는 갈산초 데이터로 학습해 갈산초 분류에 특화됨 (F1 0.93).
3. **v3의 distribution shift**: v3는 타 학교 데이터 → 갈산초 일반화에서 FP 과다 발생. recall은 유지되나 precision이 낮아 실용성 부족.
4. **진짜 unseen 비교**: v3가 갈산초에서 보여주는 F1 0.42는 현재 한계치. 갈산초 True 샘플 혼합 학습이 필요.

### 다음 작업

| 항목 | 내용 | 우선순위 |
|------|------|---------|
| 학습 데이터 혼합 | v3_dual_labeled_clean에 갈산초 True 샘플(730개) 추가 후 재학습 | 높음 |
| 고정 테스트셋 확정 | `data/draft/unseen_test_galsan.jsonl` 기준으로 v4 재학습 후 비교 | 높음 |
| Precision 개선 | galsan False 패턴을 별도로 보강하거나 BINARY_THRESHOLD 조정 | 중간 |
| 공정한 unseen셋 구성 | v2, v3 모두 학습에 쓰지 않은 데이터로 3차 비교 진행 | 중간 |

---

## 재현 방법

```bash
# 테스트셋 생성 (이미 저장됨: data/draft/unseen_test_galsan.jsonl)
# v2.1_notices_galsan 중 v3_dual_labeled_clean 미포함 항목만 추출

# 평가 실행
python file/evaluate_model.py \
  --test_data data/draft/unseen_test_galsan.jsonl \
  --v2_model checkpoints/koelectra-binary-v2 \
  --v3_model checkpoints/koelectra-binary
```

실행 환경: `conda activate multicultural`, PYTHONIOENCODING=utf-8
