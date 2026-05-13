# 모델 평가 이력 — KoELECTRA 이진 분류기

**담당**: 윤정  
**최종 수정**: 2026-05-08

---

## 요약 — 전체 버전 성능 이력

### 테스트셋 A — val split (5,650개)
> v3.1_dual_labeled 20% stratified split. v3.1에 공정, v3엔 학습 데이터 98.6% 포함.

| 모델 | Threshold | Accuracy | F1 (할 일) | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| Base (KoELECTRA-base 사전학습만) | — | 30.22% | 0.4396 | 0.2834 | 0.9794 |
| v2 Small (갈산초 전용) | 0.65 | 76.82% | 0.3905 | 0.7362 | 0.2658 |
| v3 Small (다교 27,799행) | 0.65 | 89.58% | 0.8225 | 0.8149 | 0.8303 |
| v3.1 Small (증강 28,247행) | 0.55 | 89.40% | 0.8223 | 0.8025 | 0.8431 |
| **base-v1 (v3.1.3, 22,523행)** | **0.40** | **90.69%** | **0.8387** | **0.8459** | 0.8315 |

### 테스트셋 B — galsan unseen (5,388개) ← 실전 기준
> 갈산초 v2.1_notices_galsan 중 v3 학습 미포함분. 모든 버전 완전 unseen.

| 모델 | Threshold | Accuracy | F1 (할 일) | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| Base (사전학습만) | — | 13.21% | 0.2334 | 0.1321 | 1.0000 |
| v2 Small | 0.65 | 76.82%† | 0.3905† | 0.7362† | 0.2658† |
| v3 Small | 0.65 | 70.69% | 0.4184 | 0.2836 | 0.7978 |
| v3.1 Small | 0.55 | 68.73% | 0.4168 | 0.2765 | 0.8455 |
| base-v1 (v3.1.3) | 0.40 | 72.03% | 0.4166 | 0.2875 | 0.7556 |
| **base (v4_merged)** | **0.55** | **74.00%** | **0.4687** | **0.3210** | **0.8680** |
| 향상 폭 (base-v1 → v4) | | +1.97%p | +0.0521 | +0.0335 | **+0.1124** |

†  v2는 galsan이 학습 데이터에 포함되어 직접 비교 불가. v3 val split 기준값 사용.

> **해석**: F1 절대값이 낮은 이유는 클래스 불균형(노이즈 6.6배). Recall 중심 평가가 올바름 — 학부모가 놓치면 안 되는 정보 우선.

---

## 1단계 평가 — Base / v2 / v3 비교 (2026-05-06)

**목적**: 학습되지 않은 데이터에서 세 모델의 이진 분류 성능 비교.

### 테스트셋 구성

| 항목 | 내용 |
|------|------|
| 파일 | `data/train/test_data.jsonl` |
| 출처 | v3_dual_labeled_clean 20% stratified val split (random_state=42) |
| 총 문장 | 5,560개 (is_todo True 1,554 / False 4,006) |

### 결과 요약

| 모델 | Accuracy | F1 | Precision | Recall |
|------|---------|-----|-----------|--------|
| Base (사전학습만) | 30.22% | 0.4396 | 0.2834 | 0.9794 |
| v2 Fine-tuned | 76.82% | 0.3905 | 0.7362 | 0.2658 |
| **v3 Fine-tuned** | **89.19%** | **0.8078** | **0.8029** | **0.8127** |

### 해석

- **Base 모델**: 거의 전량 양성 예측. Recall 0.9794지만 Precision 0.28 → FP 폭증.
- **v2**: 갈산초에 특화. 신규 학교 패턴에서 Recall 0.27로 붕괴 — 갈산초 특화 함정.
- **v3**: 신규 학교 ~27,800문장 추가 후 Precision/Recall 균형 달성. 실용 수준 도달.

---

## 2단계 평가 — v3 vs v3.1 비교 (2026-05-06)

**목적**: True 샘플 448개 증강(v3.1_augmented)의 효과 검증. 두 테스트셋 병행.

### 테스트셋 A — v3.1 val split (5,650개)

| 모델 | Accuracy | F1 | Precision | Recall |
|------|---------|-----|-----------|--------|
| v3 | 89.58% | 0.8225 | 0.8149 | 0.8303 |
| **v3.1** | 89.40% | **0.8223** | 0.8025 | **0.8431** |
| 변화 | -0.18%p | -0.0002 | -0.0124 | **+0.013** |

> ⚠️ v3는 이 테스트셋의 98.6%가 학습 데이터에 포함. v3.1에 공정한 비교.

### 테스트셋 B — galsan unseen (5,388개) ← 공정 비교 기준

