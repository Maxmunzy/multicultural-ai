# 모델 성능 비교 — v3 vs v3.1

**작성일**: 2026-05-06  
**담당**: 윤정  
**브랜치**: `feature/yunjeong-extraction-v5`

---

## 개요

준비물·유의사항 패턴 True 샘플 448개를 증강(v3.1_augmented.jsonl)하여 재학습한 v3.1 모델과 기존 v3 모델의 성능을 비교한다.

| 항목 | v3 | v3.1 |
|------|-----|-------|
| 체크포인트 | `checkpoints/koelectra-binary-v3` | `checkpoints/koelectra-binary-v3.1` |
| 학습 데이터 | `v3_dual_labeled_clean.jsonl` (27,799개) | `v3.1_dual_labeled.jsonl` (28,247개) |
| 증강 내용 | — | True 샘플 +448개 (준비물·유의사항·복장 등 7패턴) |
| BINARY_THRESHOLD | 0.65 | **0.50** |

---

## 테스트셋 구성

| | 테스트셋 A | 테스트셋 B |
|--|-----------|-----------|
| 파일 | `data/draft/v3.1_val_split.jsonl` | `data/draft/unseen_test_galsan.jsonl` |
| 출처 | v3.1_dual_labeled 20% stratified val split | v2.1_notices_galsan 중 v3 학습 미포함분 |
| 총 문장 | 5,650개 | 5,388개 |
| True / False | 1,644 / 4,006 | 712 / 4,676 |
| v3 관계 | ⚠️ 98.6%가 v3 학습 데이터 포함 | ✅ 두 모델 모두 완전 unseen |
| v3.1 관계 | ✅ val split (학습 gradient 미포함) | ✅ 두 모델 모두 완전 unseen |

> 테스트셋 A는 v3.1에게 공정한 평가셋이지만 v3에게는 학습 데이터 98.6% 포함으로 유리한 조건.  
> 테스트셋 B가 두 모델 간 진짜 unseen 비교 기준.

---

## 평가 결과

### 테스트셋 A — v3.1 val split (5,650개)

| 모델 | Accuracy | F1 (할 일) | Precision | Recall |
|------|----------|-----------|-----------|--------|
| Base | 70.80% | 0.0024 | 0.2000 | 0.0012 |
| **v3** | **89.58%** | 0.8225 | 0.8149 | 0.8303 |
| **v3.1** | 89.40% | **0.8223** | 0.8025 | **0.8431** |
| v3.1 변화 | -0.18%p | -0.0002 | -0.0124 | **+0.013** |

```
[v3 — 테스트셋 A]
              precision    recall  f1-score   support
      노이즈     0.9298    0.9226    0.9262      4006
      할 일     0.8149    0.8303    0.8225      1644
    accuracy                         0.8958      5650

[v3.1 — 테스트셋 A]
              precision    recall  f1-score   support
      노이즈     0.9342    0.9149    0.9245      4006
      할 일     0.8025    0.8431    0.8223      1644
    accuracy                         0.8940      5650
```

### 테스트셋 B — unseen galsan (5,388개) ← 공정 비교 기준

| 모델 | Accuracy | F1 (할 일) | Precision | Recall |
|------|----------|-----------|-----------|--------|
| Base | 13.21% | 0.2334 | 0.1321 | 1.0000 |
| **v3** | **70.69%** | **0.4184** | **0.2836** | 0.7978 |
| **v3.1** | 68.73% | 0.4168 | 0.2765 | **0.8455** |
| v3.1 변화 | -1.97%p | -0.0017 | -0.007 | **+0.048** |

```
[v3 — 테스트셋 B]
              precision    recall  f1-score   support
      노이즈     0.9575    0.6931    0.8041      4676
      할 일     0.2836    0.7978    0.4184       712
    accuracy                         0.7069      5388

[v3.1 — 테스트셋 B]
              precision    recall  f1-score   support
      노이즈     0.9657    0.6632    0.7864      4676
      할 일     0.2765    0.8455    0.4168       712
    accuracy                         0.6873      5388
```

---

## 결과 해석

### v3.1 val split (테스트셋 A)

F1이 거의 동일(0.0002 차이)하지만 구성 변화가 있다.
- **Recall 향상 +0.013**: 할 일 문장을 더 많이 잡음
- **Precision 하락 -0.012**: FP 소폭 증가
- 주의: 테스트셋 A의 98.6%가 v3 학습 데이터에 포함됨 → v3 수치가 인위적으로 높을 수 있음

### unseen galsan (테스트셋 B, 진짜 비교 기준)

F1은 0.0017 차이로 사실상 동일하지만 내부 구성이 다르다.
- **v3.1 Recall +0.048**: 갈산초 할 일 문장의 84.6%를 포착 (v3는 79.8%)
- **v3.1 Precision -0.007**: FP 소폭 증가, 허용 범위
- 증강 패턴(준비물·복장·유의사항)이 갈산초 데이터에도 부분적으로 적용됨

### 종합 평가

| 관점 | 판단 |
|------|------|
| 할 일 탐지율 | v3.1이 두 테스트셋 모두 recall ↑ (+1.3~4.8%p) |
| FP 수준 | Precision 소폭 하락(-0.7~1.2%p), 실용 허용 범위 |
| 전반적 F1 | 두 모델 거의 동일 (±0.002) |
| 갈산초 일반화 | 증강 효과 부분 확인. 갈산초 True 샘플 추가 시 추가 개선 가능 |
| 증강 방향성 | 올바름 — recall 중심 개선, precision 유지 |

---

## 재현 방법

```bash
cd model/extraction

# 테스트셋 A
python file/evaluate_model.py \
  --test_data data/draft/v3.1_val_split.jsonl \
  --v2_model checkpoints/koelectra-binary-v3 \
  --v3_model checkpoints/koelectra-binary-v3.1

# 테스트셋 B
python file/evaluate_model.py \
  --test_data data/draft/unseen_test_galsan.jsonl \
  --v2_model checkpoints/koelectra-binary-v3 \
  --v3_model checkpoints/koelectra-binary-v3.1
```

실행 환경: `conda activate multicultural`, PYTHONIOENCODING=utf-8

---

## 다음 작업

| 항목 | 내용 |
|------|------|
| BINARY_THRESHOLD 재탐색 | v3.1 재학습 후 0.4~0.7 구간 최적값 재평가 필요 |
| 갈산초 True 샘플 보강 | 갈산초 특화 패턴 추가 학습 시 galsan 일반화 개선 기대 |
| 고정 테스트셋 확보 | 두 모델 모두 미포함인 깨끗한 held-out셋 구성 필요 |
| v4 재학습 | 갈산초 True 730개 + v3.1 데이터 혼합 후 재학습 |
