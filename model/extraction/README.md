# 모델 A — 추출 파이프라인 (A단계: 이진 분류 + 제목 감지)

**담당: 윤정** · `model/extraction/` · KoELECTRA fine-tuned

---

## 한 줄 요약

> 가정통신문 원문 텍스트를 넣으면, 학부모가 실행해야 할 **후보 문장 리스트**가 나옵니다 (B단계 입력용).

---

## 파이프라인 구조

```text
┌──────────────────────────────────────────────────────────────┐
│                  가정통신문 원문 텍스트 (OCR 출력)            │
└─────────────────────────┬────────────────────────────────────┘
                          │
        ┌─────────────────▼──────────────────┐
        │          A단계 — 윤정 담당           │
        │      file/predict.py               │
        │                                    │
        │  [0] extract_title()               │
        │    제목 감지 (heuristic + 모델)      │
        │    split_sentences() 이전에 실행    │
        │                                    │
        │  [1] split_sentences()             │
        │    줄바꿈 복원 + 문장 분리           │
        │    (헤더·OCR 노이즈 조기 차단)       │
        │                                    │
        │  [2] is_likely_todo()              │
        │    정규식 1차 필터                  │
        │    → KoELECTRA 이진 분류            │
        │      threshold 0.65               │
        │      0: 노이즈  1: 할 일·중요 일정   │
        │                                    │
        │  [3] extract_due_date()            │
        │      extract_amount()              │
        │      extract_action_hint()         │
        │    정규식으로 날짜·금액·행동 추출    │
        └─────────────────┬──────────────────┘
                          │
             list[dict] — B단계 입력 스키마
             {"text", "source", "due_date",
              "amount", "confidence", "action_hint"}
                          │
        ┌─────────────────▼──────────────────┐
        │          B단계 — 경이 담당           │
        │   KoELECTRA 카테고리 분류           │
        │   (제출·준비물·건강·안전·비용·일정·기타) │
        └────────────────────────────────────┘
```

---

## 기술 스택

| | |
| --- | --- |
| A단계 모델 | KoELECTRA-small-v3 이진 분류 (`checkpoints/koelectra-binary/`) |
| 제목 감지 | heuristic fallback (`checkpoints/koelectra-title/` 있으면 모델 우선) |
| B단계 모델 | KoELECTRA 카테고리 분류 · `checkpoints/koelectra-extractor/` |
| 날짜 / 금액 | 정규식 (regex) |
| 실행 환경 | CPU / GPU 자동 선택 |
| 의존성 | `torch` · `transformers` · `huggingface_hub` · `scikit-learn` |

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

## 모델 성능

### A단계 이진 분류기 — v2 베이스라인 (2026-04-30 확정)

평가 기준: `data/train/v2.1_notices_galsan.jsonl` (갈산초 데이터 분포)

| 지표 | 값 |
| --- | --- |
| Precision | 0.9067 |
| Recall | 0.9589 |
| **F1** | **0.9321** |
| FN (놓침) | 30개 |
| FP (오탐) | 72개 |
| BINARY_THRESHOLD | **0.65** (최적값 적용) |

> 신청기간/운영시간 패턴이 학습·평가 데이터 모두에 없어 수치 높게 측정됨.  
> v3 고정 테스트셋(`data/draft/todo_test_500.jsonl`) 기준 재평가 시 변동 예상.

### B단계 카테고리 분류기 — v2 (2026-04-28 · 15 epoch · cosine LR · WeightedCrossEntropy)

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

| 지표 | v1 (10 epoch) | v2 (15 epoch) | 변화 |
| ------ | -------------- | -------------- | ------ |
| **accuracy** | 0.7500 | **0.8500** | +0.10 ✅ |
| **macro F1** | 0.5988 | **0.8159** | +0.22 ✅ |
| 기타 F1 | 0.0000 | **0.6667** | 완전 회복 ✅ |

> MVP 목표 (accuracy ≥ 0.80, macro F1 ≥ 0.75) 달성

---

## 버그 수정 이력