| 모델 | Accuracy | F1 | Precision | Recall |
|------|---------|-----|-----------|--------|
| v3 | 70.69% | **0.4184** | **0.2836** | 0.7978 |
| **v3.1** | 68.73% | 0.4168 | 0.2765 | **0.8455** |
| 변화 | -1.97%p | -0.0017 | -0.007 | **+0.048** |

### 해석

- F1은 두 테스트셋 모두 거의 동일(±0.002). 전반적 성능 유지.
- v3.1이 두 테스트셋에서 일관되게 **Recall +1.3~4.8%p** 향상 — 증강 방향성 올바름.
- Precision 소폭 하락(-0.7~1.2%p) 허용 범위.

---

## 3단계 평가 — v3.1 Small vs Base (2026-05-07~08)

**목적**: 백본을 Small(14M) → Base(110M)로 교체했을 때 효과 측정.

### 모델 구성 차이

| 항목 | v3.1 Small | Base (v3.1.3) |
| --- | --- | --- |
| 백본 | `koelectra-small-v3-discriminator` | `koelectra-base-v3-discriminator` |
| 파라미터 | ~14M | ~110M |
| 학습 데이터 | v3.1_dual_labeled (28,247) | v3.1.3_dual_labeled (22,523) |
| 데이터 변경 | Haiku 이진 라벨 | B그룹 제외 + KL Divergence 소프트 라벨 |
| Threshold | 0.55 | **0.40** |
| 학습 시간 | ~10분 | ~60분 |

### 테스트셋 A — val split (5,650개)

| 모델 | Accuracy | F1 | Precision | Recall |
| --- | --- | --- | --- | --- |
| v3.1 Small | 89.40% | 0.8223 | 0.8025 | 0.8431 |
| **Base** | **90.69%** | **0.8387** | **0.8459** | 0.8315 |
| 변화 | +1.29%p | +0.0164 | **+0.0434** | -0.0116 |

### 테스트셋 B — galsan unseen (5,388개)

> ⚠️ 평가 조건: pipeline 기본 threshold(0.5) 사용. 운영 threshold(Base: 0.40 / Small: 0.55)와 다름 — 상대 비교만 유효.

| 모델 | Accuracy | F1 | Precision | Recall |
| --- | --- | --- | --- | --- |
| v3.1 Small | 68.73% | **0.4168** | 0.2765 | **0.8455** |
| **Base** | **71.88%** | 0.4157 | **0.2865** | 0.7570 |
| 변화 | +3.15%p | -0.0011 | +0.0100 | -0.0885 |

### 임계값 탐색 결과 (Base, val split 기준)

| Threshold | F1 | Precision | Recall |
| --- | --- | --- | --- |
| **0.40** | **0.8393** | 0.8447 | 0.8339 |
| 0.50 | 0.8387 | 0.8459 | 0.8315 |
| 0.65 | 0.8354 | 0.8469 | 0.8242 |
| 0.70 | 0.8347 | 0.8467 | 0.8230 |

최적 임계값: **0.40** (곡선 평탄 — 0.40~0.70 구간 F1 차이 0.005).  
`predict.py BINARY_THRESHOLD = 0.40` → v4_merged 재학습 후 재탐색 필요.

### 해석

- **val split**: Base가 F1 +0.016, Precision +0.043 우위. Recall -0.012는 허용 범위.
- **galsan unseen**: F1 사실상 동일(0.001 차). Base Accuracy +3.15%p 우위.
- Small이 Recall에서 앞서지만 unseen F1이 동일하고 seen에서 Base 우위 → **Base 채택 유지**.
- KL Divergence 학습으로 threshold가 0.55→0.40으로 낮아진 이유: 경계 케이스 확신도 ↓, 명확히 분리.

---

## 재현 방법

```bash
cd model/extraction

# 1단계: Base/v2/v3 비교
python file/evaluate_model.py \
  --test_data data/train/test_data.jsonl \
  --v2_model checkpoints/koelectra-binary-v2 \
  --v3_model checkpoints/koelectra-binary

# 2단계: v3 vs v3.1 (양방향)
python file/evaluate_model.py \
  --test_data data/draft/v3.1_val_split.jsonl \
  --v2_model checkpoints/koelectra-binary-v3 \
  --v3_model checkpoints/koelectra-binary-v3.1

python file/evaluate_model.py \
  --test_data data/draft/unseen_test_galsan.jsonl \
  --v2_model checkpoints/koelectra-binary-v3 \
  --v3_model checkpoints/koelectra-binary-v3.1

# 3단계: Small vs Base
python file/evaluate_model.py \
  --test_data data/draft/unseen_test_galsan.jsonl \
  --v2_model checkpoints/koelectra-binary-v3.1 \
  --v3_model checkpoints/koelectra-binary-base
```

실행 환경: `conda activate multicultural`, `PYTHONIOENCODING=utf-8`
