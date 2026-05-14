# Model A 개발일지 — 추출 파이프라인 (A단계 이진 분류)

**담당**: 윤정 · `model/extraction/file/predict.py`  
**모델**: KoELECTRA-base-v3 fine-tuned (2026-05-07 base 전환)  
**원칙**: 최신 날짜가 맨 위

---

## 2026-05-08

### 작업 요약

| 분류 | 내용 | 파일 |
|---|---|---|
| refactor | predict.py 정규식 필터 3종 제거 — layout_normalizer 시너지 | `file/predict.py` |
| docs | eval-base-vs-small: galsan unseen 테스트셋 B 결과 추가 | `docs/eval-base-vs-small-2026-05-07.md` |
| data | v4 학교 데이터 ZIP → TXT 변환 (1,359개) | `data/txt/v4_school_txt/` |
| data | TXT → JSONL 변환 (34,284개 문장) | `data/train/v4_raw_unlabeled.jsonl` |
| data | is_todo_label.py 규칙 라벨링 | `data/train/v4_labeled.jsonl` |
| data | koelectra-small 모델 재검수 + 정제 → 최종 학습 데이터 | `data/train/v4_clean.jsonl` |
| data | v3.1.3 + v4_clean 병합 (소프트 라벨 통일) | `data/train/v4_merged_train.jsonl` |
| feat | HF Hub 업로드 셀 + INPUT_FILE 업데이트 | `file/train_koelectra_base.ipynb` |
| feat | 재라벨링 스크립트 신규 작성 | `scripts/relabel_false_model.py` |
| feat | 병합 스크립트 신규 작성 | `scripts/merge_train_data.py` |

---

### 1. predict.py 정규식 필터 3종 제거

백엔드 layout_normalizer(Claude API)가 PDF/HWP 텍스트를 정제해 `\n` 줄 단위로 전달하는 구조로 변경됨. 기존 정규식 3종이 이 구조와 책임이 중복되거나 모델 판단을 덮어쓰는 문제를 일으켰음.

| 항목 | 문제 |
|---|---|
| `_HEADER_ONLY` | layout_normalizer가 title을 별도 필드로 분리해 넘기므로 중복 |
| keyword split (`운영시간\|운영방법\|신청방법\|...`) | Claude가 `\n` 줄 단위로 정제된 텍스트를 넘기므로 재분리 불필요. "제출 바랍니다" 식 잘림 잔재 유발 |
| `_NON_TODO_PATTERNS` 18개 | labeling-guide F4_greeting/F3_sender_info에 해당 패턴이 학습 데이터에 False로 충분히 포함됨. 규칙이 모델이 학습한 미묘한 판단을 덮어씌우는 부작용 |

`_OCR_LINE_NOISE` (URL/시간 범위/화살표 전용 줄)는 layout_normalizer와 무관한 형식 노이즈이므로 유지.

---

### 2. galsan unseen 테스트셋 B 평가 (Small vs Base)

| 모델 | Accuracy | F1 (할 일) | Precision | Recall |
|---|---|---|---|---|
| v3.1 Small | 68.73% | **0.4168** | 0.2765 | **0.8455** |
| **Base** | **71.88%** | 0.4157 | **0.2865** | 0.7570 |

> 평가 조건: pipeline 기본 threshold(0.5) 사용 — 운영 threshold와 다름. 상대 비교는 유효.

- F1은 두 모델 사실상 동일 (차이 0.001)
- Base가 Accuracy +3.15%p, Precision +1.0%p 우세
- **결론: 테스트셋 A·B 모두에서 Base가 열등하지 않음 → Base 채택 유지**

---

### 3. v4 데이터 파이프라인

| ZIP 파일 | 합계 |
|---|---|
| v4_405.Zip / v4_413.Zip / v4_694.Zip | 1,119개 원본 |

```
v4 ZIP 파일들
    ↓ Docker batch_convert.py (BATCH_MODE=batch)
data/txt/v4_school_txt/   1,359개 TXT  (HWP→ODT→TXT, PDF→TXT, 실패 81개)
    ↓ preprocess_txt_to_jsonl.py
data/train/v4_raw_unlabeled.jsonl   34,284개 문장  (급식 파일 13개 스킵)
    ↓ is_todo_label.py --with_reason
data/train/v4_labeled.jsonl  True 4,599개 (13.4%) / no_match 24,781개
    ↓ relabel_false_model.py (koelectra-small, threshold=0.55)
data/train/v4_relabeled.jsonl
    ↓ _clean_jsonl.py  (len<10 제거 4,731개 / 중복 제거 4,928개)
    ↓ _refine_jsonl.py (model_relabel conf<0.97 → False, 1,498개 재전환)
data/train/v4_clean.jsonl   24,625개  True 35.3% (8,701개)
```

---

### 4. v4_merged_train.jsonl 생성

