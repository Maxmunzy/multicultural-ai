# Model A 개발일지 — 추출 파이프라인 (A단계 이진 분류)

**담당**: 윤정 · `model/extraction/file/predict.py`  
**모델**: KoELECTRA-small-v3 fine-tuned (`yunjeong116/koelectra-extractor`)  
**원칙**: 최신 날짜가 맨 위

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
