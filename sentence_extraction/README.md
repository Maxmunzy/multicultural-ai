# Sentence Extraction — 1단계 자체화 PoC

가정통신문 1단계(`sentence_list` 추출)를 외부 LLM(Claude Haiku 4.5)에서 자체 모델로 옮기기 위한 비교 검증 노트북·스크립트 보존소. 발표 §3-4 「자체화 시도 흔적」의 근거.

## 검증 이력

| 노트북·스크립트 | 접근 | 결과 | 결론 |
| --- | --- | --- | --- |
| `lilt_sentence_grouping_colab.ipynb` | LiLT (140M, text+bbox) | 셔플 정확도 43.3% | bbox만으론 layout 학습 불가 |
| `layoutxlm_sentence_grouping_colab.ipynb` | LayoutXLM (360M, +image stream) | 셔플 정확도 78.8% | image stream이 layout 학습에 결정적 |
| `layoutxlm_train_test_split_colab.ipynb` | LayoutXLM 4장 train / 2장 test | 일반화 9.7% | `sentence_id` task 한계 → BIO 의미 라벨 재설계 필요 |
| `sat_sentence_segmentation_colab.ipynb` | SaT (Segment Any Text, text only) | 변형 0 ✓, but 단어 끊김 누락 5~10% | text-only 한계, bbox 후처리 또는 학습 모델 필요 |
| `build_kd_data.py` + `kobert_kd_train_colab.ipynb` | **Knowledge Distillation** (Claude Teacher → KLUE-BERT Student) | val F1 0.69~0.71 (plateau) | end-to-end 평가 필요 — F1 ≠ 사용자 경험 |

> **셔플 검증**: 토큰 순서를 무작위로 섞어 시퀀스 신호를 제거한 뒤, 모델이 진짜 layout을 학습하는지(bbox·image만으로 분류 가능한지) 측정하는 방식.

## Knowledge Distillation 시도 (2026-05-19)

### 접근

```text
PDF
 ↓ pdfplumber bbox 추출 (build_kd_data.extract_rows)
 ↓ 행 페어 (cur_row, next_row)
 ↓
Claude Haiku 4.5 Teacher  ──(직접 페어 라벨링, --mode direct)──→  merge(1) / split(0)
 ↓
KLUE-BERT Student (binary classification)
 ↓
[CLS] cur_row [SEP] next_row [SEP] → merge / split

학습된 모델로 인접 행 페어 분류 → 연속 merge 행을 sentence 그룹으로 묶음 (transitive)
```

### 데이터 라벨링 — Claude `--mode direct`

`build_kd_data.py`로 자동 생성:

- pdfplumber `extract_words(use_text_flow=True, x_tolerance=3, y_tolerance=3)` + y좌표 ±2pt 묶기 → 행
- 한 PDF 행 목록을 Claude에게 한 번에 보내고 N-1개 페어 라벨 받음 (1 호출, 1~2초)
- `--mode sentence` (sentence_list 매칭) 대비 5배 더 풍부한 merge 라벨 (45.9% vs 8.9%)

**최종 학습 데이터**: `data/kd_train_full.jsonl` — 44장 PDF, **2289 페어** (merge 28%, split 72%)

- 기존 PoC 6장 (가정통신문, 도서관·구강검진·체험학습 등)
- 성남초 16장 + 태평초 30장 (라벨링 성공분만)

**변형 0 보장 검증** ✓:

- 44장 PDF 전체에서 페어 데이터의 글자가 PDF 원본 글자에 100% 포함됨
- Claude가 만들어낸 글자·환각·변형 0건
- 일부 PDF에서 누락은 발생 (대형 매뉴얼의 표·도형 영역) — 양적 손실이지 변형 아님

### 학습 (KLUE-BERT base + binary head)

`kobert_kd_train_colab.ipynb` — 코랩 T4 GPU, KLUE-BERT base 110M.

| 회차 | 데이터 | 페어 | merge % | val F1 |
| --- | --- | --- | --- | --- |
| 1차 | 6장 (가정통신문 only) | 257 | 45.9% | **0.714** |
| 2차 | +성남 16장 (큰 문서 포함) | 1359 | 34.0% | 0.643 (악화) |
| 3차 | 필터링 16장 (페어 100+ 제외) | 687 | 37.4% | 0.714 |
| **4차** | **+태평 30장 (전체 44장)** | **2289** | **28.0%** | **0.689** |

### 결과 해석 — F1 plateau