v3.1.3_dual_labeled.jsonl(22,523개) + v4_clean.jsonl(24,625개) 병합.

| 출처 | is_todo_prob |
|---|---|
| model_relabel(conf=X) True | X 그대로 |
| 규칙 기반 True | 0.90 |
| False | 0.05 |

**최종 병합 결과:**

| | 수 |
|---|---|
| v3.1.3 | 22,523개 |
| v4 | 24,625개 |
| **합계** | **47,148개** |
| True 비율 | 26.2% |

---

### 5. 의사결정 기록

**Small vs Base 모델 선택**: unseen 성능이 동일하고 seen 데이터에서 Base가 앞서므로 Base 유지. 속도가 중요해지는 시점에 Small 재검토.

**가정통신문 도메인 특화 포지셔닝**: 범용 생성형 AI보다 도메인 특화 모델이 나을 수 있는 영역. v4 데이터 축적 → 재학습 사이클이 격차를 벌리는 플라이휠.

---

### 다음 작업

- [x] Colab에서 koelectra-base 재학습 실행 (`v4_merged_train.jsonl`) — 완료
- [x] HF Hub `yunjeong116/koelectra-extractor` 새 가중치 푸시 — 완료
- [x] galsan unseen 테스트셋 B 재평가 (새 모델 기준) — 완료 (Recall 0.8680)
- [ ] NCP hf_cache 비우기 + 재배포
- [ ] 4종 통신문으로 정규식 제거 효과 검증

---
---

## 2026-05-07

### 작업 요약

| 분류 | 내용 | 파일 |
| --- | --- | --- |
| feat | `is_todo_label.py` 신규 — 규칙 기반 is_todo 재라벨러 | `file/is_todo_label.py` |
| data | v3.1.1 생성 (규칙 기반, True 12.1%) | `data/train/v3.1.1_dual_labeled.jsonl` |
| data | v3.1.2 생성 (no_match 228건 True 회복, True 12.9%) | `data/train/v3.1.2_dual_labeled.jsonl` |
| data | v3.1.3 생성 (B그룹 제외 + 소프트 라벨, True 16.2%) | `data/train/v3.1.3_dual_labeled.jsonl` |
| feat | `train_koelectra_base.ipynb` 신규 — KoELECTRA-base 학습 노트북 | `file/train_koelectra_base.ipynb` |
| model | KoELECTRA-base 학습 완료 (v3.1.3 + 소프트 라벨, T4 약 60분) | `checkpoints/koelectra-binary-base/` |
| fix | `BINARY_THRESHOLD` 0.55 → **0.40** (base 모델 최적값 반영) | `predict.py` |
| fix | `_LOCAL_CHECKPOINT_DIR` `koelectra-binary-v3.1` → `koelectra-binary-base` | `predict.py` |
| docs | `labeling-guide.md` 전면 업데이트 (v3.1.1 / v3.1.2 이력·규칙 상세화) | `docs/labeling-guide.md` |
| docs | `eval-base-vs-small-2026-05-07.md` 신규 — Base vs Small 성능 비교 | `docs/eval-base-vs-small-2026-05-07.md` |

---

### 1. 라벨링 파이프라인 재설계 — is_todo_label.py

**배경**: v3.1(Haiku 라벨)의 True 비율 29.1%가 galsan unseen 실제 분포(13.2%)의 2배. 노이즈 라벨이 모델 학습에 혼선 유발.

**판별 구조**:

```text
is_title=True → 제목 전용 3분류 (액션형/일정형 → True, 공지형 → False)
F1~F7 False 조건 체크 (표 헤더, 인사말, 발신자, 개인정보 등)
  └ 3가지 우선순위 역전:
      F2_timetable + 학부모 → True (학부모 참여 행사)
      F3_sender_info + 장소: 헤더 → True (장소 정보)
      F7_privacy + CAT3 제출 패턴 → True (동의서 제출 요청)
CAT1~7 True 카테고리 OR 체크
기본값 False
```

**버전별 True 비율 변화**:

| 버전 | True 비율 | 변경 내용 |
| --- | --- | --- |
| v3.1 | 29.1% | Haiku 원본 |
| v3.1.1 | 12.1% | 규칙 기반 재라벨링 |
| v3.1.2 | 12.9% | no_match 228건 회복 (수강료/교재비/보호자동반/이상소견 등) |
| **v3.1.3** | **16.2%** | B그룹(5,724건) 제외 + 소프트 라벨 |

---

### 2. v3.1.3 소프트 라벨 설계

B그룹(v3.1=True, v3.1.2=False)은 ~50% 노이즈 혼재 → 학습 데이터에서 완전 제외.  
남은 A/C/D 그룹에 신뢰도 기반 확률 부여.

