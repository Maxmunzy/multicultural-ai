# 모델 B — 가정통신문 분류 + 중요도 (경이)

다문화 가정 학부모 알림 AI 파이프라인의 두 번째 단계 모델이다.

```
가정통신문 텍스트
        ↓ 모델 A (윤정) — 추출
할 일 문장 (예: "내일까지 동의서를 제출해 주세요")
        ↓ 모델 B (경이) — 본 모듈
{ category: "제출", importance: 0.98, action_required: "Y" }
        ↓ 모델 C (세종) — 번역 + TTS
베트남어 음성 안내
```

## 핵심 설계

| 컴포넌트 | 역할 | 기본 구현 | Production 옵션 |
| --- | --- | --- | --- |
| 분류기 | 추출 문장 → 6개 카테고리 | numpy LR + TF-IDF (의존성 0) | sklearn LR / SBERT+LightGBM / KoELECTRA fine-tune / Qwen2.5 LoRA |
| 시급도 룰 | 시간 표현·키워드로 0~1 점수 | `feature_engineering.py` (정규식 기반) | 동일 |
| 중요도 회귀 | 학습된 회귀 + 룰 점수 가중 결합 | numpy Ridge | sklearn / LightGBM Regressor |
| API | 백엔드 연결 (`/classify`) | FastAPI | 동일 |

### 카테고리 (`config.LABELS`)

`일정`, `준비물`, `제출`, `비용`, `건강·안전`, `기타`

### 중요도 (0~1)

- `1.0` — 즉시 행동 필요 (내일 마감, 감염병 확진 등)
- `0.85~0.95` — 놓치면 문제 (주중 마감 제출/납부)
- `0.7~0.85` — 일정 확인 / 가정 지도 필요
- `0.5~0.7` — 참고성 정보
- `< 0.5` — 일반 공지 (행동 불필요)

## 폴더 구조

```
model/classification/
├── README.md
├── requirements.txt
├── src/
│   ├── config.py                      # 라벨/경로/하이퍼파라미터
│   ├── data_loader.py                 # 두 출처 통합 + stratified split
│   ├── feature_engineering.py         # 시급도 룰 + 키워드 피처
│   ├── text_features.py               # numpy TF-IDF
│   ├── classifier_simple.py           # numpy 기반 (의존성 0, 데모/백업)
│   ├── classifier_sklearn.py          # sklearn LR (production 베이스라인)
│   ├── classifier_sbert.py            # SBERT + LightGBM (메인 권장)
│   ├── classifier_kobert.py           # KoBERT/KoELECTRA fine-tune + Qwen2.5
│   ├── importance_scorer.py           # 룰 + Ridge 회귀 결합
│   ├── train.py                       # 학습 진입점
│   ├── predict.py                     # 추론·CSV 빈 칸 채우기
│   ├── evaluate.py                    # F1·MAE·Spearman 평가
│   ├── fill_yunjeong_extracted.py     # 모델 A 출력 → 모델 B로 채우기
│   └── api.py                         # FastAPI 서버
├── data/                              # 입력 데이터
└── outputs/
    ├── models/                        # 학습된 가중치
    ├── reports/                       # 평가 보고서 (md+json)
    └── predictions/                   # 채운 결과 CSV/JSON
```

## 빠른 시작

### 1) 의존성 0으로 (numpy + pandas만)

```bash
python -m src.train --model simple
python -m src.predict --text "내일까지 동의서를 제출해 주세요" --today 2026-04-27
```

### 2) sklearn 베이스라인

```bash
pip install scikit-learn joblib
python -m src.train --model sklearn
```

### 3) SBERT + LightGBM (메인 권장)

```bash
pip install sentence-transformers lightgbm joblib torch --index-url https://download.pytorch.org/whl/cpu
python -m src.train --model sbert
```

처음 실행 시 `paraphrase-multilingual-MiniLM-L12-v2`(50MB)를 자동 다운로드한다.
실패 시 `jhgan/ko-sroberta-multitask`로 fallback.

### 4) KoBERT/KoELECTRA fine-tune

```bash
pip install torch transformers
python -m src.train --model kobert --epochs 5
```

CPU에서 epoch당 2~3분 (300건 기준). Colab 무료 GPU 사용 권장.