- 데이터를 257 → 2289로 8.9배 늘렸지만 val F1은 0.69~0.71에서 정체
- 에폭·class_weights·도메인 다양성 조정으로도 큰 향상 어려움 예상
- 본질적 한계 추정:
  1. **라벨 모호성**: 일부 페어는 Claude도 헷갈리는 케이스 (같은 topic but 별도 문장 등)
  2. **페어 분류 ≠ sentence_list 정확도**: N=30 페어 모두 정답일 확률 ≈ 0.87³⁰ = 1.5%
  3. **KD 누적 노이즈**: Claude 자체가 100% 아닌데 그 85%를 모방
- 그러나 학습된 모델이 backend 통합 시 어떻게 동작할지는 별개:
  - KoELECTRA가 어차피 todo만 골라내므로 일부 누수 흡수 가능
  - **F1 0.689 = 페어 분류 정확도, 사용자 경험과 다름**

### End-to-End 평가 결과 (2026-05-20)

```text
PoC PDF 6장에 대해:
  A. Claude → sentence_list → KoELECTRA → todo (현재 backend)
  B. pdfplumber → KoBERT → sentence_list → KoELECTRA → todo (자체화)
```

| 지표 | 결과 |
| --- | --- |
| 평균 todo recall (substring 매칭) | 80.2% |
| 평균 todo precision | 82.2% |
| 실제 recall (substring inflation 감안) | 60-75% 추정 |
| 속도 비율 | KoBERT 34s vs Claude 24s (1.4x slower) |

substring 매칭 trap 식별 — KoBERT가 여러 Claude sentence를 한 sentence로 묶을 때 substring 매칭이 false positive 생성. 진짜 정확도는 substring보다 낮음. KoBERT KD 라인은 plateau 확정 → **PointerDoc으로 방향 전환**.

---

## PointerDoc 시도 (2026-05-20 ~ 21)

### 접근 — DCGAN 철학, End-to-End PDF → sentence_list

```text
페이지 PNG (pdf2image)
  ↓
DINOv2-small (22M, FROZEN)  ← vision backbone
  ↓ vision tokens
KoCharELECTRA-small (14M, FROZEN)  ← Korean char-level text encoder
  ↓ row text features
pdfplumber bbox + 2D PE  ← bbox feature
  ↓
row tokens (B, R, D) ── 256d 통합 임베딩
  ↓
32 sentence queries → Transformer Decoder (4 layer)
  ↓
  ┌─ Activity head: 각 query active 여부 (sigmoid)
  └─ Pointer head: 각 query × row score (sigmoid → row_ids)
  ↓
sentence_text = " ".join(rows[i] for i in row_ids)  ← 변형 0 구조적 보장
```

**학습 파라미터**: ~5M (frozen backbone 36M 제외). 변형 0은 **decoder output vocabulary가 row index만**이라 구조적으로 보장.

### 데이터 수집 — 6장 → 2,745장

| 단계 | PDF 수 | 행 수 | sentence 수 |
| --- | --- | --- | --- |
| 1차 (PoC + 성남·태평) | 1,371 | - | - |
| **2차 (+ extra_405 + extra_1033 + HWP→PDF 변환 +986)** | **2,745** | - | - |

- HWP/HWPX → PDF 변환: LibreOffice + H2Orestart, 1,020장 변환 (99% 성공)
- PNG 렌더링: pymupdf, 9,097 페이지 (longer side 518px)

### 라벨 매핑 알고리즘 진화

| 버전 | 알고리즘 | 매칭률 | 노이즈 |
| --- | --- | --- | --- |
| fuzzy (v1) | char-set overlap, 한 row가 sentence chars의 65%+ 포함 | 17K / 47% fuzzy added | 짬뽕 多 (행 순서 무시, 표 짬뽕) |
| **sequential v2** | **Bidirectional Jaccard + Minimal contiguous range + cursor monotonic** | **30K** | **짬뽕 0건, 1:1 매칭 95%+** |

### 학습 회차

| 회차 | 학습 데이터 | trainable | epochs | best val | 평가 best F1 (v2 평가셋 기준) |
| --- | --- | --- | --- | --- | --- |
| v1 | 17K fuzzy | 5M | 20 | 0.999 | 0.467 (R 0.554, P 0.470) |
| **v2 (resume)** | 17K fuzzy | 5M | +20 | 0.969 | **0.492 (R 0.551, P 0.521)** |
| v3 | **30K sequential** | 5M | 20 | 0.961 | 0.476 (R 0.542, **P 0.560**) |
| C (capacity ↑) | 17K fuzzy | **20M** | 30 | 0.961 | (실패: 작은 모델 v2가 더 좋음) |

