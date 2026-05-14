# 카테고리 분류 모델 — 경이님 작업 가이드

> 이 문서는 경이님이 작업 내용을 빠르게 이해하고 바로 실행할 수 있도록 작성되었습니다.  
> 코드가 **왜** 이렇게 짜여졌는지, **무엇**을 하는지 중심으로 설명합니다.

---

## 전체 구조 한눈에 보기

```
model/classification/
├── data/
│   ├── notice_sample_v3.csv        ← 경이님이 라벨링한 학습 데이터 (150개)
│   └── split_v1.csv                ← train/val/test 분할 (scripts 실행 후 생성됨)
├── src/
│   ├── predict.py                  ← 백엔드 진입점 (이게 핵심!)
│   ├── classifier_simple.py        ← 베이스라인 모델 (TF-IDF + LogReg)
│   └── classifier_kcelectra.py     ← KcELECTRA 추론 모듈
├── scripts/
│   ├── split_dataset.py            ← 데이터 분할 (딱 한 번만 실행)
│   └── evaluate_compare.py         ← 두 모델 성능 비교
├── notebooks/
│   ├── 01_train_kcelectra.ipynb    ← GPU 학습 (Colab에서 실행)
│   └── 02_evaluate_compare.ipynb   ← 성능 비교 시각화
├── checkpoints/
│   ├── simple_tfidf_logreg.pkl     ← 베이스라인 모델 저장 파일 (학습 후 생성)
│   └── kcelectra-category/         ← KcELECTRA 파인튜닝 결과 (Colab 후 복사)
└── README2.md                      ← 지금 이 파일
```

---

## 파이프라인에서 경이님 역할

전체 가정통신문 분석 시스템에서 경이님 모델은 **[4]번 단계**를 담당합니다.

```
[3] 윤정님 모델 (할일 추출)
        ↓
       text: "체험학습 비용 20,000원을 납부해 주세요."
             ↓
[4] 경이님 모델 (카테고리 분류)  ← 여기!
        ↓
    category: "비용"
        ↓
[5] 번역 → [6] 응답 빌드 → [7] TTS
```

**윤정님이 추출한 문장들이 경이님 모델로 들어오고**, 경이님 모델이 각 문장을 6개 카테고리 중 하나로 분류합니다.

---

## 6가지 카테고리 설명

| 카테고리 | 의미 | 예시 |
|--------|------|------|
| **일정** | 날짜·시간·행사 관련 | "운동회는 10월 5일 오전 9시에..." |
| **준비물** | 챙겨야 할 물건 | "도시락과 물을 준비해 주세요." |
| **제출** | 서류·동의서 제출 | "동의서를 담임선생님께 제출해 주세요." |
| **비용** | 금액·납부 관련 | "급식비 65,000원을 납부해 주세요." |
| **건강·안전** | 건강·안전 지침 | "발열 증상 시 등교를 자제해 주세요." |
| **기타** | 위에 해당 없음 | "궁금한 사항은 담임선생님께 문의..." |

---

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

##4월30일##작업 완료 — feature/kyeongyi-classification 브랜치
model/classification/ 폴더에 다음 구조가 완성됐습니다:


model/classification/
├── data/
│   ├── notice_sample_v3.csv         ← 새로 만든 학습 데이터 (150개, 6카테고리 균등)
│   ├── notices_labeled_v2.csv       ← 기존 라벨 데이터 복원 (병합 학습에 사용)
│   └── notices_labeled_v2.jsonl     ← 기존 원본 데이터 복원
├── src/
│   ├── predict.py                   ← 백엔드 진입점 (predict_one 함수)
│   ├── classifier_simple.py         ← 베이스라인: TF-IDF + LogReg (CPU)
│   └── classifier_kcelectra.py      ← KcELECTRA 추론 모듈
├── scripts/
│   ├── split_dataset.py             ← 데이터 공정 분할 (딱 한 번 실행)
│   └── evaluate_compare.py          ← 두 모델 성능 비교
├── notebooks/
│   ├── 01_train_kcelectra.ipynb     ← GPU 학습 (Colab T4, ~20분)
│   └── 02_evaluate_compare.ipynb    ← 성능 비교 시각화
├── checkpoints/                     ← 학습 후 모델 파일 저장 위치
├── docs/
│   └── devlog_2026-04-30.md         ← 오늘 개발일지
└── README2.md                       ← 상세 가이드

# 지금 바로 실행할 순서:

python scripts/split_dataset.py → 데이터 분할
python src/classifier_simple.py → 베이스라인 학습
Colab에서 notebooks/01_train_kcelectra.ipynb → KcELECTRA 파인튜닝 (GPU)
python scripts/evaluate_compare.py → 두 모델 성능 비교
notebooks/02_evaluate_compare.ipynb → 시각화 차트 생성 (발표 근거 자료)
백엔드가 호출하는 predict_one() 인터페이스는 기존과 완전히 호환되며, model="simple" / "kcelectra" / "auto" 세 가지 모드를 지원합니다. 자세한 설명은 README2.md와 devlog_2026-04-30.md를 참고.