# Worklog — 2026-05-06 · 분류 파트 (담당: 경이)

**작성일:** 2026-05-06  
**작성자:** 경이 (kyeongyi)  
**작업 범위:** KcELECTRA v3 파인튜닝 최종 성능 비교 및 튜닝 시도 결과 정리

---

## 1. 실행 환경

| 항목 | 내용 |
|---|---|
| 데이터 | `notice_sample_v5_clean_full_20260504.csv` (4,992행, 수동 라벨링) |
| 분할 파일 | `data/split_v5_20260505.csv` (train 3,993 / val 500 / test 499) |
| 분할 전략 | Stratified Split — 카테고리 비율 유지 (Seed=42) |
| 평가 대상 | Simple (TF-IDF + LogReg) vs KcELECTRA v3 (파인튜닝) |
| 평가 기준 | 동일 test 세트 499건으로 공정 비교 |
| 출력 폴더 | `model/classification/data/20260505/` |

---

## 2. 실행 명령 및 원본 출력

```
(ai_env) python scripts/evaluate_compare_v3_20260505.py

[Simple - TF-IDF + LogReg]
          일정   precision 0.95 / recall 0.83 / f1 0.88  (92건)
         준비물   precision 0.90 / recall 0.82 / f1 0.86  (22건)
          제출   precision 0.83 / recall 0.84 / f1 0.83  (147건)
          비용   precision 0.89 / recall 0.75 / f1 0.81  (32건)
       건강·안전   precision 0.84 / recall 0.94 / f1 0.88  (127건)
          기타   precision 0.59 / recall 0.61 / f1 0.60  (79건)
    accuracy: 0.82  (499건)

  Simple    Macro F1 : 0.8116
  KcELECTRA Macro F1 : 0.8545
  Delta              : +0.0429
```

---

## 3. 성능 비교 요약

### 3-1. Macro 지표 (전체 평균)

| 지표 | Simple (베이스라인) | KcELECTRA v3 | 차이 | 비고 |
|---|---|---|---|---|
| Macro Precision | 0.8322 | 0.8513 | +0.0191 | ↑ |
| Macro Recall | 0.7959 | 0.8625 | **+0.0666** | ★ 5% 목표 초과 |
| **Macro F1** | **0.8116** | **0.8545** | **+0.0429** | 목표 5%에 0.71%p 미달 |

### 3-2. 카테고리별 F1 비교

| 카테고리 | Simple F1 | KcELECTRA F1 | 차이 | test 건수 | 해석 |
|---|---|---|---|---|---|
| 일정 | 0.8837 | 0.8851 | +0.0014 | 92건 | Simple이 이미 높아 개선 여지 좁음 |
| 준비물 | 0.8571 | 0.8750 | +0.0179 | 22건 | 소수 클래스 — 평가 불안정 |
| 제출 | 0.8339 | 0.8664 | **+0.0325** | 147건 | 의미 있는 향상 |
| 비용 | 0.8136 | **0.9231** | **+0.1095** | 32건 | 가장 큰 향상 — 금액·납부 패턴 포착 |
| 건강·안전 | 0.8848 | 0.9105 | **+0.0257** | 127건 | 안정적 향상 |
| 기타 | 0.5963 | 0.6667 | **+0.0704** | 79건 | 양 모델 모두 낮음 — 구조적으로 어려운 클래스 |

### 3-3. v1 → v2 → v3 버전 추이

| 버전 | train 크기 | Simple Macro F1 | KcELECTRA Macro F1 | 결과 |
|---|---|---|---|---|
| v1 | ~244건 | ~0.72 | ~0.51 | KcELECTRA 크게 열세 |
| v2 | 556건 | 0.7919 | 0.6938 | KcELECTRA 여전히 열세 |
| **v3** | **3,993건** | **0.8116** | **0.8545** | **KcELECTRA 역전** |

> KcELECTRA는 데이터 양에 민감하다. v2→v3에서 train을 약 7배 늘리자 Simple 대비 역전에 성공.

---

## 4. 생성된 시각화 파일: 4-1. 이전 결과 VS. 4-2. 최신 결과

### 4-1. 이전 결과 (2026-04-30 기준)

| 파일명 | 내용 |
|---|---|
| `compare_macro_f1.png` | Macro F1 막대 비교 |
| `compare_per_class_f1.png` | 카테고리별 F1 그룹 바 차트 |
| `compare_confusion_matrix.png` | Confusion Matrix 비교 |
| `compare_radar_f1.png` | 레이더 차트 |