**Fair 비교 (같은 평가셋 = v2 sequential, n=203 val PDFs)**:

- v2 최고 F1 0.492 — fuzzy 학습으로도 충분
- v3 최고 Precision 0.560 — 깨끗한 라벨이 출력 신뢰도 ↑
- 데이터 quality·양 효과 매우 제한적 (F1 ±0.025)

### 결과 해석 — 모델 아키텍처 한계

| 지표 | PointerDoc v2 | 의미 |
| --- | --- | --- |
| 변형 0 보장 | ✓ 구조적 | pointer mechanism — 환각 불가능 |
| 속도 | 0.9초/페이지 (CPU) | Claude (15s) 대비 **16배 빠름** |
| Sentence F1 | 0.49 | ceiling 도달 (data quality·량 늘려도 안 오름) |

PoC PDF 정성 분석 (학습 데이터 포함 PDF조차):

- 중복 출력 (같은 sentence 여러 query가 잡음) — query diversity 학습 신호 부족
- 표 행 짬뽕 (여러 표 셀이 한 sentence) — row-level pointer가 표 의미 단위 못 잡음
- 단어 순서 깨진 row (HWP→PDF 변환 artifact) — fuzzy 라벨 노이즈 학습으로 짬뽕 출력

**진단**: 5M trainable 파라미터로는 의미 단위 sentence boundary 학습 어려움. 본질적 해결은 **모델 아키텍처 변경 또는 후처리 모델 추가** 필요.

### 다음 단계 후보

| 옵션 | 내용 | 기대 |
| --- | --- | --- |
| Char-level BIO splitter | KoCharELECTRA-small + B-SENT/I-SENT/O 분류, PointerDoc 후처리로 통합 | sentence 분리 자연스러움 |
| KoBERT KD를 PointerDoc 텍스트 인코더로 채택 | 두 모델 합치기 — row embedding이 sentence-aware | F1 0.60+ 가능 |
| Multi-task PointerDoc | pointer + pair classifier head 추가, joint training | 모델 완전 통합 |
| Todo recall로 가치 metric 측정 | sentence boundary 무시, KoELECTRA 통과 후 todo recall만 평가 | KoBERT KD (80%)와 직접 비교 가능 |

---

## 2026-05-21 작업 일지

PointerDoc 폐기 후 새 방향 (BIO + 표 룰) 완성 → v2 BIO 실험 실패 → LayoutXLM 통합 모델 실험 실패. 두 가설 검증 + 진단 확정.

### 완료 작업

1. **Parser ensemble 강화 (`parser_ensemble.py`)**
   - 본문 parsers: pymupdf + pdfplumber + pdfminer.six 병렬 실행 + rule-based selection (avg row length, short ratio, terminator ratio, newline ratio)
   - 표 처리 (`_table_to_sentences`):
     - **col/row-major orientation 자동 판별** — cell 길이 분산 통계 기반. 어린이날/구강검진(col-major), 겨울방학 도서관(row-major) 자동 처리. hard-coded 가정 제거
     - **entity prefix + attr별 분리 sentence** — `"진심담은치과의원 - 전화번호: ..."` 형식. 6-class 분류기에 들어갈 단위로 의미 보존
     - **cell 내부 `▪/▸/•` bullet 자동 분리** — 한 cell 안 `"▪평일 9:30~18:30 ▪점심시간 12:30~14:00 ..."` 같은 다중 항목을 별도 sentence로 분리
   - 시행착오: per-cell 분리 (v4) → entity별 한 sentence 묶음 (v5 초안) → entity prefix attr별 분리 (최종). recall 변화 0.780 → 0.870 → 0.870

2. **v5 아키텍쳐 완성 (KoCharELECTRA BIO + 표 처리 룰)** — PoC 6장 평균 **recall 0.870, precision 0.791**, Claude 대비 **11x faster**
   - 본문은 KoCharELECTRA-small BIO 모델 (자체 학습) — sentence boundary 결정
   - 표는 위 `_table_to_sentences` 룰 사용
   - 회의용 자료 `meeting_5pm.md` + 전체 추출 dump `v5_extraction_report.md`