| 그룹 | 구성 | 건수 | is_todo_prob |
| --- | --- | --- | --- |
| A | 양쪽 True (v3.1 ∩ v3.1.2) | 2,496 | 0.95 |
| C | v3.1.2만 True | 1,159 | 0.85 |
| D | 양쪽 False | 18,868 | 0.05 |

---

### 3. KoELECTRA-base 학습

**학습 환경**: Google Colab T4 GPU, 약 60분  
**학습 데이터**: `v3.1.3_dual_labeled.jsonl` (22,523건)  
**손실 함수**: KL Divergence (소프트 라벨 대응)  
**배치**: 8 + gradient_accumulation_steps=2 (유효 배치 16), fp16=True

**val split(5,650개) 결과**:

| 모델 | Accuracy | F1 (할 일) | Precision | Recall | Threshold |
| --- | --- | --- | --- | --- | --- |
| v3.1 Small | 89.40% | 0.8223 | 0.8025 | 0.8431 | 0.55 |
| **Base** | **90.69%** | **0.8387** | **0.8459** | 0.8315 | **0.40** |
| 변화 | +1.29%p | +0.016 | **+0.043** | -0.012 | — |

Precision +4.3%p — 학부모 체크리스트에서 노이즈 문장이 보이는 빈도 감소.  
Recall -1.2%p — 허용 범위. 서비스 UX 관점에서 오탐 감소가 더 가치 있음.

**임계값 0.55 → 0.40으로 낮아진 이유**: KL Divergence 학습으로 모델이 경계 케이스에 확신을 덜 가짐. 임계값 곡선이 평탄 (0.40~0.70 구간 F1 차이 0.005) — 모델이 경계선에서 명확하게 분리하고 있음.

---

### 4. 서비스 방향성 논의

갈산초 unseen 테스트셋 비교 평가 중 (CPU 추론으로 시간 소요).

**파이프라인 한계 파악**: 문장 단위 추출 → 카드 나열 방식은 Gemini 대비 문서 구조 이해·프로그램별 그룹화에서 열위. 단, 다국어 TTS·OCR·교사-학부모 워크플로우·학교 용어사전은 명확한 차별성.

**향후 방향 검토**:

- XLM-RoBERTa + LoRA 멀티태스크 (is_todo + 카테고리 + NER) → 구조화 출력 → 다국어 자동
- 체크리스트 완성도 + 달력 등록 + D-day 알림 = 핵심 UX 3종

---

### 다음 작업

- [ ] galsan unseen 기준 Small vs Base 비교 평가 완료 (`eval_compare.py` 실행 중)
- [ ] Base 체크포인트 HF Hub 업로드 (`yunjeong116/koelectra-extractor`)
- [ ] `eval_compare.py` 결과로 `eval-base-vs-small-2026-05-07.md` 완성
- [ ] `eval_compare.py` 임시 파일 삭제

---
---

## 2026-05-06

### 작업 요약

| 분류 | 내용 | 파일 |
| --- | --- | --- |
| fix | `BINARY_THRESHOLD` 0.65 → 0.50 → **0.55** 조정 (FP/FN 균형) | `predict.py` |
| eval | Base / v3 / v3.1 성능 비교 — v3 val split 기준 문서화 | `docs/eval-model-comparison-2026-05-06.md` |
| data | v3.1 증강 데이터 생성 — 7패턴 448개 True 샘플 | `data/train/v3.1_augmented.jsonl` |
| data | v3.1 병합 학습 데이터 생성 (27,799 + 448 = 28,247개) | `data/train/v3.1_dual_labeled.jsonl` |
| model | v3.1 재학습 완료 · HF Hub 업로드 | `checkpoints/koelectra-binary-v3.1/` |
| eval | v3 vs v3.1 양방향 비교 평가 (val split + unseen galsan) | `docs/eval-v3-vs-v3.1-2026-05-06.md` |
| fix | `_load_model()` HF Hub 우선 로드로 변경 (배포 안정성) | `predict.py` |
| fix | `_clean_symbols` whitelist 방식 전환 — PUA·체크박스 변종 기호 제거 | `predict.py` |
| fix | `_LOCAL_CHECKPOINT_DIR` 경로 `koelectra-binary-v3.1`로 수정 | `predict.py` |
| docs | README 전면 최신화 — 파일구조·성능지표·파이프라인 반영 | `README.md` |
| docs | v3.1 생성 배경 문서 추가 — 문제 파악·증강 전략·재학습 결과 | `docs/v3.1-problem-and-solution.md` |

---

### 1. 준비물 recall 문제 분석 및 BINARY_THRESHOLD 조정

**원인**: `"5. 준비: 간편한 복장..."` 등 번호 붙은 준비물 항목이 threshold 0.65에서 전량 reject.  
학습 데이터에서 해당 패턴 True 샘플이 0~1개에 불과한 데이터 공백이 주원인.  
mislabeling 전수 조사(v3_dual_labeled_clean 기준) 결과, False 라벨 대부분 정확 — 라벨 오류 아닌 패턴 부재.