**Macro F1 비교 (이전)**
![Macro F1 비교 이전](../model/classification/data/20260430/compare_macro_f1.png)

**카테고리별 F1 비교 (이전)**
![카테고리별 F1 이전](../model/classification/data/20260430/compare_per_class_f1.png)

**Confusion Matrix (이전)**
![Confusion Matrix 이전](../model/classification/data/20260430/compare_confusion_matrix.png)

**레이더 차트 (이전)**
![레이더 차트 이전](../model/classification/data/20260430/compare_radar_f1.png)

---

### 4-2. 최신 결과 — KcELECTRA v3 (2026-05-05 기준)

| 파일명 | 내용 |
|---|---|
| `compare_macro_f1_v3_20260505.png` | Macro F1 막대 비교 |
| `compare_per_class_f1_v3_20260505.png` | 카테고리별 F1 그룹 바 차트 |
| `compare_confusion_matrix_v3_20260505.png` | Confusion Matrix 비교 |
| `compare_radar_f1_v3_20260505.png` | 레이더 차트 |
| `compare_version_trend_v3_20260505.png` | v1→v2→v3 버전 추이 |
| `compare_precision_recall_f1_v3_20260505.png` | Precision / Recall / F1 종합 비교 |

**Macro F1 비교 (v3)**
![Macro F1 비교 v3](../model/classification/data/20260505/compare_macro_f1_v3_20260505.png)

**카테고리별 F1 비교 (v3)**
![카테고리별 F1 v3](../model/classification/data/20260505/compare_per_class_f1_v3_20260505.png)

**Confusion Matrix (v3)**
![Confusion Matrix v3](../model/classification/data/20260505/compare_confusion_matrix_v3_20260505.png)

**레이더 차트 (v3)**
![레이더 차트 v3](../model/classification/data/20260505/compare_radar_f1_v3_20260505.png)

**버전 추이 (v1→v2→v3)**
![버전 추이](../model/classification/data/20260505/compare_version_trend_v3_20260505.png)

**Precision / Recall / F1 종합 비교 (v3)**
![Precision Recall F1 v3](../model/classification/data/20260505/compare_precision_recall_f1_v3_20260505.png)

> 이미지가 보이지 않을 경우 아래 경로에서 직접 확인:  
> - 이전: `multicultural-ai/model/classification/data/20260430/`  
> - 최신: `multicultural-ai/model/classification/data/20260505/`

---

## 5. 현재 결과 해석

### 잘 된 점

- KcELECTRA가 **전 카테고리에서 Simple 이상** 성능 달성 (하락 없음)
- **비용** 카테고리: +10.95%p — 금액, 납부, 안내 표현을 전이학습 모델이 잘 포착
- **기타** 카테고리: +7.04%p — 불명확한 공지도 KcELECTRA가 더 잘 분류
- **Macro Recall** +6.66% — 5% 목표 초과 달성
- v2 대비 KcELECTRA 성능 0.6938 → 0.8545 대폭 향상 (데이터 7배 증가 효과)

### 아쉬운 점

- **Macro F1 +4.29%** — 목표치 5%에 0.71%p 미달
- **일정·준비물** 카테고리 개선 폭 미미
- **기타** 카테고리가 양 모델 모두 낮음 (0.60 / 0.67) — 정의 자체가 모호한 클래스

---

## 6. 추가 튜닝 시도 요약 및 한계

v4 (LR 3e-5), v5 (label_smoothing + cosine), v6 (FocalLoss + 차등 LR) 등 하이퍼파라미터 튜닝을 여러 번 시도했으나, 모든 시도에서 v3(0.8545)보다 낮은 성능이 나왔다.

이는 단순한 튜닝 설정의 문제가 아니라 **기타 클래스 학습 데이터의 다양성 부족**이 근본 원인임을 시사한다. 기타 클래스 train 데이터(630건)에 충분한 패턴이 없어 어떤 손실 함수나 학습률 조정도 실질적인 개선으로 이어지지 않았으며, 파인튜닝만으로는 이 모델을 더 개선하기 어려운 구조적 한계에 도달했다.

| 시도 | 핵심 변경 | 결과 |
|---|---|---|
| v4 | LR 3e-5 | v3보다 낮음 |
| v5 | label_smoothing + cosine | v3보다 낮음 |
| v6 | FocalLoss + 차등 LR | v3보다 낮음 |

**현재 최선:** KcELECTRA v3 + Simple 앙상블(kc=0.5) → Macro F1 **0.8583** (+4.67%)

---

*작성: 2026-05-06*