### 5) Qwen2.5 zero-shot (학습 없이)

```python
from src.classifier_kobert import qwen_zero_shot_predict
qwen_zero_shot_predict("내일까지 동의서를 제출해 주세요")  # → '제출'
```

## CSV 빈 칸 채우기 (이미지 시나리오)

```bash
python -m src.predict --input data/new_notices.csv \
                     --output outputs/predictions/filled.csv \
                     --today 2026-04-27
```

- 입력 CSV의 `category`/`importance`가 비어 있는 행만 채운다 (사람 라벨 보호).
- `--overwrite`로 모든 행 덮어쓰기 가능.

### 모델 A 출력 채우기

윤정님이 보낸 `extracted_results.json`처럼 todo 단위 JSON을 그대로 넣으면 카테고리/중요도가 채워져 나온다:

```bash
python -m src.fill_yunjeong_extracted --today 2026-04-27
# → outputs/predictions/extracted_results_filled.json
```

## API 서버 (태수님 백엔드 연결용)

```bash
pip install fastapi uvicorn
uvicorn src.api:app --host 0.0.0.0 --port 8001
```

```bash
curl -XPOST http://localhost:8001/classify \
  -H 'content-type: application/json' \
  -d '{"text":"내일까지 동의서를 제출해 주세요","today":"2026-04-27"}'
```

응답:
```json
{
  "category": "제출",
  "importance": 0.98,
  "action_required": "Y",
  "urgency_score": 0.93,
  "days_to_deadline": 1,
  "has_deadline": false,
  "has_submit_verb": true
}
```

## 성능 (test=61, simple 트랙 기준)

| 항목 | 값 | MVP 목표 | 결과 |
| --- | --- | --- | --- |
| accuracy | **0.803** | ≥ 0.80 | 달성 |
| macro F1 | **0.784** | ≥ 0.75 | 달성 |
| weighted F1 | **0.806** | — | — |
| importance MAE | **0.082** | < 0.10 | 달성 |
| importance Spearman | **0.690** | — | — |
| 고중요(≥0.85) precision | **0.900** | — | "내일 마감" 안내 90% 정확 |

SBERT/KoELECTRA 사용 시 +3~7%p 추가 향상이 일반적이다.

## 시급도 룰의 핵심 (importance 정확도의 비결)

`feature_engineering.py`가 텍스트에서 직접 다음을 추출:

| 신호 | 패턴 예 | 영향 |
| --- | --- | --- |
| 즉시성 | "오늘", "당일", "내일" | urgency ≥ 0.93 |
| 절대 마감 | "4월 30일까지", "5월 1일까지" | days_to_deadline 정확히 계산 |
| 요일 마감 | "이번 주 금요일까지" | 다가오는 그 요일까지 일수 |
| 상대 일수 | "5일 이내" | days_to_deadline = 5 |
| 행동 불필요 | "자동이체", "배부됩니다" | importance × 0.6 |
| 건강 위급 | "감염병 확진", "발열", "즉시 연락" | importance + 0.05 |
| 카테고리 키워드 | "동의서/신청서/조사서/체육복/..." | 분류 보조 피처 |

`days_to_deadline`은 지수 감쇠(τ=10)로 시급도로 변환한다.

## 다른 팀과의 인터페이스

### 입력 (모델 A → 모델 B)

```json
{"text": "내일까지 동의서를 제출해 주세요"}
```

### 출력 (모델 B → 모델 C)

```json
{
  "category": "제출",
  "importance": 0.98,
  "action_required": "Y",
  "urgency_score": 0.93,
  "days_to_deadline": 1
}
```

`action_required`는 모델 C의 TTS 우선순위 결정에 사용된다.

## 향후 개선 포인트

1. **데이터 증강**: 윤정 jsonl 비-todo 문장을 negative `기타` 샘플로 추가 → '기타' 클래스 F1 0.50 → 0.70+ 가능
2. **SBERT 도메인 어댑테이션**: ko-sroberta를 가정통신문에 simCSE로 추가 학습
3. **importance 라벨 일관성**: 0.05 단위 라벨이 사람마다 ±0.10 흔들림 → 라벨링 가이드 보강 필요
4. **다국어 zero-shot**: 베트남어 입력에서도 직접 분류 (NLLB embedding 활용)