`BINARY_THRESHOLD`: 0.65 → **0.50** (즉시 recall 개선 효과, FP 소폭 증가 감수)

---

### 2. v3.1 증강 데이터 생성

`file/generate_v3_1.py` 신규 작성 → 7개 패턴 총 **448개** True 샘플 생성.

| 패턴 | 샘플 수 | 기존 True 수 |
| --- | --- | --- |
| 번호+준비물 (`N. 준비:`) | 100개 | **0개** |
| 간편한/편안한 복장 | 80개 | **1개** |
| 부정형 준비물 (없음/불필요) | 68개 | 6개 (False 12개 역전 상태) |
| 유의사항 실행형 | 60개 | 12개 |
| 지참물 목록형 | 60개 | 34개 |
| 학부모 동반 요청 | 40개 | — |
| 당일 건강·안전 주의사항 | 40개 | — |

기존 학습 데이터 중복: **0개** (완전 신규 샘플).

---

### 3. v3.1 재학습 결과

학습 데이터: `v3.1_dual_labeled.jsonl` (28,247개, True 29.1%)  
학습 파라미터: v3와 동일 (epochs 10, lr 2e-5, cosine, WeightedCrossEntropy)

| 지표 | v3 | v3.1 | 변화 |
| --- | --- | --- | --- |
| 할 일 Recall | 0.8127 | **0.8431** | **+0.030 ✅** |
| 할 일 Precision | 0.8029 | 0.8025 | ±0.000 |
| 할 일 F1 | 0.8078 | **0.8223** | +0.015 ✅ |
| Accuracy | 0.8919 | **0.8940** | +0.002 ✅ |
| Macro F1 | 0.8663 | **0.8734** | +0.007 ✅ |

평가 기준: v3.1 val split 5,650개 (학습 gradient 미포함 20% split)

---

### 4. v3 vs v3.1 비교 평가

두 테스트셋 병행 평가.

**테스트셋 A — v3.1 val split** (v3.1에 공정, v3엔 학습 데이터 98.6% 포함)

| 모델 | Accuracy | F1 (할 일) | Recall |
| --- | --- | --- | --- |
| v3 | 89.58% | 0.8225 | 0.8303 |
| v3.1 | 89.40% | 0.8223 | **0.8431** |

**테스트셋 B — unseen galsan** (두 모델 모두 완전 unseen ← 진짜 비교 기준)

| 모델 | Accuracy | F1 (할 일) | Recall |
| --- | --- | --- | --- |
| v3 | 70.69% | **0.4184** | 0.7978 |
| v3.1 | 68.73% | 0.4168 | **0.8455** |

F1은 두 테스트셋 모두 거의 동일(±0.002). v3.1이 두 테스트셋에서 일관되게 **Recall +1.3~4.8%p** 향상, Precision 소폭 하락(-0.7~1.2%p).

> 갈산초 데이터는 두 모델 모두 distribution shift로 낮은 절대 성능. 갈산초 True 샘플 혼합 재학습 시 개선 예상.

---

### 다음 작업

- [ ] BINARY_THRESHOLD 0.5 기준 최적값 재탐색 (`evaluate_hf_model.ipynb`)
- [ ] 갈산초 True 샘플 730개 + v3.1 데이터 혼합 후 v4 재학습
- [ ] v4 학습 후 unseen_test_galsan 기준 재평가
- [ ] `predict.py` 내 `V3_MODEL_PATH` 기본값 `koelectra-binary` → `koelectra-binary-v3.1` 수정
- [ ] HF Hub 업로드 (v3.1 체크포인트)

---
---

## 2026-05-01

### 작업 요약

| 분류 | 내용 | 파일 |
|---|---|---|
| feat | newschool2 / newschools txt 데이터 → v3_school.jsonl 생성 | `data/processed/v3_school.jsonl` |
| fix | 기호 정제 로직 전면 교체 — whitelist 방식 도입 | `preprocess_txt_to_jsonl.py` |
| fix | 한국식 날짜 분절 버그 수정 — join_broken_lines 규칙 0 추가 | `preprocess_txt_to_jsonl.py` |
| fix | `_simple_split` 2글자 lookbehind 적용 — 날짜 마침표 분리 방지 | `preprocess_txt_to_jsonl.py` |
| feat | `auto_label.py` 규칙 기반 is_todo 초안 라벨러 신규 작성 | `file/auto_label.py` |
| feat | v3_labeled.jsonl 생성 — 초안 라벨 포함 | `data/processed/v3_labeled.jsonl` |

---

### 1. 신규 데이터 처리 — v3_school.jsonl 생성

1,415개 TXT 파일 처리 → **35,219개 문장** 생성 (문장 수: 46,046개 → 날짜 분절 수정 후 35,219개).

주요 학교: 90장·500장·검단·성남·송파·태평 등 10개 폴더.