3. **BIO v2 학습 (raw parser input + norm-matching 라벨) — 실패**
   - 가설: BIO 학습 데이터의 input을 Claude cleaned_text가 아닌 pymupdf raw text로 → BIO가 line break/공백 노이즈 무시를 학습으로 처리
   - `prepare_bio_v2.py` 작성, 2,063 PDFs (norm-matching 75% 매칭, 46.7K B-SENT)
   - Colab T4 학습 (5 epoch, val 0.577, B-acc 0.773) → v6 평가 **recall 0.828** (v5 0.870 대비 -0.042)
   - Resume 학습 (+5 epoch LR 1e-5) → 2 epoch best, 그 후 떨어짐 → v7 평가 **recall 0.796** (더 하락)
   - 진단: 표 sentence가 norm-matching에서 매칭 실패 → 표 영역 char가 전부 O 라벨 → BIO가 "표 영역엔 sentence boundary 없다"고 잘못 학습 → 추론 시 sentence 보수적으로 적게 잡음
   - 결론: 라벨 매칭률 75%의 unlabeled noise가 학습 신호 약화. v1 (Claude cleaned_text input, 99% 매칭)이 학습 데이터 quality 면에서 더 나음

4. **LayoutXLM 통합 모델 학습 (group_id classification) — 실패**
   - 가설: 본문/표를 단일 모델로 처리. LayoutXLM-base (360M, text+bbox+image) → 룰 의존 0
   - `prepare_layoutxlm.py` 자동 라벨링: 2,063 PDFs → 4,018 page records (page 단위 record), 매칭 75.8%, max_label 128
   - PowerShell `Compress-Archive` zip 한국어 파일명 backslash 문제 → Colab rename 우회로 해결
   - Colab T4 학습 (5 epoch, batch 2, LR 2e-5)
     - Epoch 1: train 2.52 / val 2.14 / acc 0.440
     - Epoch 4: 1.64 / **1.91** / **0.511** (best)
     - Epoch 5: 1.49 / 1.93 / 0.516 (overfit 시작)
   - PoC 6장 평가: **recall 0.486** (v5 0.870 대비 -0.384)
   - Heldout 20장 평가 (학습 안 본 PDF): **recall 0.295** (generalization 실패 확정)
   - 진단: `group_id` 130-way classification은 **PDF별 의미 충돌** — PDF A의 group_id=5와 PDF B의 group_id=5가 다른 의미. 모델이 일관된 학습 신호 못 얻음. PoC 노트북의 셔플 79% 결과는 1장 overfit 환경에서만 통용
   - 결론: 모델 capacity 문제가 아닌 **라벨 형식 자체가 문제**
   - heldout 평가 set 준비: `data/heldout_20/` — 학습 데이터에 없는 PDF 20장 sampling (generalization 측정용)

### 진단 종합

| 시도 | recall (PoC 6장) | recall (heldout 20장) | 실패 원인 |
| --- | --- | --- | --- |
| **v5 (KoCharELECTRA BIO + 룰)** | **0.870** | 미측정 | 현재 best — 단 표 처리가 룰 의존, 새 형식 generalization 한계 |
| v6 (BIO v2, raw input) | 0.828 | 미측정 | 학습 데이터 unlabeled 34% → 학습 신호 약화 |
| v7 (BIO v2 resume) | 0.796 | 미측정 | overfit. v2 가설 실패 확정 |
| LayoutXLM (group_id 130-class) | 0.486 | **0.295** | `group_id` 의미 충돌. 학습 본 PDF조차 절반 못 잡음 |

### 핵심 교훈

- **PoC 노트북 결과가 일반화될지 항상 검증 필요** — LayoutXLM 1장 overfit 96%는 전체 데이터에서 51%로 추락. PoC 결과는 가설 가설용일 뿐 일반화 보장 X
- **라벨 형식이 모델 성능보다 중요** — `group_id` 형식 자체가 PDF별 의미 충돌을 야기 → 어떤 모델로도 학습 불가
- **automatic labeling 매칭률이 학습 데이터 quality 좌우** — 75% 매칭은 25% noise. 모델이 sentence boundary 학습 신호 약함
- **룰 후처리는 항상 generalization 한계** — v5 recall 0.870은 학습된 한국어 가정통신문에서만 동작. 새 형식 → 룰 안 맞으면 fail

### 다음 axis 후보 (미결정, 6/1 deadline 9일)

| 옵션 | 시간 | 기대 |
| --- | --- | --- |
| **B-2: BIO 라벨링 + LayoutXLM 재학습** | 3시간 | 의미 충돌 해결 (3-class). LayoutXLM image stream 활용 가능. 가설 검증 가치 있음 |
| A: v5 운영 + heldout 평가 + 단편 sentence 후처리 | 1~2시간 | 안전. 다만 룰 의존 그대로 |
| 더 큰 BIO 모델 (KoCharELECTRA-small → base 110M) | 1일 | paragraph 처리 능력 ↑ |
| 본질적 재설계: 2-stage (BIO + grouping 모델) | 2~3일 | Sentence-BERT 등으로 Stage 2 학습. Claude 그룹 라벨 활용 |

