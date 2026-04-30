# 모델 A — 추출 파이프라인 (A단계: 이진 분류 + B단계: 카테고리 분류)

**담당: 윤정** · `model/extraction/` · KoELECTRA fine-tuned

---

## 한 줄 요약

> 가정통신문 원문 텍스트를 넣으면, 학부모가 실행해야 할 **후보 문장 리스트**가 나옵니다 (B단계 입력용).

---

## 2단계 구조

```text
┌──────────────────────────────────────────────────────────────┐
│                  가정통신문 원문 텍스트 (OCR 출력)            │
└─────────────────────────┬────────────────────────────────────┘
                          │
        ┌─────────────────▼──────────────────┐
        │          A단계 — 윤정 담당           │
        │      file/predict.py               │
        │                                    │
        │  ① split_sentences()               │
        │    줄바꿈 복원 + 문장 분리           │
        │    (헤더·OCR 노이즈 조기 차단)       │
        │                                    │
        │  ② is_likely_todo()                │
        │    정규식 1차 필터                  │
        │    → KoELECTRA 이진 분류            │
        │      0: 노이즈  1: 할 일·중요 일정   │
        │                                    │
        │  ③ extract_due_date()              │
        │     extract_amount()               │
        │     extract_action_hint()          │
        │    정규식으로 날짜·금액·행동 추출    │
        └─────────────────┬──────────────────┘
                          │
             list[dict] — B단계 입력 스키마
             {"text", "source", "due_date",
              "amount", "confidence", "action_hint"}
                          │
        ┌─────────────────▼──────────────────┐
        │          B단계 — 경이 담당           │
        │   KoELECTRA 5-class 카테고리 분류   │
        │   (제출·준비물·건강·안전·비용·일정·기타) │
        └────────────────────────────────────┘
```

---

## 기술 스택

| | |
| --- | --- |
| A단계 모델 | KoELECTRA-small-v3 이진 분류 (`checkpoints/koelectra-binary/`) |
| B단계 모델 | KoELECTRA-base-v3 5-class · `yunjeong116/koelectra-extractor` |
| 날짜 / 금액 | 정규식 (regex) |
| 실행 환경 | CPU / GPU 자동 선택 |
| 의존성 | `torch` · `transformers` · `huggingface_hub` · `sklearn` |

> **이전 → 현재:** Llama-3-Korean 8B (Colab T4, 4-bit 양자화) → KoELECTRA 하이브리드  
> 추론 속도 ↑, 서버 배포 용이성 ↑

---

## 카테고리 & 중요도 (B단계)

| 카테고리 | 설명 | 기본 점수 |
| --- | --- | --- |
| `제출` | 서류 · 동의서 · 과제 | **1.00** |
| `준비물` | 지참물 안내 | 0.85 |
| `건강·안전` | 건강 · 안전 사항 | 0.80 |
| `비용` | 금액 포함 항목 (정규식) | 0.75 |
| `일정` | 행사 · 일정 안내 | 0.70 |
| `기타` | 위 외 항목 | 0.50 |

긴급 키워드(`반드시`, `마감`, `즉시` 등) 포함 시 +0.05 / due_date 있을 시 +0.05

---

## 모델 성능 (B단계 카테고리 분류기)

### v2 재학습 결과 (2026-04-28 · 15 epoch · cosine LR · WeightedCrossEntropy)

```text
              precision    recall  f1-score   support

          일정     1.0000    1.0000    1.0000         4
         준비물     1.0000    0.5000    0.6667         4
          제출     0.8000    1.0000    0.8889         4
       건강·안전     0.8571    0.8571    0.8571         7
          기타     0.5000    1.0000    0.6667         1

    accuracy                         0.8500        20
   macro avg     0.8314    0.8714    0.8159        20
weighted avg     0.8850    0.8500    0.8444        20
```

### v1 → v2 비교

| 지표 | v1 (10 epoch) | v2 (15 epoch) | 변화 |
| ------ | -------------- | -------------- | ------ |
| **accuracy** | 0.7500 | **0.8500** | +0.10 ✅ |
| **macro F1** | 0.5988 | **0.8159** | +0.22 ✅ |
| 기타 F1 | 0.0000 | **0.6667** | 완전 회복 ✅ |

> MVP 목표 (accuracy ≥ 0.80, macro F1 ≥ 0.75) 달성  
> 학습 파라미터: `num_train_epochs=15`, `lr=2e-5`, `scheduler=cosine`, `warmup_ratio=0.1`, `WeightedCrossEntropy(balanced)`

---

## 버그 수정 이력 (2026-04-27)

| # | 현상 | 원인 | 수정 |
| --- | ------ | ------ | ------ |
| Bug 1 | 인사말이 TODO로 잡힘 | `NON_TODO_PATTERNS`에 `안녕하세요` 미포함 | 패턴 3개 추가 |
| Bug 2 | NLLB 첫 번역 문장 어색 | 제목 줄이 인사말과 합쳐져 번역 전달 | `_HEADER_ONLY` 필터 추가 |
| Bug 3 | `원→won` 오탐 | `원하시는`, `원인` 등 substring 매칭 | `MONEY_PATTERN`에 숫자 선행 조건 강제 |

---

## 파일 구성