---

### 2. 기호 정제 로직 전면 교체

기존 하드코딩 방식(30여 종)에서 whitelist 방식으로 전환.

**1단계 `_NORMALIZE_TABLE`** — `'→'`, `"→"`, `～→~`, `…→...` 등 변환 매핑.

**2단계 `_SYMBOL_REMOVE_RE`** — 허용 목록(한글/영숫자/`.,:!?()/%@~&_-'"`) 외 문자를 공백으로 치환. PUA·체크박스·원형숫자 일괄 제거.

---

### 3. 날짜 분절 버그 수정

한국식 날짜(`2026. ~ 11. 30.`)가 마침표마다 쪼개지던 문제 수정.

```python
# join_broken_lines() 규칙 0 추가
text = re.sub(r"(\d+\.)\n", r"\1 ", text)

# _simple_split() 2글자 lookbehind
r"(?<!\d\.)(?<=[.!?])\s+"
```

결과: `2026. ~ 11. 30.(추후 공지)` — 4개 조각 → 1개로 통합.

---

### 4. auto_label.py — 규칙 기반 초안 라벨러

FALSE 조건 8종(표 헤더/발신자/인사말/배경설명 등) 먼저 체크, TRUE 조건 7종(마감+액션/준비물/안전지침/요청형 어미 등) OR 체크.

결과: True 3,387건(9.6%) / False 31,832건(90.4%).

> `T7_request_ending` 구간은 `"댁내 두루 평안하시길 바랍니다."` 같은 케이스 포함 — 검수 필요.

---

### 다음 작업

- [x] v3_labeled.jsonl 수동 검수 → is_todo 최종 확정 — 이후 v3_dual_labeled_clean으로 확정
- [x] 검수된 데이터로 `train_koelectra.ipynb` 파인튜닝 재실행 — v3 학습으로 완료

---
---

## 2026-04-30

### 작업 요약

| 분류 | 내용 | 파일 |
| --- | --- | --- |
| fix | `_OCR_LINE_NOISE` 전 패턴에 `^` anchor 추가 | `predict.py` |
| fix | `split_sentences()` — 리스트 마커·반복 레이블 앞 분리 추가 | `predict.py` |
| fix | distribution shift — 추론도 학습과 동일 기호 정제 적용 | `predict.py` |
| fix | 전처리 순서 — split 이후 기호 정제로 변경 | `preprocess_txt_to_jsonl.py` |
| feat | `BINARY_THRESHOLD` 0.5 → 0.65 (v2 평가 최적값 반영) | `predict.py` |
| feat | 변종 마커 추가 — `‧∙∘․` / `➊➋➌➍➎➏` | 양쪽 파일 |
| docs | `labeling-guide.md` 신규 생성 | `docs/` |
| docs | `README.md` 전면 갱신 | `README.md` |

---

### 1. OCR 노이즈 정규식 — `^` anchor 추가

**원인**: 서대구초 케이스에서 `"학부모님 안녕하십니까? ... http://... ... 신청기간: ..."` 같이 URL이 본문 중간에 포함된 줄이 통째로 차단됨.

```python
# 수정 전 — 줄 어디든 URL 있으면 차단
r"https?://"

# 수정 후 — URL 전용 줄만 차단
r"^https?://"
```

`☎\s*\d` (전화번호), `\d{1,2}:\d{2}...\d{1,2}:\d{2}` (시간 범위)도 동일하게 `^` anchor 및 `$` 추가.

---

### 2. `split_sentences()` — 리스트 마커·반복 레이블 분리

**원인**: `"❏ 운영시간 오전 10:00 ~ 12:00 ❏ 운영방법 ..."` 처럼 마침표 없이 이어진 항목들이 하나의 문장으로 처리돼 `predict()`가 묶음 dict 반환.

```python
# 추가된 분리 규칙
r"\s+(?=[❏○◆●▪◎□■])|"                          # 리스트 마커 앞 분리
r"\s+(?=운영시간|운영방법|신청방법|신청기간|"
r"준비물|제출|기타\s*안내|접수방법|참가방법)",   # 반복 레이블 앞 분리
```

결과: 동일 입력에서 묶음 1개 dict → 항목별 개별 dict로 분리.

---

### 3. Distribution Shift 수정 — 추론 기호 정제 추가

**원인**: `clean_text()`(학습 전처리)는 특수기호를 제거하지만, `predict.py`(추론)는 `_join_broken_lines()`만 호출하고 기호 정제가 없어 distribution shift 발생.  
ODT parser 출력에 마커가 살아있는 상태에서 모델 입력에 그대로 들어가는 문제도 함께 발견.

**해결**: split 이후 문장 단위로 기호 정제 — split에서 마커를 분리 기준으로 쓰므로 제거는 반드시 split 이후에 수행.

