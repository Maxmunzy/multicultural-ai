# 베이스 KoELECTRA vs 파인튜닝 모델 — 카테고리 분류 정량 비교

**날짜**: 2026-04-28  
**영역**: extraction  
**담당**: 태수 (윤정 파인튜닝 모델 기반)  
**관련 PR/커밋**: 디스코드 팀방 공유 md (검증 코드는 미팅 후 폐기)

---

## 1. 목적

강사 지적사항(2026-04-27): *"파인튜닝을 했더니 성능이 이렇게 좋았어요... 똑같은 텍스트를 주었을 때 베이스 모델과 파인튜닝 모델의 성능 비교를 보여주는 자료가 있어야 한다."*

→ 학습 안 한 KoELECTRA(=base + 분류 head random init)와 윤정님이 100문장으로 파인튜닝한 모델을 동일 검증셋에서 비교, 파인튜닝 효과를 정량 입증.

---

## 2. 데이터

| 항목 | 값 |
| --- | --- |
| 데이터셋 | `model/extraction/data/notices_labeled_v2.jsonl` |
| 샘플 수 | 100문장 (category 라벨 있는 행만) |
| 분할 | train 80 / val 20 |
| 분할 시드 | `random_state=42`, `stratify=labels` (윤정 노트북 셀과 동일) |
| 라벨 분포 (val) | 건강·안전 7 / 일정 4 / 준비물 4 / 제출 4 / 기타 1 |
| 전처리 | sklearn `train_test_split` 외 별도 전처리 없음 |
| 증강 | 없음 |

---

## 3. 모델 / 파이프라인

| 항목 | 값 |
| --- | --- |
| 베이스 모델 | `monologg/koelectra-base-v3-discriminator` (HF Hub public) |
| 파인튜닝 모델 | `yunjeong116/koelectra-extractor` (subfolder: `koelectra-extractor`) |
| 비교 대상 | Random baseline (이론값) / Majority baseline / Base / Fine-tuned |
| 추론 | `AutoModelForSequenceClassification` + `argmax(logits)` |

---

## 4. 하이퍼파라미터

### Base 모델 (학습 X)

| 항목 | 값 |
| --- | --- |
| 분류 head | random init (5-class) |
| 학습 | **수행하지 않음** |
| seed | 42, 1, 2 (3개 평균) |
| max_length | 128 |
| device | CPU (Docker 컨테이너) |

### Fine-tuned 모델 (윤정님 학습 결과 — 참고)

| 항목 | 값 |
| --- | --- |
| epochs | 10 (이전 04-27 체크포인트) |
| learning rate | 3e-5 |
| LR 스케줄러 | linear |
| warmup | 없음 |
| 손실 함수 | CrossEntropy (균등) |

> 04-28 재학습본(0.85)은 본 측정 시점에 HF Hub에 미배포 상태였음. 본 실험 측정값은 04-27 체크포인트 기준.

---

## 5. 결과

### 핵심 비교 표

| 모델 | accuracy | macro F1 | 비고 |
| --- | --- | --- | --- |
| Random baseline (이론값) | 0.20 | — | 5-class 균등 추측 |
| Majority baseline (건강·안전로 다 찍기) | 0.35 | 0.10 | precision 0.07 weighted |
| **Base KoELECTRA** (학습 X, 3 seed 평균) | **0.17 ± 0.09** | **0.07 ± 0.04** | seed별 0.05 / 0.25 / 0.20 |
| **Fine-tuned KoELECTRA** (yunjeong116/koelectra-extractor) | **0.7500** | **0.5988** | 04-27 체크포인트 |

### 향상 폭

| 지표 | Base → Fine-tuned | 배수 |
| --- | --- | --- |
| accuracy | 0.17 → 0.75 | **×4.4** |
| macro F1 | 0.07 → 0.60 | **×8.6** |

### Per-class (Fine-tuned 기준)

| 카테고리 | precision | recall | F1 | support |
| --- | --- | --- | --- | --- |
| 일정 | 1.0000 | 1.0000 | 1.0000 | 4 |
| 준비물 | 1.0000 | 0.2500 | 0.4000 | 4 |
| 제출 | 1.0000 | 0.7500 | 0.8571 | 4 |
| 건강·안전 | 0.5833 | 1.0000 | 0.7368 | 7 |
| 기타 | 0.0000 | 0.0000 | 0.0000 | 1 |

---

## 6. 인사이트 / 해석

- **학습 100문장만으로도 random 수준 → 운영 가능 수준 도달.** 적은 데이터에서도 KoELECTRA pretrained representation이 한국어 학교 도메인에 빠르게 적응.
- **준비물 recall 0.25, 기타 F1 0.0** — 클래스 불균형 영향. 윤정님이 04-28 재학습에서 `compute_class_weight('balanced')` 적용해 0.85까지 끌어올림 (`devlog-2026-04-28-v2.md`).
- 04-28 재학습본이 HF Hub에 배포되면 동일 측정 다시 수행 예정.

---

## 7. 재현 방법

검증 스크립트는 측정 후 폐기. 핵심 로직:

```python
from sklearn.model_selection import train_test_split
from transformers import AutoModelForSequenceClassification, AutoTokenizer

LABEL_LIST = ["일정", "준비물", "제출", "건강·안전", "기타"]
texts, labels = load_from_jsonl("model/extraction/data/notices_labeled_v2.jsonl")

train_t, val_t, train_y, val_y = train_test_split(
    texts, labels, test_size=0.2, random_state=42, stratify=labels,
)

# Base: head random init, no training
base = AutoModelForSequenceClassification.from_pretrained(
    "monologg/koelectra-base-v3-discriminator", num_labels=5,
)
# Fine-tuned: from HF Hub
ft = AutoModelForSequenceClassification.from_pretrained(
    "yunjeong116/koelectra-extractor", subfolder="koelectra-extractor",
)
# 양쪽 model.eval() 후 val_t에 inference, sklearn classification_report
```

---

## 8. 첨부

- 디스코드 팀방 공유 md (이 실험 자료의 외부 링크)
- 윤정 학습 노트: `model/extraction/docs/devlog-2026-04-28-v2.md` — 04-28 재학습 결과(0.85) 별도 측정 예정
