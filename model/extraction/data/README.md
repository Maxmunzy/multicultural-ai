# model/extraction/data/

A단계(is_todo 추출) 및 is_title 분류기 학습에 사용하는 데이터 디렉토리.

---

## 폴더 구조

```text
data/
├── train/       학습 바로 쓰는 완성 데이터 — 라벨링 완료
├── processed/   전처리 완료, 라벨링 전 단계
├── draft/       라벨링 초안 — 검수 중
├── legacy/      v1·v2 구버전 데이터
├── samples/     소규모 샘플·추론 테스트용
└── txt/         원본 가정통신문 .txt 파일 모음
```

---

## 폴더별 파일

### `train/` — 학습용 완성 데이터

| 파일 | 크기 | 행 수 | 설명 |
| --- | --- | --- | --- |
| `v3_dual_labeled_clean.jsonl` | 4.7 MB | ~27,800 | **메인 학습 파일** — is_todo + is_title 이중 라벨, 정제 완료 |
| `v3_dual_labeled.jsonl` | 5.9 MB | 28,890 | 정제 전 이중 라벨 원본 (10자 미만·5000자 초과 포함) |
| `v3_dual_labeled_strict_yj.jsonl` | 5.9 MB | 28,890 | 윤정님 정의 기준 엄격 재정제 버전 |
| `label_sample.jsonl` | 28 KB | 206 | 골드 스탠다드 샘플 — `{text, is_todo, is_title}` |
| `v2.1_notices_galsan.jsonl` | 1.2 MB | — | `train_koelectra.ipynb` 학습 입력 (갈산학교, is_todo) |
| `notices_labeled_v2.jsonl` | 50 KB | — | v2 수동 라벨링 결과 |
| `train_data_preprocessed_v2.jsonl` | 11 KB | — | v2 전처리 완료 데이터 |

> **학습 시작점**: `v3_dual_labeled_clean.jsonl`

---

### `processed/` — 전처리 완료, 라벨링 전

| 파일 | 크기 | 행 수 | 설명 |
| --- | --- | --- | --- |
| `v3_school_dedup.jsonl` | 10 MB | 20,843 | dedup 완료 — `prepare_todo_labels.py` 입력용 |
| `v3_school.jsonl` | 15.6 MB | 35,219 | txt → JSONL 변환 원본 (중복 포함) |
| `v3_school_split_fixed_v2.jsonl` | 5.5 MB | — | 문장 분리 버그 수정 버전 |
| `v3_labeled.jsonl` | 16.6 MB | — | `auto_label.py` 초안 라벨 적용본 |

---

### `draft/` — 라벨링 초안 (검수 중)

| 파일 | 크기 | 행 수 | 설명 |
| --- | --- | --- | --- |
| `todo_labeled_draft_1500.jsonl` | 13.4 MB | 5,383 | Gemini 라벨링 1~1500행 결과 (draft rows) |
| `todo_test_500.jsonl` | 2.3 MB | 1,887 | Gemini 라벨링 1500~2000행 테스트 결과 |
| `v3_school_test_500.jsonl` | 200 KB | 500 | 테스트 입력 샘플 (1500~2000행) |

> **주의**: draft 데이터는 `review_required` 가 과다 표시됨. 학습에 직접 사용 금지.

---

### `legacy/` — 구버전

| 파일 | 크기 | 설명 |
| --- | --- | --- |
| `v2_notices_galsan.jsonl` | 1.2 MB | v2 갈산학교 데이터 |
| `v2.1_notices_galsan.jsonl` | (→ train/) | train/ 으로 이동됨 |
| `v1_notices_galsan.jsonl` | 388 KB | v1 갈산학교 데이터 |
| `notices_galsan.jsonl` | 931 KB | 최초 원본 갈산학교 |
| `notices_original2.jsonl` | 72 KB | 원본 가정통신문 문서 단위 |
| `notices_original2.csv` | 58 KB | 동일 데이터 CSV 버전 |

---

### `samples/` — 추론 테스트용

| 파일 | 설명 |
| --- | --- |
| `sample_pdfplumber.txt` | pdfplumber OCR 출력 샘플 |
| `sample_pymupdf.txt` | pymupdf OCR 출력 샘플 |

---

### `txt/` — 원본 .txt 파일

| 폴더 | 설명 |
| --- | --- |
| `galsan_txt/` | 갈산초등학교 가정통신문 (1행 복원 전) |
| `galsan_txt_1line/` | 갈산초등학교 (줄 끊김 복원 후) |
| `newschool2_txt/` | 신규 학교 2차 수집 |
| `newschools_txt/` | 신규 학교 1차 수집 |

---

## 데이터 전처리 흐름

```text
[1] 원본 txt
    txt/galsan_txt/
    txt/newschool2_txt/        ─→  preprocess_txt_to_jsonl.py
    txt/newschools_txt/

[2] 문장 단위 JSONL 변환
    processed/v3_school.jsonl (35,219행)

[3] 중복 제거 (text 완전 일치 기준)
    processed/v3_school_dedup.jsonl (20,843행)  ─14,376행 제거

[4] Gemini 라벨링  ←  prepare_todo_labels.py --use_gemini_segment
    초안: draft/todo_labeled_draft_1500.jsonl
    (API 한도 초과 — 나머지 19,343행 재처리 예정)

[5] 이중 라벨 완성  {text, is_todo, is_title}
    train/v3_dual_labeled.jsonl (28,890행)

[6] 정제  ←  clean_labeled_data.py
    10자 미만 1,078행 + 5,000자 초과 13행 제거
    train/v3_dual_labeled_clean.jsonl (~27,800행)  ← 최종 학습 입력
```

---

## 학습 데이터 포맷

```json
{"text": "4월 30일까지 동의서를 제출해주세요.", "is_todo": true,  "is_title": false}
{"text": "2026 해원 놀이 한마당 안내",           "is_todo": false, "is_title": true}
{"text": "학부모님 안녕하십니까?",               "is_todo": false, "is_title": false}
```

| 라벨 | 설명 | 비율 |
| --- | --- | --- |
| `is_todo=true` | 학부모가 행동해야 할 문장 | 27% |
| `is_title=true` | 통신문 제목 문장 | 1.8% |

---

## 관련 스크립트

| 스크립트 | 역할 |
| --- | --- |
| `file/preprocess_txt_to_jsonl.py` | txt → JSONL 변환 |
| `file/auto_label.py` | 규칙 기반 is_todo 초안 라벨링 |
| `scripts/prepare_todo_labels.py` | Gemini 세그멘테이션 + is_todo·is_title 이중 라벨 |
| `scripts/clean_labeled_data.py` | 학습 부적합 행 정제 |
| `file/train_koelectra.ipynb` | is_todo 분류기 학습 (Colab) |
| `file/train_koelectra_title.ipynb` | is_title 분류기 학습 (Colab) |