```text
model/extraction/
├── fill_original2.py              ← notices_original2.jsonl 자동 채우기 스크립트
├── file/
│   ├── predict.py                 ← A단계 메인 파이프라인 (백엔드 진입점)
│   ├── evaluate_model.py          ← Base vs Fine-tuned 성능 비교 (강사 제출용)
│   ├── preprocess_txt_to_jsonl.py ← PDF txt → JSONL 변환 (문장 단위, 라벨링용)
│   └── txt_to_jsonl.py            ← PDF txt → JSONL 변환 (문서 단위)
├── data/
│   ├── notices_labeled_v2.jsonl   ← 학습 라벨 데이터 (100문장, is_todo + original_id)
│   ├── notices_original2.jsonl    ← 원문 27장 + category/keywords/importance 자동 채우기
│   ├── notices_original2.csv      ← CSV 버전
│   └── galsan_txt/                ← 갈산초 가정통신문 txt 원본 (~100건)
├── checkpoints/
│   └── koelectra-extractor/       ← B단계 5-class 카테고리 분류 체크포인트 (Hub 백업)
├── docs/
│   ├── devlog-2026-04-27.md       ← Bug 수정 3종 + 학습 파라미터 개선
│   ├── devlog-2026-04-28.md       ← notices_original2.jsonl 자동 채우기 작업
│   └── devlog-2026-04-28-v2.md    ← v2 재학습 결과 (accuracy 0.85 달성)
└── x/                             ← 구버전 보관 (Llama Few-shot + 구 predict.py)
    ├── MODEL.py
    ├── predict.py
    ├── notices_labeled_v2.csv
    └── extracted_results.json
```

---

## A단계 출력 예시 (`file/predict.py`)

B단계(경이 모델) 입력 스키마:

```json
[
  {
    "text":        "개인용 이어폰(3.5mm) 4월 20일까지 준비해 주세요.",
    "source":      "sample.txt",
    "due_date":    "2026-04-20",
    "amount":      null,
    "confidence":  0.9312,
    "action_hint": "준비"
  },
  {
    "text":        "구입비는 5,000원 이내의 잔돈으로 준비합니다.",
    "source":      "sample.txt",
    "due_date":    null,
    "amount":      5000,
    "confidence":  0.8741,
    "action_hint": "준비"
  }
]
```

---

## 실행

### A단계 추출 (직접 테스트)

```bash
pip install torch transformers
python model/extraction/file/predict.py
```

### 모델 성능 평가 (Base vs Fine-tuned 비교)

```bash
pip install scikit-learn pandas
python model/extraction/file/evaluate_model.py
# 테스트 데이터 직접 지정 시:
python model/extraction/file/evaluate_model.py --test_data data/test_data.jsonl
```

### txt → JSONL 변환 (데이터 전처리)

```bash
# 문서 단위 (notices_original2.jsonl 스키마)
python model/extraction/file/txt_to_jsonl.py \
    --input data/galsan_txt/*.txt \
    --output data/notices_original2.jsonl \
    --source_type 초등학교

# 문장 단위 (학습 라벨링용)
python model/extraction/file/preprocess_txt_to_jsonl.py \
    --input_dir data/galsan_txt \
    --output data/notices_labeled.jsonl
```

### notices_original2.jsonl 자동 채우기

```bash
python model/extraction/fill_original2.py
```

멱등성 보장 — 재실행 시 항상 재계산하여 덮어씀.

---

## 백엔드 연동

```python
from model.extraction.file.predict import predict

# A단계: 후보 문장 추출 → B단계 입력
candidates = predict(notice_text, source="파일명.pdf")
# [{"text", "source", "due_date", "amount", "confidence", "action_hint"}, ...]
```

모델은 첫 호출 시 로컬 체크포인트(`checkpoints/koelectra-binary/`)를 우선 로드하고,  
없으면 HuggingFace Hub(`yunjeong116/koelectra-extractor`)에서 자동 다운로드합니다.

---

## 데이터 구성

| 파일 | 내용 | 건수 |
| ------ | ------ | ------ |
| `notices_labeled_v2.jsonl` | 문장 단위 라벨 (is_todo + category + original_id) | 100문장 (N01~N19) |
| `notices_original2.jsonl` | 원문 문서 단위 + category/keywords/importance | 27건 |
| `galsan_txt/` | 갈산초 가정통신문 원본 txt | ~100건 |

> `notices_labeled_v2.jsonl`의 `original_id` 필드로 원문(`notices_original2.jsonl`)과 연결 가능.  
> N16~N19(알림장 4건)는 27장 원문 미포함 → `original_id: null`.

---

## 잔존 한계 및 향후 작업

| 항목 | 내용 |
| ------ | ------ |
| 준비물 recall 0.50 | 4개 중 2개 오분류. 데이터 추가 시 개선 여지 있음 |
| 기타 support=1 | 검증셋 샘플 1개 → F1 신뢰도 낮음. 가상 데이터 증강 필요 |
| 전체 샘플 100개 | 데이터 절대량 부족. 가상 데이터 추가 후 3차 학습 예정 (목표: 준비물·기타 F1 ≥ 0.70) |
| Binary 체크포인트 | `checkpoints/koelectra-binary/` 미배포 상태 — Colab 재학습 후 교체 필요 |
