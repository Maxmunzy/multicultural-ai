# {실험 제목}

**날짜**: YYYY-MM-DD  
**영역**: extraction / classification / translation / tts / data / pipeline  
**담당**: {이름}  
**관련 PR/커밋**: {링크 또는 SHA}

---

## 1. 목적

이 실험으로 무엇을 입증하려 하는가? (한두 문장)

---

## 2. 데이터

| 항목 | 값 |
| --- | --- |
| 데이터셋 | {경로 또는 URL} |
| 샘플 수 | {N건} |
| 분할 | train: {N} / val: {N} / test: {N} |
| 분할 시드 | {random_state} |
| 라벨 분포 | {클래스별 카운트} |
| 전처리 | {적용된 전처리 단계 나열} |
| 증강 | {증강 기법 또는 "없음"} |

---

## 3. 모델 / 파이프라인

| 항목 | 값 |
| --- | --- |
| 베이스 모델 | {예: monologg/koelectra-base-v3-discriminator} |
| 파인튜닝 모델 | {예: yunjeong116/koelectra-extractor} |
| 후처리 | {예: 정규식 통화 보정} |
| 비교 대상 | {Random / Majority / Base / 다른 fine-tuned} |

---

## 4. 하이퍼파라미터

| 항목 | 값 |
| --- | --- |
| epochs | {N} |
| learning rate | {값} |
| LR 스케줄러 | {linear / cosine / 없음} |
| warmup | {ratio} |
| 손실 함수 | {CE / Weighted CE / 등} |
| 배치 사이즈 | {N} |
| max_length | {N} |
| device | {CPU / GPU} |
| seed | {값(들)} |

---

## 5. 결과

### 핵심 지표

| 메트릭 | 값 |
| --- | --- |
| accuracy | {값} |
| macro F1 | {값} |
| 추가 지표 | {값} |

### 비교 표

| 모델 | 지표 1 | 지표 2 | 비고 |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

### 클래스별 / 케이스별 결과

(필요 시 per-class 또는 per-case 표)

---

## 6. 인사이트 / 해석

- 무엇이 효과 있었는가
- 무엇이 효과 없었는가  
- 다음에 시도할 것 / 한계

---

## 7. 재현 방법

```bash
# 이 실험을 재현하려면
{커맨드 또는 노트북 경로}
```

---

## 8. 첨부

- 원본 결과 로그: {경로}
- 학습/추론 노트북: {경로}
- 추가 자료: {링크}
