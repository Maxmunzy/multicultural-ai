# 추천된 모델 및 기술 스택

추천1. KcELECTRA fine-tune

이유:
1. 데이터 양 충분 (700~1400 sentence) — KcELECTRA fine-tune 권장 sweet spot
2. 학교 도메인 어휘 OOV 문제 해결 (subword tokenization)
3. 윤정님 base 모델과 같은 koelectra-small ─ backbone 공유 가능
   → 백엔드 RAM 중복 로드 회피 (둘 다 base는 같고 head만 다름)
4. CPU 추론 가능 (small 변형이라 ~50ms/문장)
5. 윤정님이 이미 같은 모델로 학습 환경 셋업 완료 — 학습 코드 재활용
메모리 효율 트릭

두 모델이 같은 backbone 공유하면 RAM 중복 0
shared_encoder = AutoModel.from_pretrained("monologg/koelectra-small-v3-discriminator")

윤정_head = BinaryHead(shared_encoder)        # 할일 추출 (binary)
경이_head = MulticlassHead(shared_encoder, 6)  # 카테고리 (6-class)
이렇게 짜면 경이 모델 추가에 따른 RAM 증가가 head만큼(~수MB)으로 줄어듦. 이상적.

단계적 권장안

1주차: 경이님이 KcELECTRA fine-tune 시도
   
데이터: notice_sample_v3.csv + notices_galsan.jsonl 라벨 부분
GPU: Colab T4 무료로 충분 (~20분 학습)
검증: 갈산초 holdout F1 + cross-validation

2주차: 정확도 비교
   
simple (현재) vs KcELECTRA fine-tune
5%+ F1 향상 → KcELECTRA 채택, 그 미만 → simple 유지
simple은 항상 fallback으로 유지

3주차: 시연 통합
   
더 좋은 쪽으로 교체
선생님께 학습 코드/모델 공유로 재현성 보장
주의
시연 4주 임박이라 무리하면 안 됨:

KcELECTRA fine-tune 학습 자체는 빠르지만 검증 + 디버깅 시간 필요
simple v1이 이미 75% 정확도라 시연 박살 안 남
실패하면 simple 그대로 — 백업 명확히
경이님 부담:

학습 환경 셋업 (윤정님 코드 빌려쓰기로 부담 경감)
라벨 데이터 정제 (현재 v3.csv 라벨 품질 확인)
검증셋 분리 (갈산초 holdout)
한 줄 요약
데이터 충분 → KcELECTRA fine-tune 시도가 정답. 다만 simple v1을 fallback으로 항상 유지. 윤정님 backbone 공유하면 RAM 효율 + 학습 환경 재활용 가능.

경이님이 비교 실험 의지 있는 건 좋음. 다만 제대로 비교해야 가치 있고, 시연 4주 안 압박도 있으니 셋업이 중요.

# 비교 실험 설계 가이드
1. 후보 모델 선정 (3~4개가 최대)
모델                              카테고리           학습 시간       강점               
TF-IDF + LogReg                베이스라인 (필수)       수초          빠름              
SBERT + LightGBM                임베딩 ML             분         의미 유사도           
KcELECTRA-small fine-tune      한국어 BERT          20~30분      도메인 학습          
KoBERT fine-tune               한국어 BERT          20~30분      한국어 특화  

→ 3개 권장: TF-IDF (baseline) + SBERT + KcELECTRA. 4개는 시간 박살.

2. 공정 비교를 위한 절대 규칙
(a) 동일 train/val/test 분할 강제

scripts/split_dataset.py 만들어서 ONE TIME 실행:
random.seed(42)  # 무조건 고정
labels = stratified_split(data, train=0.8, val=0.1, test=0.1)

split_v1.csv 라는 단일 파일로 저장 → 모든 모델이 같은 분할 사용

(b) Metric 통일

Macro F1 (메인) — 클래스 불균형 대비
Per-class F1 — "비용은 잘 잡는데 건강·안전은 못 잡는다" 같은 진단
Confusion matrix — 어디서 헷갈리는지 시각화

(c) Seed 고정 — numpy, torch, random 모두 42