```python
# predict.py 에 추가
_SYMBOL_PATTERN     = re.compile(r"[▪▫▸▹◆◇●○◎□■★☆※◁▷△▽→←↑↓·•…❏‧∙∘․]+")
_CIRCLE_NUM_PATTERN = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩➊➋➌➍➎➏]")

def _clean_symbols(sentence: str) -> str:
    sentence = _SYMBOL_PATTERN.sub(" ", sentence)
    sentence = _CIRCLE_NUM_PATTERN.sub("", sentence)
    return re.sub(r"\s+", " ", sentence).strip()

# predict() 루프 내
for sentence in split_sentences(notice_text):
    sentence = _clean_symbols(sentence)  # ← 추가
    ...
```

---

### 4. 전처리 순서 수정 — split 먼저, 정제 나중

**원인**: `preprocess_txt_to_jsonl.py`가 `clean_text()` → `split_into_sentences()` 순서였는데, `clean_text()`가 기호를 먼저 제거하면 `split_sentences()`의 마커 기반 분리 규칙이 작동 불가.

```
수정 전: clean_text(기호 제거 포함) → split
수정 후: clean_text(null byte/CR만) → split → clean_sentence(기호 제거)
```

```python
def clean_text(text: str) -> str:
    """null byte / CR / 공백만 — 기호 정제는 split 이후 clean_sentence 에서"""
    ...

def clean_sentence(sentence: str) -> str:
    """split 이후 문장 단위 정제 — predict.py _clean_symbols 와 동일 로직"""
    ...

# preprocess_to_custom_schema() 내
pre_cleaned = clean_text(joined)
raw_sents   = split_into_sentences(pre_cleaned)   # 마커 기준 분리 먼저
sentences   = [clean_sentence(s) for s in raw_sents if len(clean_sentence(s)) > 3]
```

---

### 5. `BINARY_THRESHOLD` 0.5 → 0.65

`evaluate_hf_model.ipynb` 실행 결과 최적 임계값 확인 후 반영.

| threshold | F1 |
| --- | --- |
| 0.50 | 0.9321 |
| **0.65** | **0.9332** ← 최적, 적용 |

---

### 6. 변종 마커 추가

팀원 검토에서 추가 미정제 마커 발견. `predict.py` / `preprocess_txt_to_jsonl.py` 양쪽 동기화.

| 패턴 | 추가 내용 |
| --- | --- |
| `_SYMBOL_PATTERN` | `‧∙∘․` (변종 가운뎃점 계열) 추가 |
| `_CIRCLE_NUM_PATTERN` | `➊➋➌➍➎➏` (채워진 원문자) 추가 |

> merge 후 한 번 날아갔다가 복구함.

---

### 7. v2 베이스라인 성능 확정

`evaluate_hf_model.ipynb` 실행 결과. 이후 v3 모델과의 비교 기준.

| 지표 | 값 |
| --- | --- |
| Precision | 0.9067 |
| Recall | 0.9589 |
| **F1** | **0.9321** |
| FN (놓침) | 30개 |
| FP (오탐) | 72개 |

**해석 주의**: 갈산초 학습 데이터 분포 위에서 나온 수치. 신청기간/운영시간 패턴이 학습·평가 데이터 모두에 없어서 높게 측정됨. v3 고정 테스트셋(`data/test_fixed.jsonl`) 기준 재평가 시 수치 변동 예상.

---

### 8. labeling-guide.md 신규 생성

v3 데이터 라벨링 기준 문서화. 현재 모델이 confidence 0.05 미만으로 전부 컷하는 패턴 5종의 `is_todo: true` 기준 및 예시 정리.

- 운영시간 (score 0.008)
- 신청방법 (score 0.043)
- 신청기간 (score 0.043)
- 기타 안내사항 (score 0.231)
- 표 행 (score 0.008~0.043)

→ `docs/labeling-guide.md` 참조.

---

### 다음 작업

- [ ] v3 데이터 수신 (찬영님) → 고정 테스트셋 100~200문장 먼저 추출 (`data/test_fixed.jsonl`)
- [ ] galsan_txt 재전처리 후 is_todo 새로 라벨링 (labeling-guide.md 기준)
- [ ] True 샘플 730개 → 1,500개 이상 확보 후 재학습
- [ ] 재학습 후 고정 테스트셋 기준 F1 비교 (v2 베이스라인 대비)
- [ ] 변종 마커 다음 PR 시 체계적으로 목록화
- [ ] 경이님 B단계 모델 구축 시 `action_hint` 활용 방안 협의

---
---

## 2026-04-29

### 작업 요약