### 추가된 파일

```text
sentence_extraction/
├── meeting_5pm.md                          ← 5시 회의용 자료 (파이프라인 + 추출 예시 + 누락 분석)
├── v5_extraction_report.md                 ← PoC 6장 전체 추출 sentence dump + 누락 todo
├── prepare_bio_v2.py                       ← BIO v2 학습 데이터 (raw input + norm-matching)
├── kocharelectra_bio_v2_train_colab.ipynb  ← BIO v2 학습 노트북
├── kocharelectra_bio_v2_resume_colab.ipynb ← BIO v2 resume 학습 노트북
├── prepare_layoutxlm.py                    ← LayoutXLM 자동 라벨링 (sentence → group_id)
├── layoutxlm_full_train_colab.ipynb        ← LayoutXLM 본격 학습 노트북
├── layoutxlm_infer.py                      ← LayoutXLMInferer + attr별 분리 후처리
├── evaluate_e2e_layoutxlm.py               ← Claude vs LayoutXLM todo recall 평가
├── dump_v5_to_md.py                        ← v5 추출 결과 → markdown 변환
└── data/
    ├── bio_train_v2.jsonl                  ← BIO v2 학습 데이터 (2,063 PDFs, 46.7K B-SENT)
    ├── kocharelectra_bio_v2_resume_best.pt ← v2 resume best (사용 X — v5 v1보다 못함)
    ├── layoutxlm_train.jsonl               ← LayoutXLM 자동 라벨링 (4,018 page records)
    ├── layoutxlm_best.pt                   ← LayoutXLM epoch 4 best (1.4GB, group_id 가설 실패)
    ├── eval_bio_v5_entity.json             ← v5 평가 결과 (recall 0.870)
    ├── eval_bio_v6.json                    ← v6 (BIO v2 + 표 룰)
    ├── eval_bio_v7.json                    ← v7 (BIO v2 resume)
    ├── eval_layoutxlm.json                 ← LayoutXLM PoC 평가 (recall 0.486)
    ├── eval_layoutxlm_heldout.json         ← LayoutXLM heldout 평가 (recall 0.295)
    └── heldout_20/                         ← generalization 평가용 PDF 20장 (학습 안 본)
```

## 파일 구조

```text
sentence_extraction/
├── README.md                                   ← 이 문서
├── build_kd_data.py                            ← Claude 자동 라벨링 (--mode direct / sentence / pointerdoc)
├── prepare_pointerdoc.py                       ← PointerDoc 학습 sample 변환 (fuzzy or --sequential)
├── render_pdfs.py                              ← PDF → PNG 렌더링 (pymupdf)
├── pointerdoc_model.py                         ← PointerDoc 모델 정의 (DINOv2 + KoCharELECTRA + pointer)
├── pointerdoc_infer.py                         ← 추론 — PDF → sentence_list (변형 0 보장)
├── show_inference.py                           ← 원본 행 + 모델 출력 비교 출력
├── evaluate_e2e.py                             ← End-to-end 평가 (KoBERT KD vs Claude todo recall)
├── evaluate_e2e_pointerdoc.py                  ← End-to-end 평가 (PointerDoc vs Claude todo recall)
├── evaluate_pointerdoc_offline.py              ← Offline 평가 — sentence-level IoU (claude 호출 X)
├── pointerdoc_train_colab.ipynb                ← PointerDoc 학습 노트북 (v1/v3 공통)
├── pointerdoc_resume_colab.ipynb               ← v1 → v2 resume 학습 노트북
├── pointerdoc_train_C_colab.ipynb              ← capacity ↑ 변형 (d_model 512, 6 layer)
├── kobert_kd_train_colab.ipynb                 ← KoBERT KD 학습 (이전 단계)
├── lilt/layoutxlm/sat/layoutlmv3 PoC ipynb     ← 검증 이력 노트북들
└── data/
    ├── kd_train_full.jsonl                     ← KoBERT KD 페어 라벨 (2289 페어, 44장)
    ├── kd_train_pointerdoc.jsonl               ← PointerDoc raw 라벨 (2064 PDFs, Claude sentence_list)
    ├── pointerdoc_train.jsonl                  ← v1 학습 데이터 (17K fuzzy)
    ├── pointerdoc_train_v2.jsonl               ← v3 학습 데이터 (30K sequential)
    ├── pointerdoc_best_v2.pt                   ← best 모델 (F1 0.49, R 0.55, P 0.52)
    ├── pointerdoc_best_v3.pt                   ← sequential 학습 모델 (F1 0.48, R 0.54, P 0.56)
    ├── page_images/                            ← 학습용 PNG (9,097 페이지)
    ├── all_pdfs/                               ← 학습용 PDF 통합 (2,745장)
    ├── converted_pdfs/                         ← HWP/HWPX → PDF 변환 (2,022장)
    ├── extra_500/, extra_694/, extra_405/, extra_1033/  ← 사용자 zip 압축 해제
    ├── seongnam_pdfs/, taepyeong_pdfs/, 90장/  ← 학교별 source 폴더
    └── sweep_*.json                            ← threshold sweep 결과
```