추천2.  모델: klue/roberta-base

KoELECTRA(A단계)와 겹치지 않고, KLUE 벤치마크에서 한국어 분류 SOTA. 
파인튜닝이 안정적이고 허깅페이스에서 바로 쓸 수 있음.

## 6가지 카테고리 설명

| 카테고리 | 의미 | 예시 |
|--------|------|------|
| **일정** | 날짜·시간·행사 관련 | "운동회는 10월 5일 오전 9시에..." |
| **준비물** | 챙겨야 할 물건 | "도시락과 물을 준비해 주세요." |
| **제출** | 서류·동의서 제출 | "동의서를 담임선생님께 제출해 주세요." |
| **비용** | 금액·납부 관련 | "급식비 65,000원을 납부해 주세요." |
| **건강·안전** | 건강·안전 지침 | "발열 증상 시 등교를 자제해 주세요." |
| **기타** | 위에 해당 없음 | "궁금한 사항은 담임선생님께 문의..." |

## 백엔드 연결 구조 이해하기

백엔드 `backend/app/services/classifier.py`가 이렇게 호출합니다:

```python
from src.predict import predict_one
result = predict_one("납부할 급식비는 6만 5천원입니다.", model="simple")
# → {"category": "비용", "confidence": 0.87, "model_used": "simple"}
```

`predict.py`의 `predict_one()`이 **모든 모델의 단일 창구**입니다.  
`model="simple"` → TF-IDF+LogReg 사용  
`model="kcelectra"` → KcELECTRA 파인튜닝 모델 사용  
`model="auto"` → KcELECTRA 체크포인트 있으면 사용, 없으면 simple로 자동 전환

---

## 파일별 역할 상세 설명

### `data/notice_sample_v3.csv`
학습 데이터 파일입니다. 컬럼 2개 (`text`, `category`).

- 150개의 문장이 미리 라벨링 되어 있습니다
- 각 카테고리당 약 20~25개씩 균등하게 구성
- **더 많은 데이터를 추가할수록 모델 성능이 향상됩니다**
  - 형식: `문장,카테고리` (맨 아래에 행 추가)
  - 카테고리는 반드시 `일정`, `준비물`, `제출`, `비용`, `건강·안전`, `기타` 중 하나

### `src/classifier_simple.py` — 베이스라인 (TF-IDF + Logistic Regression)

**왜 TF-IDF인가?**
- TF-IDF는 각 단어가 문서에서 얼마나 중요한지 숫자로 나타냅니다
- "납부", "입금", "원" 같은 단어가 **비용** 카테고리에서 많이 나오면 높은 점수를 받음
- GPU 없이 CPU에서 수십 ms만에 실행 — 백엔드 서버 부담 없음

**왜 char_wb n-gram인가?**
- 한국어는 "납부해" "납부하여" "납부하시기" 등 동사 변형이 많음
- 글자 단위 2~4글자 조합(`ngram_range=(2,4)`)으로 형태소 변형 문제 해결
- 예: "납부" → "납부", "부하", "부해", "납부하" 등으로 분해해 학습

**사용법:**
```bash
cd model/classification
python src/classifier_simple.py          # 학습 + 저장
python src/classifier_simple.py --eval   # 테스트 평가
```

### `src/classifier_kcelectra.py` — KcELECTRA 추론 모듈

**왜 KcELECTRA인가?**
- 한국어 특화 사전학습 모델 (윤정님 모델과 동일한 backbone!)
- ELECTRA 구조: BERT보다 학습 효율이 2~3배 좋음
- `koelectra-small`: 메모리 사용량 적어 CPU 서버에서도 동작

**중요:** 이 파일은 **추론만** 합니다. 학습은 `notebooks/01_train_kcelectra.ipynb`에서.

학습이 끝나면 `checkpoints/kcelectra-category/` 폴더가 생깁니다.
이 폴더가 없으면 `is_ready()` 함수가 False를 반환하여 simple로 자동 전환됩니다.

### `src/predict.py` — 백엔드 진입점