| 작업 | 파일 | 결과 |
| --- | --- | --- |
| 전처리 버그 수정 2건 + 성능 개선 | `preprocess_txt_to_jsonl.py` | ✅ |
| B단계 연동 출력 스키마 확장 | `predict.py` | ✅ |
| galsan_txt 전처리 실행 | `v2_notices_galsan.jsonl` | 5,475 문장 |
| is_todo 라벨링 | `v2.1_notices_galsan.jsonl` | True 730 / False 4,745 |
| 노트북 파일명·필터 수정 | `train_koelectra.ipynb` | ✅ |
| KoELECTRA 파인튜닝 실행 | `checkpoints/koelectra-binary/` | ✅ 53.9 MB |

---

### 1. preprocess_txt_to_jsonl.py — 버그 수정 및 성능 개선

#### 버그 1: predict.py 경로 오류 (치명)

kss 미설치 환경에서 fallback으로 `predict.split_sentences`를 불러올 때 경로가 잘못되어 있었다.

```python
# 수정 전 — model/extraction/predict.py 를 찾음 (존재하지 않음)
predict_path = _HERE.parent / "predict.py"

# 수정 후 — model/extraction/file/predict.py (실제 위치)
predict_path = _HERE / "predict.py"
```

#### 버그 2: 급식 파일 과잉 스킵

파일명에 `"급식"` 키워드가 있으면 무조건 스킵 → 정보 전달 목적 파일 7개도 함께 날아감.

```python
# 수정 전
_MEAL_NAME_KEYWORDS = ["급식"]
# 수정 후
_MEAL_NAME_KEYWORDS = []   # 내용 기반 패턴만 사용
```

실제 식단표 고유 패턴(`에너지/단백질`, `①난류 ②우유`, `무상급식비:`, `N회 무상급식`)으로만 판별. 스킵 15개, 유지 7개 — 모두 정확.

#### 성능 개선: 모듈 캐싱

281개 파일 처리 시 매 파일마다 `exec_module()`으로 predict.py 재로드 → torch import 281회 반복으로 수 분 소요. 최초 1회 로드 후 캐시하도록 수정.

---

### 2. predict.py — B단계 연동 출력 스키마 확장

```python
# 변경 전
{"text": str, "due_date": str|None, "has_money": bool}

# 변경 후
{
  "text":        str,
  "source":      str|None,   # 출처 파일명 — 신규
  "due_date":    str|None,   # 연도 하드코딩 제거
  "amount":      int|None,   # has_money bool → 실제 금액
  "confidence":  float,      # KoELECTRA 확률값 — 신규
  "action_hint": str|None    # 납부/제출/신청/참여/준비/확인 — 신규
}
```

---

### 3. 학습 데이터 생성

#### v2_notices_galsan.jsonl

- 입력: `galsan_txt/` — 281개 txt (급식표 15개 스킵, 266개 처리)
- 출력: 5,475 문장

#### v2.1_notices_galsan.jsonl (라벨링 완료)

| 라벨 | 수 | 비율 |
| --- | --- | --- |
| `is_todo: true` | 730 | 13.3% |
| `is_todo: false` | 4,745 | 86.7% |
| **합계** | **5,475** | |

---

### 4. KoELECTRA 파인튜닝

| 항목 | 값 |
| --- | --- |
| 베이스 모델 | `monologg/koelectra-small-v3-discriminator` |
| 학습 데이터 | v2.1 — 5,450문장 (7자 미만 제거 후) |
| Train / Val | 4,360 / 1,090 (80/20 stratified) |
| Epochs | 10 |
| LR | 2e-5 (cosine, warmup 0.1) |
| 클래스 불균형 | WeightedTrainer + `compute_class_weight('balanced')` |

체크포인트: `checkpoints/koelectra-binary/` — 53.9 MB

---

### 5. predict.py 안정화 버그 3건

| # | 내용 |
| --- | --- |
| 1 | `_LOCAL_CHECKPOINT_DIR` 경로 한 단계 오류 수정 |
| 2 | `_local_ready` 체크 — `config.json` 유무 검사 추가 |
| 3 | `_join_broken_lines()` predict() 입력에 미적용 → 추가 |

---

### 6. HF Hub 업로드

`yunjeong116/koelectra-extractor` 전체 파일 업로드 완료. 로컬 체크포인트 없을 시 자동 fallback.

---

### 7. 로컬 실행 테스트 결과

- confidence 0.9946 — 모델 정상 작동
- `"신청 기간: N월 N일"` 형식 미추출 — 학습 데이터 패턴 부족. 데이터 보강 후 재학습 필요.

---

### 다음 작업

- [x] galsan_txt 재전처리 후 is_todo 새로 라벨링 — v3.1.2 기준 완료
- [x] True 샘플 1,500개 이상 확보 후 재학습 — v4_merged(47,148행)로 완료
- [x] 재학습 후 galsan unseen 기준 F1 비교 — Recall 0.7556 → 0.8680
- [x] 경이님 B단계 모델 `action_hint` 활용 방안 협의 — 완료
- [ ] 변종 마커 체계적 목록화 — 향후 과제

---
---

