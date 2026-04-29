전체 파이프라인 (확정 버전)

┌──────────────────────────────────────────────────────────────────┐
│ 호스트 앱 → POST /notice/analyze                                  │
│   body: HWP/PDF (multipart) or text (json)                        │
└──────────────────────────────────────────────────────────────────┘
            ↓
[1] 텍스트 변환  (services/parser.py — 신설)
    · text     → passthrough
    · PDF      → pdfplumber + table 분리
    · HWP/HWPX → LibreOffice + pdfplumber
    · 이미지   → 세종님 OCR (연휴 후 합류)
    → output: clean_text (str)

            ↓
[2] 정규식 슬롯 추출  (services/slot_extractor.py — 이미 구현)
    · dates / times / amounts (이미 있음)
    · urls / phones (NEW — 추가 필요)
    · 통신문 전체 단위. summary용 재료.
    → output: regex_slots (dict)

            ↓
[3] 할일 추출  (services/extractor.py — 윤정님 v2 wrapper)
    입력:  clean_text
    내부:  문장분리 → binary 분류(0.5컷) → 정규식(due_date/amount/action_hint)
    출력:  list[YunjeongTodo]
           각 항목: { text, source, due_date, amount,
                     confidence, action_hint }
    빈 리스트면 items 없음.

            ↓
[4] 카테고리 분류  (services/classifier.py — 경이님 6-class wrapper)
    입력:  각 todo.text
    출력:  category ∈ {일정, 준비물, 제출, 비용, 건강·안전, 기타}

            ↓
[5] 번역  (services/translator.py — 이미 구현, 보강 필요)
    슬롯 단위:
      · dates/times/amounts → i18n formatter (deterministic, NLLB 안 거침)
      · urls/phones        → ko 그대로 (NEW)
      · places/supplies    → glossary lookup → 없으면 NLLB
    본문 단위 (todo.text):
      · URL/전화 ⟦P0⟧ 토큰 치환 → NLLB → 토큰 복원 (NEW, 보호)
      · glossary injection → NLLB

            ↓
[6] 응답 빌드  (routers/notice.py)
    summary = SummarySlots(
        dates, times, amounts, urls, phones,    # 정규식
        places, supplies, deadlines              # items에서 집계
    )
    items = [
        AnalyzeItem(
            text_ko        = todo.text,
            title_translated = ...번역...,
            category       = 경이(todo.text),    # 주제 (6-class)
            action_hint    = todo.action_hint,   # 행동 (신청/제출/...)
            due_date       = todo.due_date,
            amount         = todo.amount,
            importance     = todo.confidence,
            ...
        )
        for todo in yunjeong_todos
    ]

            ↓
[7] TTS  (services/tts.py — 이미 구현)
    슬롯 + 할일 합쳐 문장별 mp3 생성.
    importance 내림차순 정렬.

            ↓
JSON 응답 → 호스트 앱
{
    "summary": SummarySlots,
    "items":   [AnalyzeItem, ...],
    "tts_url": "...",
    ...
}


### 카테고리 분류-경이님

`일정`, `준비물`, `제출`, `비용`, `건강·안전`, `기타`


# 가장 중요한 핵심과제: 모델 성능 비교 (베이스라인 VS. 파인튜닝)
1. 조건: 베이스라인 모델, 파인튜닝한 모델에 들어가는 input data가 동일한 데이터셋 및 동일한 조건에서 두 모델의 성능을 비교. 다시 말해서, 기존에 있던 모델을 가지고 동일한 조건을 맞춰서 일정, 준비물, 제출, 비용, 건강·안전, 기타에 대한 분류 성능 점수가 나와야하고 파인튜닝한 모델을 동일한 조건으로 6가지 분류 성능 점수가 나와야 비교가 가능. 그래서 파인튜닝된 모델이 베이스라인모델보다 성능이 좋다라는 지표가 나와야 성능의 우수함을 입증할 수 있음. 근거 자료를 만들어야 함. 

2. 두 모델(베이스라인 모델, 파인튜닝한 모델)에 들어가는 데이터는 답안지가 없기 때문에 accuracy가 아닌 그 모델의 맞는 평가 방식 및 성능 지표를 뽑아야 함. 사용하고자 하는 모델들의 기능을 자세한 설명 듣기.

예시로, Precision이라고 하면 10개 단어 중에 2개 단어만 맞췄다. 그래서 그 모델로 해서 모든 텍스트 데이터 돌아서 몇 프로 맞췄으니까 얘는 성능이 얼마다 라고 얘기하는 것도 있다.

==> 파인튜닝의 성능이 베이스라인 성능보다 좋은 쪽으로 모델이 나와야하고 그 모델에 맞는 평가 지표가 나와야 한다. 글씨로 정리하는 것 뿐만아니라 시각적인 도구를 활용해서 그래프 혹은 직선 사용 등으로 제시할 근거 자료가 필요.


# 윤정님 데이터 정보들

-원본 데이터 : \data\galsan_txt 
-전처리 파일 : file/preprocess_txt_to_jsonl.py
-전처리 후 데이터 : data/v2.1_notices_galsan.jsonl

-윤정님이 전처리 후 데이터로 모델 학습 시켰고 실 서비스에서
데이터 넣고 나오는 아웃풋을 보려면 predict.py를 돌려봐야
하고 그 predict.py의 아웃풋이 경이님 모델로 들어감. 

-predict.py를 경이님 모델의 인풋으로 해서 넣어야 함.
results.append({
            "text":        sentence,
            "source":      source,
            "due_date":    extract_due_date(sentence),
            "amount":      extract_amount(sentence),
            "confidence":  round(confidence, 4),
            "action_hint": extract_action_hint(sentence),
        })
[
  {
    "text": "모국어를 사용하는 강사가 단계별로 친절히 가르치는 동영상 강의(VOD)를 PC나 모바일 기기로 접속하여 언제든지 원하는 장소에서 편리하게 학습할 수 있는 좋은 기회이오니, 한국어 학습이 필요한 다문화가정 학생 및 학부모(보호자) 모두 기한 내 신청하여 주시기 바랍니다.",
    "source": "sample_pdfplumber.txt",
    "due_date": null,
    "amount": null,
    "confidence": 0.9946,
    "action_hint": "신청"
  }
]

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

비교 실험 설계 가이드
후보 모델 선정 (3~4개가 최대)
모델    카테고리    학습 시간    강점    약점
TF-IDF + LogReg    베이스라인 (필수)    수초    빠름, 가벼움    OOV·문맥 약
SBERT + LightGBM    임베딩 ML    분    의미 유사도    도메인 적응 약
KcELECTRA-small fine-tune    한국어 BERT    20~30분    도메인 학습    base 한국 일반
KoBERT fine-tune    한국어 BERT    20~30분    한국어 특화    KcELECTRA와 비슷
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

KoELECTRA(A단계)와 겹치지 않고, KLUE 벤치마크에서 한국어 분류 SOTA. 파인튜닝이 안정적이고 허깅페이스에서 바로 쓸 수 있음.