## `build_kd_data.py` 사용법

```powershell
$env:ANTHROPIC_API_KEY = ((Get-Content backend/.env)[0] -split '=', 2)[1]

# 기본: --mode direct (Claude에게 행 페어 직접 라벨링 시킴, 빠름·정확)
python sentence_extraction/build_kd_data.py `
    --pdf-dir <PDF 폴더> `
    --out sentence_extraction/data/kd_train_XXX.jsonl

# 대안: --mode sentence (Claude sentence_list를 char-offset로 매칭, 매칭 노이즈 있음)
python sentence_extraction/build_kd_data.py `
    --pdf-dir <PDF 폴더> `
    --out sentence_extraction/data/kd_train_XXX.jsonl `
    --mode sentence
```

**옵션**:

- `--limit N` — PDF 개수 제한 (테스트용)
- `--exclude KEYWORD ...` — 파일명 제외 키워드 (기본: 논문·연구자료 제외)
- 행 수 200+ PDF는 자동 스킵 (가정통신문 아닌 큰 문서로 간주)

## 향후 실험 후보 (KD 계속 가는 경우)

- **End-to-end 평가** ⭐ 다음 단계 — F1 plateau가 실서비스에 미치는 영향 실측
- **라벨 사람 검수** — Claude 라벨 모호 케이스 정리, F1 한계 돌파 가능성
- **모델 크기 ↑** — KLUE-RoBERTa-large (337M) 또는 도메인 특화 모델
- **데이터 추가 수집** — 송파·검단 폴더, 다른 학교 양식 다양성
- **multi-step KD** — Claude를 페어 분류기 대신 sentence_list 추출로

## 입력 스코프

PDF text layer / HWPX / HWP 5.0(LibreOffice 경유) 지원. JPG·스캔 PDF는 OCR 픽셀 의존성 때문에 배제 (변형 0 보장 충돌).

---

## 2026-05-22 ~ Hybrid 모델 axis 도입

PointerDoc / KoCharELECTRA BIO 단독 / LayoutXLM group_id 모두 한계 확인 후 **단일 forward Hybrid 모델**로 전환. 두 backbone의 강점만 결합:

- LayoutXLM (frozen, 360M): visual + layout (표 column·row, 본문 paragraph 영역)
- KoCharELECTRA (fine-tune, 14M): 한국어 char-level boundary 정밀도

### 아키텍쳐

```text
PDF page → words + bbox + image
   ↓
LayoutXLM(frozen) → word repr (visual + layout context)
   ↓ char broadcast (word repr를 char에 gather)
   ↓
KoCharELECTRA(fine-tune) + char_visual_ctx
   ↓
Fusion MLP (concat → projection)
   ↓
BIO head (B-SENT / I-SENT / O, char-level)
   ↓
