# 모델 성능 비교 — Small(v3.1) vs Base

**작성일**: 2026-05-07  
**담당**: 윤정  
**브랜치**: `feature/yunjeong-extraction-v5`

---

## 개요

KoELECTRA-small(v3.1)과 KoELECTRA-base를 비교한다.  
모델 크기 외에 학습 데이터와 손실 함수도 함께 변경되었으므로 변수가 복합적임에 유의.

| 항목 | v3.1 Small | **Base** |
| --- | --- | --- |
| 체크포인트 | `checkpoints/koelectra-binary-v3.1` | `checkpoints/koelectra-binary-base` |
| 백본 | `monologg/koelectra-small-v3-discriminator` | `monologg/koelectra-base-v3-discriminator` |
| 파라미터 수 | ~14M | **~110M** |
| 학습 데이터 | `v3.1_dual_labeled.jsonl` (28,247개, True 29.1%) | `v3.1.3_dual_labeled.jsonl` (22,523개, True 16.2%) |
| 데이터 변경 | Haiku 이진 라벨 | B그룹 제외 + 소프트 라벨 (KL Divergence) |
| BINARY_THRESHOLD | 0.55 | **0.40** |
| 학습 시간 (T4) | ~10분 | **~60분** |

---

## 테스트셋 구성

| | 테스트셋 A |
| --- | --- |
| 파일 | `data/draft/v3.1_val_split.jsonl` |
| 출처 | v3.1_dual_labeled 20% stratified val split |
| 총 문장 | 5,650개 |
| True / False | 1,644 / 4,006 |
| Base 관계 | ⚠️ Base 학습 데이터(v3.1.3)와 일부 겹침 가능 — 단, B그룹 제외로 구성 다름 |

> 공정한 unseen 비교를 위해 추후 galsan 테스트셋(테스트셋 B) 평가 필요.

---

## 평가 결과

### 테스트셋 A — val split (5,650개)

| 모델 | Accuracy | F1 (할 일) | Precision | Recall |
| --- | --- | --- | --- | --- |
| v3.1 Small | 89.40% | 0.8223 | 0.8025 | 0.8431 |
| **Base** | **90.69%** | **0.8387** | **0.8459** | 0.8315 |
| 변화 | **+1.29%p** | **+0.0164** | **+0.0434** | -0.0116 |

```
[v3.1 Small — 테스트셋 A]
              precision    recall  f1-score   support
      노이즈     0.9342    0.9149    0.9245      4006
      할 일     0.8025    0.8431    0.8223      1644
    accuracy                         0.8940      5650

[Base — 테스트셋 A]
              precision    recall  f1-score   support
      노이즈     0.9313    0.9378    0.9346      4006
      할 일     0.8459    0.8315    0.8387      1644
    accuracy                         0.9069      5650
```

---

## 임계값 탐색 결과 (Base)

| Threshold | F1 | Precision | Recall |
| --- | --- | --- | --- |
| **0.40** | **0.8393** | 0.8447 | 0.8339 |
| 0.45 | 0.8388 | 0.8451 | 0.8327 |
| 0.50 | 0.8387 | 0.8459 | 0.8315 |
| 0.55 | 0.8375 | 0.8461 | 0.8291 |
| 0.60 | 0.8362 | 0.8466 | 0.8260 |
| 0.65 | 0.8354 | 0.8469 | 0.8242 |
| 0.70 | 0.8347 | 0.8467 | 0.8230 |

**최적 임계값: 0.40** → `predict.py BINARY_THRESHOLD = 0.40` 반영 완료.

> 임계값 곡선이 매우 평탄(F1 차이 0.005)함. 모델이 0.4 이하 또는 0.7 이상으로 명확하게 분류하고 있음을 시사.

---

## 결과 해석

### Precision +4.3%p, Recall -1.2%p

Base 모델이 더 정밀해졌고, 약간의 Recall을 잃었다.

- **Precision 향상**: 오탐(노이즈를 할 일로 잘못 분류)이 줄었다. 소프트 라벨 + B그룹 제외로 경계 케이스 노이즈가 줄어든 효과.
- **Recall 소폭 하락**: True 학습 샘플이 절대적으로 줄었다(8,220 → 3,655개). 일부 경계 케이스를 보수적으로 False 처리.

### Threshold가 0.55 → 0.40으로 낮아진 이유

소프트 라벨(KL Divergence) 학습으로 모델이 경계 케이스에서 확신을 덜 가진다.  
0.4~0.7 구간에 확률을 몰아넣지 않고 명확하게 양 끝으로 분리하므로 threshold 0.40에서 최적.

### 종합 평가

| 관점 | 판단 |
| --- | --- |
| F1 | Base +0.016 향상 ✅ |
| Precision | Base +0.043 향상 ✅ (FP 감소) |
| Recall | Small이 +0.012 높음 ⚠️ |
| Accuracy | Base +1.3%p 향상 ✅ |
| 학습 비용 | Small ~10분, Base ~60분 (×6) |

서비스 관점에서 Precision 향상이 Recall 소폭 하락보다 가치 있다.  
학부모가 "노이즈 문장"을 할 일로 오인하는 것이 "중요 문장"을 놓치는 것보다 UX에 더 해롭기 때문.

---

## 전체 모델 이력

| 모델 | 학습 데이터 | Threshold | Accuracy | F1 (할 일) | Precision | Recall |
| --- | --- | --- | --- | --- | --- | --- |
| v3 Small | v3_dual_labeled_clean (27,799) | 0.65 | 89.58% | 0.8225 | 0.8149 | 0.8303 |
| v3.1 Small | v3.1_dual_labeled (28,247) | 0.55 | 89.40% | 0.8223 | 0.8025 | 0.8431 |
| **Base** | **v3.1.3_dual_labeled (22,523)** | **0.40** | **90.69%** | **0.8387** | **0.8459** | 0.8315 |

> galsan unseen(테스트셋 B) 평가 미완료 — 추후 `evaluate_model.py` 로 측정 필요.

---

## 재현 방법

```bash
cd model/extraction

# Base 모델 평가 (테스트셋 A)
python file/evaluate_model.py \
  --test_data data/draft/v3.1_val_split.jsonl \
  --model     checkpoints/koelectra-binary-base \
  --threshold 0.40

# Small vs Base 비교 (테스트셋 B)
python file/evaluate_model.py \
  --test_data data/draft/unseen_test_galsan.jsonl \
  --v2_model  checkpoints/koelectra-binary-v3.1 \
  --v3_model  checkpoints/koelectra-binary-base
```

실행 환경: `conda activate multicultural`, PYTHONIOENCODING=utf-8