**왜 이 파일이 중요한가?**
- 백엔드가 `from src.predict import predict_one`으로 이 함수를 호출
- 내부에서 어떤 모델을 쓸지 결정하는 로직 포함
- `model="auto"`로 설정하면 체크포인트 유무에 따라 자동 선택

**반환 형식:**
```python
{
    "text":       "납부할 급식비는 6만 5천원입니다.",
    "category":   "비용",       # 최종 분류 결과
    "confidence": 0.87,         # 얼마나 확신하는지 (0~1)
    "model_used": "simple",     # 실제 사용된 모델
    "probs": {                  # explain=True일 때만 포함
        "일정": 0.02,
        "비용": 0.87,
        ...
    }
}
```

### `scripts/split_dataset.py` — 데이터 분할

**왜 딱 한 번만 실행해야 하는가?**
- 베이스라인과 KcELECTRA가 **완전히 동일한** 데이터로 학습/평가해야 공정한 비교 가능
- 한 번 분할하면 `split_v1.csv`에 고정 저장
- 랜덤 시드 42로 고정 → 언제 실행해도 같은 결과

```bash
python scripts/split_dataset.py         # 최초 1회 실행
python scripts/split_dataset.py --force # 강제 재생성 (비추천)
```

분할 비율: **Train 80% / Val 10% / Test 10%**  
Stratified Split: 각 카테고리에서 균등하게 뽑음

### `scripts/evaluate_compare.py` — 성능 비교

두 모델을 같은 test 데이터로 평가하고 결과를 저장합니다.

```bash
python scripts/evaluate_compare.py
```

생성 파일:
- `data/eval_results_simple.json` — 베이스라인 상세 결과
- `data/eval_results_kcelectra.json` — KcELECTRA 상세 결과
- `data/eval_comparison_summary.csv` — 두 모델 비교 요약

---

## 실행 순서 (처음부터 전부 하려면)

### Step 1. 데이터 분할 (딱 한 번)
```bash
cd c:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification
python scripts/split_dataset.py
```

### Step 2. 베이스라인 학습
```bash
python src/classifier_simple.py
```
`checkpoints/simple_tfidf_logreg.pkl` 파일이 생성됩니다.

### Step 3. KcELECTRA 파인튜닝 (Colab GPU 필요)
1. Google Colab 접속 → 런타임 → 런타임 유형 변경 → **GPU**
2. `notebooks/01_train_kcelectra.ipynb` 업로드
3. `data/notice_sample_v3.csv`와 `data/split_v1.csv` 업로드
4. 모든 셀 순서대로 실행 (~20분)
5. `checkpoints/kcelectra-category/` 폴더 다운로드
6. 로컬 `checkpoints/kcelectra-category/`에 붙여넣기

### Step 4. 성능 비교
```bash
python scripts/evaluate_compare.py
```

### Step 5. 시각화 확인
Jupyter에서 `notebooks/02_evaluate_compare.ipynb` 열어서 실행.

---

## 평가 지표 설명

### Macro F1 (메인 지표)
- 6개 카테고리 각각의 F1을 구한 뒤 **평균**
- 클래스 불균형에 강함 (특정 클래스가 많아도 편향 없음)
- **0.8 이상이면 좋은 성능**

### F1 Score = 2 × (Precision × Recall) / (Precision + Recall)
- **Precision (정밀도):** "비용이라고 예측한 것 중 실제로 비용인 비율"
- **Recall (재현율):** "실제 비용인 것 중 비용이라고 맞춘 비율"
- F1은 이 둘의 균형

### Confusion Matrix
행 = 실제 카테고리, 열 = 예측 카테고리  
대각선이 클수록 좋음 (맞게 분류한 것들)

---

## KcELECTRA 채택 기준

> Simple 대비 **Macro F1이 5% 이상 향상**되면 KcELECTRA 채택

- ΔF1 ≥ +0.05 → KcELECTRA 채택, predict_one에서 `model="kcelectra"`로 변경
- ΔF1 < 0.05 → Simple 유지 (안정성 우선)
- Simple은 항상 fallback으로 유지

---

## 자주 묻는 질문

**Q. 베이스라인 학습이 안 되고 파일을 못 찾는다고 에러가 난다면?**  
→ `cd model/classification` 후 실행하세요. 경로 기준이 `model/classification/`입니다.