변형 0 보장: B 위치마다 sentence span = 원본 char substring
```

**파라미터**: total 380M, trainable 11.5M (LayoutXLM frozen + KoCharELECTRA + fusion + classifier). 변형 0은 모델 구조 자체 — encoder + classifier only, generation X.

### 학습 데이터 진화

| 버전 | base | 추가 변경 | recall (6장) |
|---|---|---|---|
| v3 | bio_train_v2 그대로 | Hybrid forward 처음 | 0.851 |
| v4 | + 표 entity 라벨 보강 | `_table_to_sentences` 룰 활용해 표 cell 라벨 자동 매핑 | 0.864 |
| v5b | + 룰 안 쓰는 영역 늘림 | rule-free zone 확장 | 0.864 |
| **v6** | layoutxlm_bio_train_v6 안정화 | class_weights (1.0, 8.0, 1.0) — B 비율 2% 보정 | **0.864 / P 0.899** |

### v7 CRF (단편화 fix axis) — 2026-05-25

**가설**: BIO logits argmax는 "B 다음 갑자기 I" 같은 inconsistent transition 못 막음. CRF transition matrix 추가로 sequence consistency 학습 → 단편화 ↓.

- `pytorch-crf` 추가, `HybridConfig.use_crf=True` 옵션
- 학습 동일 (5 epoch, Colab T4 ~2,000s/epoch)
- inference: `crf.decode()` (Viterbi) 사용 — `hybrid_infer.py` argmax → `outputs["predictions"]` 분기

**결과**:

| 데이터셋 | v6 sent | v7 sent | Δ |
|---|---|---|---|
| Heldout 20장 (학습 안 본) | 3,811 | 2,043 | **-46.4%** |
| HWP→PDF 10장 | 392 | 260 | **-33.7%** |
| 6장 정량 recall | 0.864 | 0.843 | -2.4% (substring 매칭 한계로 정량 차이 작음) |

본문 sentence가 절반 가까이 통합 — 같은 todo가 더 적은 단편으로 표현. CRF 효과 명확 입증. 표 영역 over-merge 부작용 별도 axis (v8).

### Parser dedup — PDF 디자인 더블 프린팅 fix (2026-05-26)

AIEP 동의서 같은 PDF가 헤더를 1~2px offset으로 두 번 인쇄(bold 효과 흉내) → `pdfplumber.extract_words`가 word를 2배로 추출 → 모델이 sentence 두 번 출력.

`parser_ensemble.dedup_overlapping_words`:
- 같은 좌표 (`top/x0/x1 ±2px`) + 같은 text 인접 word → 두 번째 제거
- 표 셀 반복은 좌표 다르므로 안전
- `hybrid_infer._extract_page`에서 `merge_singleton_words` 전 단계로 추가

효과: heldout 20장 sentence 2,043 → 2,034 (-0.4%, 4개 PDF 영향), 단순 수치 외에 **본문 내용 중복 제거가 핵심** (NLLB 번역에 중복 문장 안 들어감).

### Backend wire-up — extract_sentences 통째 교체 (2026-05-26)

`backend/app/services/layout_normalizer.extract_sentences`를 LLM (Claude/Gemini) → Hybrid로 통째 교체. LLM API 의존 제거.

신규 `backend/app/services/hybrid_extractor.py`:
- `HybridInferer` singleton (lazy load, 모델 로딩 비용 1회만)
- PDF bytes → 임시 파일 → `extract_sentences_from_pdf_bytes` → sentence list

기존 LLM 함수 `_call_claude` / `_extract_sentences_llm_legacy`는 코드 유지 (교차 검증용, production 호출 X). `notice.py:/analyze` 엔드포인트 흐름은 시그니처 호환이라 코드 변경 0 — Hybrid 결과가 그대로 윤정 → 경이 → 세종 파이프라인에 흘러감.

### Claude API vs Hybrid 교차 검증 (2026-05-26)

`scripts/compare_claude_vs_hybrid.py` — 같은 backend container에서 두 path 동시 실행 + 8개 언어 NLLB 번역. 판정 축: 1) 내용 누락, 2) 원문 변형, 3) 자연스러움.

| 축 | Claude API | Hybrid v7+dedup |
|---|---|---|
| 내용 누락 | 제목·전화번호·표 헤더 누락 | 없음 |
| 원문 변형 | 표 cell `,` join + ▸ bullet 제거 | 변형 0 ✓ |
| 자연스러움 (본문) | 자연스러움 | 자연스러움 |
| 자연스러움 (표) | mega-merge (한 sentence로 너무 김) | row 단편화 — 6-class 분류기 입력 못 됨 |
| 슬롯 보호 (NLLB 직전) | OK | 전화번호/단위어 누락 → 잘못된 번역 |

**진단**: Hybrid가 누락·변형 0 ✓. 표 row 단편화 + 슬롯 보호는 다음 axis.

`scripts/compare_analyze_full.py` — `/analyze` 전체 pipeline (extract_sentences → 윤정 todo → 경이 분류 → 세종 번역) 그대로 호출, cards/info_cards 단위 비교.

### v8 — 표 cell 단위 라벨링 (진행 중, 2026-05-26)

**진단**: v6 학습 데이터에서 표 영역 라벨링 일관성 X. 같은 표 안 cell들이 어떤 건 O, 어떤 건 I, 어떤 건 B+I로 들쭉날쭉. 모델이 일관 패턴 학습 못 함 → 표 row 단편화 진짜 원인.

**v8 라벨링 정책**: pdfplumber.find_tables로 표 검출 → **cell = sentence** (row 아님). cell 안 multi-line은 한 sentence로 묶고, cell 사이는 분리.

이유: row 단위로 묶으면 한 sentence에 프로그램명/날짜/대상/내용 다 섞여 6-class 분류기 입력 못 됨. cell 단위가 단일 entity → 분류 자연스러움.

도서관 PDF sample 검증 (`rebuild_v8_table_labels.py`):
- v6: O 62 / B 23 / I 797
- v8: O 0 / B 29 / I 853 (Δ char 72개, 8%)
- "가만히 들어주었어... 모루토끼 인형 만들기" cell (v6=O) → v8=B+I 한 sentence ✓
- "1.2(금) 09:30 ~ 11:30" multi-line cell → v8 한 sentence로 묶임 ✓

전체 2,064 record 자동 재생성 중 → v8 재학습 예정.

### 추가된 파일 (5/22 ~ 5/27)

```text
sentence_extraction/
├── hybrid_model.py                  ← LayoutXLM(frozen) + KoCharELECTRA + Fusion + BIO (+ CRF 옵션)
├── hybrid_dataset.py                ← 학습 collate (LayoutXLMProcessor + KoCharELECTRA tokenizer)
├── hybrid_infer.py                  ← 추론 — sliding window, CRF Viterbi decode, parser dedup 통합
├── hybrid_train_colab.ipynb         ← Colab v3 학습 노트북 (use_crf 옵션)
├── dump_hybrid_heldout.py           ← Heldout 20장 정성 dump
├── dump_3stage_comparison.py        ← 원문 PDF + 파서 word + 모델 sentence 3단 비교
├── rebuild_v8_table_labels.py       ← v6 → v8 (표 cell 단위 라벨 재매핑)
├── evaluate_e2e_hybrid.py           ← Claude vs Hybrid todo recall 평가
├── parser_ensemble.py               ← dedup_overlapping_words 추가 (디자인 더블 프린팅 fix)
└── colab_upload_hybrid/             ← Colab 업로드 묶음 (model/dataset/notebook + pdfs.zip)