| 날짜 | # | 현상 | 원인 | 수정 |
| --- | --- | ------ | ------ | ------ |
| 04-27 | 1 | 인사말이 TODO로 잡힘 | `NON_TODO_PATTERNS`에 `안녕하세요` 미포함 | 패턴 3개 추가 |
| 04-27 | 2 | NLLB 첫 번역 문장 어색 | 제목 줄이 인사말과 합쳐져 번역 전달 | `_HEADER_ONLY` 필터 추가 |
| 04-27 | 3 | `원→won` 오탐 | `원하시는`, `원인` 등 substring 매칭 | `MONEY_PATTERN`에 숫자 선행 조건 강제 |
| 04-29 | 4 | `preprocess` predict 경로 오류 | `_HERE.parent / "predict.py"` 경로 잘못됨 | `_HERE / "predict.py"` 로 수정 |
| 04-29 | 5 | 급식 파일 과잉 스킵 | 파일명에 "급식" 키워드 있으면 무조건 스킵 | 내용 기반 패턴만 사용 |
| 04-29 | 6 | `predict.py` 경로·체크 오류 3건 | `_LOCAL_CHECKPOINT_DIR` 경로, `_local_ready`, `_join_broken_lines()` 미적용 | 각각 수정 |
| 04-30 | 7 | URL·전화·시간 범위 과잉 차단 | `_OCR_LINE_NOISE` 패턴에 anchor 없어 본문 중간도 차단 | 모든 패턴에 `^` anchor / `$` 추가 |
| 04-30 | 8 | 리스트 항목 묶음 처리 | 마침표 없이 이어진 항목이 하나의 문장으로 처리 | 리스트 마커·반복 레이블 앞 분리 규칙 추가 |
| 04-30 | 9 | Distribution shift | 학습은 기호 정제 적용, 추론은 미적용 | 추론 단계에도 `_clean_symbols()` 추가 |
| 05-01 | 10 | 한국식 날짜 분절 | `2025.\n4.\n20` 이 3문장으로 분리 | `join_broken_lines` 규칙 추가 |
| 05-01 | 11 | whitelist 미적용 | `\|`·`～` 등 수백 종 기호 잔류 | 기호 정제 whitelist 방식으로 전면 교체 |

---

## 파일 구성

```text
model/extraction/
├── fill_original2.py              ← (legacy) notices_original2.jsonl 자동 채우기
│
├── file/
│   ├── predict.py                 ← A단계 메인 파이프라인 (백엔드 진입점)
│   ├── auto_label.py              ← 규칙 기반 is_todo 초안 라벨러
│   ├── evaluate_model.py          ← Base vs Fine-tuned 성능 비교
│   ├── preprocess_txt_to_jsonl.py ← PDF txt → JSONL 변환 (문장 단위, 라벨링용)
│   ├── txt_to_jsonl.py            ← PDF txt → JSONL 변환 (문서 단위)
│   ├── train_koelectra.ipynb      ← KoELECTRA 이진 분류 학습 노트북 (Colab)
│   ├── evaluate_hf_model.ipynb    ← HuggingFace 모델 성능 평가 노트북
│   └── requirements-extraction.txt ← 의존성 목록
│
├── checkpoints/
│   ├── koelectra-binary/          ← A단계 이진 분류 체크포인트 (53.9 MB, 현재 모델)
│   ├── koelectra-binary-v2/       ← A단계 이전 버전 (비교용)
│   └── koelectra-extractor/       ← B단계 카테고리 분류 (Hub 백업)
│
├── data/
│   ├── README.md                  ← 데이터 폴더 상세 설명
│   ├── train/                     ← 학습용 완성 데이터
│   │   ├── v3_dual_labeled_clean.jsonl   ← 메인 학습 파일 (~27,800문장)
│   │   ├── v3_dual_labeled_strict_yj.jsonl
│   │   ├── v3_dual_labeled.jsonl
│   │   ├── v2.1_notices_galsan.jsonl     ← 갈산초 데이터 (5,475문장, 730 True)
│   │   ├── train_data_preprocessed_v2.jsonl
│   │   ├── notices_labeled_v2.jsonl      ← 초기 라벨 데이터 (100문장)
│   │   ├── test_data.jsonl
│   │   └── label_sample.jsonl
│   ├── processed/                 ← 전처리 완료, 라벨링 전
│   │   ├── v3_school.jsonl               ← txt → JSONL 변환 원본 (35,219문장)
│   │   ├── v3_school_dedup.jsonl         ← 중복 제거 완료 (20,843문장)
│   │   ├── v3_school_split_fixed_v2.jsonl
│   │   ├── v3_labeled.jsonl              ← 초안 라벨 포함
│   │   └── predict_output_testset.jsonl
│   ├── draft/                     ← 라벨링 초안 (검수 중)
│   │   ├── todo_labeled_draft_1500.jsonl
│   │   ├── todo_test_500.jsonl
│   │   └── v3_school_test_500.jsonl
│   ├── legacy/                    ← 구버전 데이터
│   │   ├── notices_original2.jsonl
│   │   ├── notices_original2.csv
│   │   ├── notices_galsan.jsonl
│   │   ├── v1_notices_galsan.jsonl
│   │   └── v2_notices_galsan.jsonl
│   ├── samples/                   ← 추론 테스트용 샘플
│   │   ├── sample_pdfplumber.txt
│   │   └── sample_pymupdf.txt
│   └── txt/                       ← 원본 .txt 파일 모음
│       ├── galsan_txt/            ← 갈산초 원본 (전처리 전)
│       ├── galsan_txt_1line/      ← 갈산초 줄 끊김 복원 후 (~100건)
│       ├── newschools_txt/        ← 신규 학교 1차 수집 (~790건)
│       └── newschool2_txt/        ← 신규 학교 2차 수집 (~625건)
│
├── docs/
│   ├── devlog-model-a.md          ← A단계 개발일지 (최신 순)
│   ├── devlog-2026-05-01.md       ← v3 데이터 전처리 + auto_label.py
│   ├── devlog-2026-04-28-v2.md    ← v2 재학습 결과 (accuracy 0.85)
│   ├── devlog-2026-04-28.md       ← notices_original2.jsonl 자동 채우기
│   ├── devlog-2026-04-27.md       ← 버그 수정 3종
│   ├── labeling-guide.md          ← is_todo 라벨링 기준 문서
│   └── troubleshooting-2026-04-29.md
│
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
pip install torch transformers huggingface_hub
python model/extraction/file/predict.py
```