## 2026-04-28 (v2 재학습)

### 작업 요약

| 분류 | 내용 |
| --- | --- |
| model | KoELECTRA v2 재학습 (Colab T4, 하이퍼파라미터 개선) |
| eval | v2 베이스라인 성능 확정 (accuracy 0.85, macro F1 0.82) |

---

### 재학습 배경

04-27 수정한 하이퍼파라미터·손실 함수 효과 검증. `notices_labeled_v2.jsonl`(100문장)으로 Colab 재학습.

이전: accuracy 0.75 / macro F1 0.60 → MVP 목표 미달.

### 변경 사항

| 항목 | 이전 | 신규 |
| --- | --- | --- |
| `num_train_epochs` | 10 | **15** |
| `learning_rate` | 3e-5 | **2e-5** |
| LR 스케줄러 | linear | **cosine** |
| warmup | 없음 | **`warmup_ratio=0.1`** |
| 손실 함수 | CrossEntropy | **WeightedCrossEntropy (`balanced`)** |

### 재학습 결과

```
              precision    recall  f1-score   support

          일정     1.0000    1.0000    1.0000         4
         준비물     1.0000    0.5000    0.6667         4
          제출     0.8000    1.0000    0.8889         4
       건강·안전     0.8571    0.8571    0.8571         7
          기타     0.5000    1.0000    0.6667         1

    accuracy                         0.8500        20
   macro avg     0.8314    0.8714    0.8159        20
```

| 지표 | v1 (10 epoch) | v2 (15 epoch) | 변화 |
| --- | --- | --- | --- |
| accuracy | 0.7500 | **0.8500** | +0.10 ✅ |
| macro F1 | 0.5988 | **0.8159** | +0.22 ✅ |
| 기타 F1 | 0.0000 | **0.6667** | 완전 회복 ✅ |

MVP 목표 (accuracy ≥ 0.80, macro F1 ≥ 0.75) 달성.

---
---

## 2026-04-28 (notices_original2 데이터 작업)

### 작업 요약

민경이님이 가정통신문 27장 원문을 `notices_original2.csv/.jsonl`로 제공. `original_text`는 채워져 있으나 `category`, `keywords`, `importance` 열이 비어 있어 `fill_original2.py`로 자동 입력.

- `notices_labeled_v2.jsonl` — 기존 라벨 데이터에 `original_id` 연결 필드 추가
- `fill_original2.py` 신규 작성 — 규칙 기반으로 누락 필드 자동 채우기

> 이 파일들은 초기 B단계 연동 실험용으로 현재는 legacy 취급.

---
---

## 2026-04-27

### 작업 요약

| 분류 | 내용 | 파일 |
| --- | --- | --- |
| fix | Bug 1 — 인사말 패턴 3개 추가 (`NON_TODO_PATTERNS`) | `predict.py` |
| fix | Bug 2 — `_HEADER_ONLY` 필터 추가 (제목 줄 번역 차단) | `predict.py` |
| fix | Bug 3 — `MONEY_PATTERN` 숫자 선행 조건 강화 (`원→won` 오탐 방지) | `run_mvp_pipeline.py` |
| feat | 학습 코드 개선 — 하이퍼파라미터·손실 함수 변경 | `train_koelectra.ipynb` |
| fix | `predict.py` 삭제 상태 → Bug 1·2 수정본으로 복원 | `predict.py` |

---

### Bug 1 — 인사말이 TODO로 잡힘

`NON_TODO_PATTERNS`에 `안녕하십니까`만 있고 `안녕하세요` 미포함.

```python
r"^학부모님\s*안녕하세요",
r"^안녕하세요",
r"^.*님\s*안녕하(세요|십니까)",
```

### Bug 2 — 첫 번역 문장 어색

제목 줄이 인사말과 합쳐져 NLLB에 전달됨. `split_sentences()` 앞단에 조기 차단 필터 추가.

```python
_HEADER_ONLY = re.compile(
    r"^[^.,!?~]{2,40}(안내|공지|알림|공개수업|상담|학습|행사|일정)\s*$"
)
```

### Bug 3 — `원→won` 오탐

`"원하시는"`, `"원인"` 등 substring 매칭 발생. `MONEY_PATTERN`에 숫자 선행 조건 추가.

```python
# 수정 후 — extraction 단에는 이미 적용됨
MONEY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")
```

### 학습 코드 개선 (04-27)

| 항목 | 이전 | 이후 |
| --- | --- | --- |
| epochs | 10 | 15 |
| lr | 3e-5 | 2e-5 |
| 스케줄러 | linear | cosine |
| warmup | 없음 | 0.1 |
| 손실 함수 | CrossEntropy | WeightedCrossEntropy |

---

### 단위 테스트 결과 (12/12 ✅)

Bug 1·2·3 모두 패치 후 `train_koelectra.ipynb` 셀 22에서 검증 완료.