backend/app/services/
├── hybrid_extractor.py              ← HybridInferer singleton wrapper (backend 통합)
└── layout_normalizer.py             ← extract_sentences 통째 교체 (LLM → Hybrid)

scripts/
├── compare_claude_vs_hybrid.py      ← sentence + 번역 직접 비교 (8개 언어)
├── compare_analyze_full.py          ← /analyze full pipeline 비교 (cards/info_cards)
└── make_crf_notebook.py             ← CRF notebook generator
```

### 현재 상태 (2026-05-26)

- **Backend wire-up 완료** — `/analyze` 엔드포인트가 Hybrid로 동작. LLM API 비의존
- **CRF + parser dedup 적용** — 단편화 -46% (heldout), 디자인 더블 프린팅 제거
- **표 row 단편화 fix 진행** — v8 학습 데이터 재생성 → 재학습 → 평가 순
- 본문 단편화 ("2026" 잘림 같은 케이스)는 모델 inference 측 문제로 추가 진단 필요

---

## 폴더 구조 (2026-05-26 정리)

```text
sentence_extraction/
├── README.md
├── hybrid_model.py                  ← 현행 모델
├── hybrid_dataset.py
├── hybrid_infer.py                  ← CRF Viterbi + parser dedup
├── hybrid_train_colab.ipynb
├── parser_ensemble.py               ← dedup_overlapping_words 추가
├── prepare_layoutxlm_bio.py         ← 학습 데이터 prep (v3~v6)
├── rebuild_v8_table_labels.py       ← 표 cell 단위 라벨 재매핑 (v8)
├── evaluate_e2e_hybrid.py
├── dump_hybrid_heldout.py
├── dump_3stage_comparison.py
├── extract_sentences.py             ← utility
├── colab_upload_hybrid/             ← Colab 업로드 묶음 (gitignored: pdfs.tar/zip + jsonl 사본)
└── archive/                         ← 옛 시도 (라인별 폐기 경위는 README 본문 참조)
    ├── kd/                          (KoBERT KD — F1 0.71 plateau)
    ├── pointerdoc/                  (PointerDoc — F1 0.49 ceiling)
    ├── kocharelectra_bio/           (BIO v1/v2 — Hybrid에 흡수)
    ├── layoutxlm_groupid/           (group_id 130-class — recall 0.486)
    ├── sat/                         (Segment Any Text — 단어 누락 5~10%)
    ├── poc/                         (LiLT/LayoutXLM/LayoutLMv3 셔플 검증 PoC)
    └── notes/                       (meeting_5pm.md, v5_extraction_report.md)
```