### 모델 성능 평가 (Base vs Fine-tuned 비교)

```bash
pip install scikit-learn pandas
python model/extraction/file/evaluate_model.py
# 테스트 데이터 직접 지정 시:
python model/extraction/file/evaluate_model.py --test_data data/train/test_data.jsonl
```

### txt → JSONL 변환 (데이터 전처리)

```bash
# 문장 단위 (학습 라벨링용)
python model/extraction/file/preprocess_txt_to_jsonl.py \
    --input_dir data/txt/galsan_txt_1line \
    --output data/processed/v3_school.jsonl

# 문서 단위 (notices_original2 스키마)
python model/extraction/file/txt_to_jsonl.py \
    --input data/txt/galsan_txt_1line/*.txt \
    --output data/legacy/notices_original2.jsonl \
    --source_type 초등학교
```

### 규칙 기반 is_todo 초안 라벨링

```bash
python model/extraction/file/auto_label.py \
    --input data/processed/v3_school_dedup.jsonl \
    --output data/processed/v3_labeled.jsonl
```

---

## 백엔드 연동

```python
from model.extraction.file.predict import predict, extract_title

# 제목 추출 (선택)
title = extract_title(notice_text)

# A단계: 후보 문장 추출 → B단계 입력
candidates = predict(notice_text, source="파일명.pdf")
# [{"text", "source", "due_date", "amount", "confidence", "action_hint"}, ...]
```

모델은 첫 호출 시 로컬 체크포인트(`checkpoints/koelectra-binary/`)를 우선 로드하고,  
없으면 HuggingFace Hub(`yunjeong116/koelectra-extractor`)에서 자동 다운로드합니다.

---

## 데이터 구성

### 학습 데이터 전처리 흐름

```text
원본 .txt
  갈산초 (281개) + 신규학교 (1,415개)
    ↓ preprocess_txt_to_jsonl.py
  processed/v3_school.jsonl (35,219문장, is_todo:false)
    ↓ 중복 제거
  processed/v3_school_dedup.jsonl (20,843문장)
    ↓ auto_label.py (규칙 기반 초안)
  processed/v3_labeled.jsonl (True 3,387 / False 31,832)
    ↓ 수동 검수
  train/v3_dual_labeled_clean.jsonl (~27,800문장, 최종 학습)
    ↓ train_koelectra.ipynb
  checkpoints/koelectra-binary/ (53.9 MB)
```

### 주요 파일 규모

| 파일 | 건수 | 설명 |
| ------ | ------ | ------ |
| `train/v3_dual_labeled_clean.jsonl` | ~27,800문장 | 메인 학습 데이터 (최종) |
| `processed/v3_school.jsonl` | 35,219문장 | 신규 학교 전처리 원본 |
| `processed/v3_school_dedup.jsonl` | 20,843문장 | 중복 제거 완료 |
| `train/v2.1_notices_galsan.jsonl` | 5,475문장 | 갈산초 (730 True) |
| `train/notices_labeled_v2.jsonl` | 100문장 | 초기 라벨 데이터 (N01~N19) |
| `txt/galsan_txt_1line/` | ~100건 | 갈산초 원본 txt |
| `txt/newschools_txt/` + `txt/newschool2_txt/` | 1,415건 | 신규 학교 원본 txt |

---

## 잔존 한계 및 향후 작업

| 항목 | 현황 | 목표 |
| ------ | ------ | ------ |
| 준비물 recall 0.50 | 4개 중 2개 오분류 | 데이터 추가 시 개선 여지 있음 |
| 기타 support=1 | 검증셋 샘플 1개 → F1 신뢰도 낮음 | 가상 데이터 증강 필요 |
| 신청기간/운영시간 패턴 | 모델이 confidence 0.05 미만으로 전부 컷 | `data/draft/` 에 50개 이상 추가 후 재학습 |
| v3 고정 테스트셋 미확정 | `todo_test_500.jsonl` 검수 중 | 100~200문장 확정 후 v2 베이스라인과 비교 |
| True 샘플 730개 | 재학습 데이터 부족 | 1,500개 이상 확보 후 v3 재학습 |