**Q. 데이터를 더 추가하고 싶은데 어떻게 하나요?**  
→ `data/notice_sample_v3.csv` 맨 아래에 `문장,카테고리` 형식으로 행 추가.  
단, split_v1.csv가 없는 상태라면 추가 후 `split_dataset.py` 실행.  
이미 split_v1.csv가 있다면 `--force`로 재분할.

**Q. KcELECTRA 학습이 CUDA OOM 에러가 난다면?**  
→ `01_train_kcelectra.ipynb`의 `BATCH_SIZE = 16`을 `8`로 줄이세요.

**Q. predict_one이 항상 "기타"만 반환한다면?**  
→ 베이스라인 모델(pkl 파일)이 없는 것. `python src/classifier_simple.py` 먼저 실행.

# 지금 바로 실행할 순서:

python scripts/split_dataset.py → 데이터 분할
python src/classifier_simple.py → 베이스라인 학습
Colab에서 notebooks/01_train_kcelectra.ipynb → KcELECTRA 파인튜닝 (GPU)
python scripts/evaluate_compare.py → 두 모델 성능 비교
notebooks/02_evaluate_compare.ipynb → 시각화 차트 생성 (발표 근거 자료)
백엔드가 호출하는 predict_one() 인터페이스는 기존과 완전히 호환되며, model="simple" / "kcelectra" / "auto" 세 가지 모드를 지원합니다. 자세한 설명은 README2.md와 devlog_2026-04-30.md를 참고.

## 14. 모델 명칭 정정 및 v3_2 시작 (2026-05-09)

### 14-1. 모델 명칭 오류 발견

> v3~v7까지 전 과정에서 **KcELECTRA라고 부른 모델이 실제로는 KoELECTRA였다.**

| 이름 | HuggingFace ID | 만든 곳 | 이 프로젝트 사용 여부 |
|---|---|---|---|
| KoELECTRA | `monologg/koelectra-base-v3-discriminator` | monologg (박장원) | **v3~v7, v3_1 모두 이것** |
| KcELECTRA | `beomi/kcelectra-base` | beomi (이준범) | **v3_2부터 시작** |

### 14-2. 기존 성능 지표는 유효한가?

**결론: 내부적으로 일관성 있고 공정하다.**

기존 devlog와 06_visualize_comparison_v3_20260505.ipynb의 성능 수치는 여전히 유효합니다. v3~v7, v3_1 전체가 동일하게 KoELECTRA를 일관되게 사용했기 때문에 두 모델이 "섞인" 것이 아니라 일관된 KoELECTRA vs Simple 비교였습니다. 단, "KcELECTRA"라는 표기가 잘못된 것이었습니다. 

= 따라서 기존 비교(Simple vs KoELECTRA 파인튜닝)의 성능 수치 자체는 올바르다.
단, 보고서에 "KcELECTRA"라고 표기한 부분은 실제로 KoELECTRA에 대한 결과였다.

생성된 v3_2 파일 3개
파일	역할
notebooks/12_train_kcelectra_v3_2_20260509.ipynb	Colab 학습 — beomi/kcelectra-base (진짜 KcELECTRA)
scripts/evaluate_compare_v3_2_20260509.py	로컬 평가 실행
notebooks/13_visualize_comparison_v3_2_20260509.ipynb	시각화 그래프 생성

Simple 기준값은 0.7590 (v3_1 데이터 기준)으로 설정되어 있습니다.

### 14-3. v3_2 시작 — 진짜 KcELECTRA 적용

기존 v3_1 파일들은 그대로 두고, **v3_2** 버전으로 진짜 KcELECTRA를 적용한다.

| 항목 | v3_1 | v3_2 |
|---|---|---|
| 데이터 | split_v3_1_20260509.csv (15948행) | split_v3_1_20260509.csv (동일) |
| **모델** | KoELECTRA (`monologg/koelectra-base-v3-discriminator`) | **KcELECTRA (`beomi/kcelectra-base`)** |
| Simple 기준 F1 | 0.7590 | 0.7590 (동일) |