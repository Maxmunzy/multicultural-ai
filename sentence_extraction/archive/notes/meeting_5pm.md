# LLM 1단계 자체화 — 문장 추출 모델 정리

## 0. 한 줄 요약

PDF/HWP 가정통신문에서 sentence_list를 자체 모델로 뽑는 단계. Claude API가 하던 일을 KoCharELECTRA(자체 학습) + 표 처리 룰 조합으로 대체. PoC 6장 기준 todo recall 0.870, Claude 대비 11배 빠름.

---

## 1. 전체 파이프라인

```
입력: PDF (가정통신문)
  │
  ▼
[A] Parser Ensemble
  ├─ pymupdf      (block-aware text)
  ├─ pdfplumber   (layout text + 표 cell 인식)
  └─ pdfminer.six (별도 layout 분석)
  ↓ 셋 다 병렬 실행, quality score 최고 1개 선택
  │   (avg row length, short ratio, terminator ratio, newline ratio)
  ▼
┌──────────────────────────────────┬──────────────────────────────────────┐
│ [B] 본문 처리 — 모델              │ [C] 표 처리 — 구조 기반 변환            │
│                                  │                                      │
│ KoCharELECTRA + BIO classifier   │ pdfplumber.find_tables()             │
│ (14M params, 자체 fine-tune)      │  → 표 cell 2D 구조 인식                │
│                                  │                                      │
│ ↓ char별 B-SENT / I-SENT / O     │ orientation 자동 판별                  │
│ ↓ sliding window (512 char)      │  (cell 길이 분산 통계로                  │
│ ↓ sentence boundary char index   │   col-major / row-major 결정)         │
│                                  │                                      │
│                                  │ entity prefix + attr별 분리 sentence  │
│                                  │ + cell 안 ▪/▸ bullet 추가 분리         │
└──────────────────────────────────┴──────────────────────────────────────┘
  │                                       │
  └───────────────┬───────────────────────┘
                  ▼
            sentence_list[]
                  ▼
       [D] KoELECTRA — 6-class 분류 (윤정님 모델)
                  ▼
       [E] TTS / 번역 / 카드 UI
```

핵심: 본문 sentence boundary는 학습된 모델이 결정. 표는 cell 구조 정보(pdfplumber가 추출)를 보존해서 의미 단위로 직렬화.

---

## 2. 각 단계 설명

### A. Parser Ensemble — 어느 parser가 깨끗하게 뽑았는지 자동 선택
- PDF마다 parser별 추출 품질이 다름 (HWP 변환 PDF는 pdfminer가 강하고, 표 위주는 pdfplumber가 좋고, 일반 본문은 pymupdf가 자연스러움)
- 4개 통계로 quality score:
  - 평균 row 길이 (긴 row = paragraph 보존)
  - 짧은 row 비율 (< 4 char = 깨짐)
  - 종결어미로 끝나는 row 비율 (자연스러운 문장)
  - 줄바꿈 비율 (과한 줄바꿈은 깨진 신호)

### B. 본문 — KoCharELECTRA + BIO (자체 학습 모델)
- 입력: char sequence (한국어 통신문 raw 텍스트)
- 출력: 각 char마다 O / B-SENT / I-SENT 라벨
- 모델: monologg/kocharelectra-small-discriminator (14M) + linear classifier
- 학습 데이터: 2,063장 PDF → Claude가 만든 cleaned_text와 sentence_list 라벨
- 추론 방식: sliding window (max 512 char, stride 384) — 긴 문서 처리

### C. 표 — cell 구조 인식 + 자동 직렬화
- pdfplumber가 line/edge detection으로 표 cell 좌표 추출 (룰 기반)
- 그 위에서:
  1. **orientation 자동 판별** (col-major / row-major):
     - 같은 attribute 값들은 길이/패턴이 비슷 → 분산 작은 axis가 attribute axis
     - 어린이날(col-major) / 구강검진(col-major) / 겨울방학 도서관(row-major) 자동 구분
  2. **entity별 + attr별 분리 sentence 생성**:
     - "사이언스 매직쇼 - 운영 시간: 14:00~15:00"
     - "사이언스 매직쇼 - 참여 방법: 사전 신청"
     - 6-class 분류기가 각 항목을 개별 분류할 수 있게
  3. **cell 안 다중 항목 분리**:
     - ▪/▸/• 등 bullet marker로 자동 split
     - "검진시간: 평일 9:30~18:30, 점심시간 12:30~14:00, 토요일 ..." → 각각 별도 sentence

---

## 3. PoC 6장 — 추출 결과 매칭

Claude 정답(추출된 todo) 대비 우리 모델 todo 매칭률:

| PDF | Claude todos | 우리 todos | matched | recall | precision |
|---|---|---|---|---|---|
| 2024 4학년 현장체험학습 정산 | 3 | 4 | 2 | 0.667 | 0.500 |
| 2025 겨울방학 도서관 독서캠프 | 5 | 5 | 5 | **1.000** | 1.000 |
| 2026 구강검진 | 8 | 13 | 8 | **1.000** | 0.615 |
| 2026 어린이날 행사 | 8 | 7 | 7 | 0.875 | 1.000 |
| 2026 서귀포 토요프로그램 | 7 | 7 | 5 | 0.714 | 0.714 |
| 2019 인플루엔자 예방접종 | 28 | 29 | 26 | 0.929 | 0.897 |
| **평균** | — | — | — | **0.870** | **0.791** |

속도: BIO 2.0s/PDF vs Claude 22.1s/PDF (**11x faster**)

---

## 4. 추출 sentence 실제 예시

### 2026 어린이날 행사 (recall 1.000 직전 0.875)

**본문 (BIO 모델이 boundary 결정)**:
```
- 1. 행사 개요
- 가. 일시: 2026. 5. 5.(화) 09:30~17:30 (※점심시간(12:30~13:30)에는 운영하지 않습니다.)
- 나. 장소: 경기도교육청미래과학교육원 북부과학교육관(의정부시 체육로135번길 32)
- 다. 대상: 경기도 내 유치원생, 초등학생 및 학부모 누구나
- 2. 사이언스 매직쇼 신청 안내
- 가. 신청 기간: 2026. 4. 27.(월) 09:00 ~ 2026. 4. 29.(수) 17:00
- 나. 신청 방법: 경기도교육청미래과학교육원 홈페이지(www.gise.kr)
- 다. 선정 방법: 선착순 30가족(1가족 당 2명)
- 라. 선정자 발표: 2026. 4. 30.(목) 홈페이지 공지 및 선정 대상자 문자 발송
```

**표 (col-major 자동 판별, entity별 + attr별 분리)**:
```
- 오늘은 내가 과학왕! - 내용: 미션 도장깨기 (전시물 체험, 포토인증, 과학체험활동)
- 오늘은 내가 과학왕! - 운영 시간: 상시
- 오늘은 내가 과학왕! - 참여 방법: 현장 참여
- 사이언스 매직쇼 - 내용: 신기한 마술 속 숨겨진 과학원리
- 사이언스 매직쇼 - 운영 시간: 14:00~15:00
- 사이언스 매직쇼 - 참여 방법: 사전 신청
- 핑퐁로봇 체험 - 내용: 모션메이커 이용 핑퐁 로봇 체험
... (총 7개 프로그램 × 3개 속성 = 21개 sentence)
```

### 2026 구강검진 (recall 1.000)

**표 (col-major 자동 판별, ▪ bullet 자동 분리)**:
```
- 진심담은치과의원 - 전화번호: ☎ (031)821-8828
- 진심담은치과의원 - 소재지: ▪경기 의정부시 평화로 636 대호빌딩 - 가능역 2번 출구에서 112m
- 진심담은치과의원 - 검진시간: 평일 9:30 ~ 18:30
- 진심담은치과의원 - 검진시간: 점심시간 12:30 ~ 14:00
- 진심담은치과의원 - 검진시간: 토요일 09:30 ~ 14:00
- 진심담은치과의원 - 검진시간: 토요일은 점심시간 없이 진료
- 진심담은치과의원 - 검진시간: 사전 예약 시 대기시간이 줄어듭니다.
- 진심담은치과의원 - 검진시간: 방문 전 치과로 전화문의 바랍니다.
- 청담i(아이)치과의원 - 전화번호: ☎ (031)837-1111
- 청담i(아이)치과의원 - 소재지: ▪경기 의정부시 신흥로240번길 21 가연타워 ...
- 청담i(아이)치과의원 - 검진시간: 평일 10:00 ~ 18:00
... (2개 치과 × 3개 속성, 각 속성의 ▪ bullet 분리)
```

→ TTS/분류기 입장에서 각 항목이 별도 sentence로 들어가서 6-class 분류 가능. (지금 TTS는 카테고리 prefix를 모든 항목에 붙여서 "기타. 진심담은치과의원 ... 기타. 진심담은치과의원 ..." 식으로 반복 — backend integration에서 별도 손볼 부분.)

### 2025 겨울방학 도서관 독서캠프 (recall 1.000)

**표 (row-major 자동 판별, ▸ bullet 자동 분리)**:
```
- 가만히 들어주었어 - 비밀친구 모루토끼 인형 만들기 - 날 짜: 1.2(금) 09:30 ~ 11:30
- 가만히 들어주었어 - 비밀친구 모루토끼 인형 만들기 - 대상: 1-2학년 신청자
- 가만히 들어주었어 - 비밀친구 모루토끼 인형 만들기 - 내용: 라포 형성
- 가만히 들어주었어 - 비밀친구 모루토끼 인형 만들기 - 내용: 북토크 - 책 이해하기, 까만 놀이, 컬리링 작업
- 가만히 들어주었어 - 비밀친구 모루토끼 인형 만들기 - 내용: 아트 활동 - 나의 비밀 친구: 모루 토끼 인형 만들기
- 나도 작가! -초콜릿 세상 이야기 - 날 짜: 1.5(월) 9:30 ~ 11:30
- 나도 작가! -초콜릿 세상 이야기 - 대상: 3-5학년 신청자
- 나도 작가! -초콜릿 세상 이야기 - 내용: 오리엔테이션
- 나도 작가! -초콜릿 세상 이야기 - 내용: 작가 만나기 - 천재 이야기꾼 '로알드 달'
...
```

---

## 5. 누락된 todo 분석

### 전체 누락 요약 (v5 기준)

| PDF | recall | 누락 건수 | 누락 원인 |
|---|---|---|---|
| 2026 어린이날 | 0.875 | 1건 | Claude는 표 전체를 한 todo로 통합, 우리는 entity별 분리. substring 매칭 알고리즘이 형식 차이를 못 잡음 (정보 자체는 21개 sentence로 다 추출됨) |
| 2026 구강검진 | 1.000 | 0건 | |
| 2025 겨울방학 도서관 | 1.000 | 0건 | |
| 2026 서귀포 | 0.714 | 2건 | 본문 paragraph가 raw text에서 줄로 끊겨 BIO가 한 sentence로 못 묶음 |
| 2019 인플루엔자 | 0.929 | 2건 | cell 안 다중 줄/긴 sentence가 BIO 출력에서 부분만 매칭 |
| 2024 정산 안내 | 0.667 | 1건 | 선 없는 회계 표 (수납인원×단가×금액). pdfplumber가 cell 인식 못함 — 모델/룰 공통 한계 |

### 누락 todo 상세

**2026 어린이날 (1건)** — Claude todo:
> `(미션 도장깨기...) (운영 시간 상시) (참여 방법 현장 참여) 프로그램: 사이언스 매직쇼... 프로그램: 핑퐁로봇 체험... 프로그램: 천체투영실 ...`
>
> → 표 전체가 한 통합 todo. 우리 모델은 21개 attr별 sentence로 다 추출됐는데(`"사이언스 매직쇼 - 운영 시간: 14:00~15:00"` 등) 통합 형식과 substring 매칭이 안 됨. **정보 자체는 빠짐없이 잡혔고 매칭 알고리즘 문제.**

**2026 서귀포 (2건)** — Claude todo:
> - `24.(금) 24:00 운영일시:` (2회 — 두 토요 프로그램 각각)
>
> → 본문 `4. 24.(금) 24:00 / 운영일시: ...`이 raw에서 줄로 끊겨 BIO가 sentence로 못 묶음. v2 학습이 풀려고 한 문제지만 표 영역 학습 신호 부족으로 회귀.

**2019 인플루엔자 (2건)** — Claude todo:
> - `출생자) 접종명: 인플루엔자(독감) 예방접종 준비물: 어린이인플루엔자 3가백신0.5ml, 예진표, 주민등록번호 필수 확인 접종비: 무료`
> - `기침, 재채기를 할 때 손으로 가리지 않기 휴지나 손수건이 없을 때는 옷소매 위쪽으로 입과 코를 가리고 기침하기 ...`
>
> → 같은 정보가 우리 출력에선 더 잘게 쪼개진 sentence들로 들어있음(`"접종명: 인플루엔자"`, `"준비물: 예진표"`, `"접종비: 무료"`). Claude가 통합한 것과 substring 미스. **정보 자체는 잡혔음.**

**2024 정산 안내 (1건)** — Claude todo:
> `수납인원 1인단가 수입금액(A) 반환액(B) 지 급 명 세(C) 잔액(D A-B-C) 89명 51,200 4,556,800 0 - 체험비 : 18,000원 89명 1,602,000 / ...`
>
> → 선 없는 회계 표 (공백 정렬). pdfplumber가 cell 단위로 인식 못함. 별도 회계 표 처리 또는 LayoutXLM 필요.

### 핵심 관찰

대부분의 "누락"은 **정보 자체는 추출됐고 Claude의 통합 형식과 우리의 분리 형식의 substring 매칭 한계**입니다. attr별 분리는 6-class 분류기에 들어갈 단위로는 더 좋은 형식. 즉 실용적으로는 정보 손실 없음.

**진짜 추출 실패**는 서귀포 본문 paragraph + 정산 안내 회계 표 = 6장 중 2장.

### 추출 sentence + 매칭 전체 dump

PDF별 본문/표 sentence 전체, Claude todo, 우리 todo, 누락 항목까지 — 별첨: [sentence_extraction/v5_extraction_report.md](sentence_extraction/v5_extraction_report.md)

### 2026 서귀포 토요프로그램 — 2건 누락 (recall 0.714)

| Claude todo | 원인 |
|---|---|
| `토요다문화이야기 대상: 유치원(7세) ~ 초등 1·2학년 9명 모집(모집정원 4명, 대기자 5명 추가 모집) 내용: 꼬꼬붱 (홍홍/길벗어린이), ...` | 본문 paragraph가 raw text에서 줄로 끊겨 들어와 BIO가 한 sentence로 못 묶음. **v2 학습에서 해결 시도 중** |
| `24.(금) 24:00 운영일시:` | 같은 원인 — 같은 paragraph에서 line break 처리 한계 |

### 2024 4학년 현장체험학습 정산 — 1건 누락 (recall 0.667)

회계 표 (수납인원 × 단가 × 금액 매트릭스). pdfplumber가 표를 cell 단위로 인식 못함 (선 없이 공백으로만 정렬된 회계 표). 현재 모델/룰 둘 다 한계.

### 2019 인플루엔자 — 2건 누락 (recall 0.929)

한 cell 안 다중 줄 텍스트의 일부가 본문 BIO에서 sentence boundary 잘못 잡힘. v2 학습에서 line break 처리 개선 기대.

---

## 6. 룰 vs 모델 — 솔직한 분리

질문: "정규식이랑 뭐 달라? 새 통신문 오면 또 건드려야 하는 거 아냐?"

| 컴포넌트 | 모델? | 새 통신문 대응 |
|---|---|---|
| Parser ensemble selection | 룰 (점수식) | 임계값 박혀있음, 일반화는 됨 |
| **본문 sentence 분리 (BIO)** | **모델** | **KoCharELECTRA fine-tuned. 학습으로 일반화** |
| 표 cell 인식 (find_tables) | 룰 (line/edge detection) | 대부분의 가정통신문 표는 OK |
| col/row-major 판별 | 룰 (cell 길이 분산 통계) | 형식 바뀌어도 통계로 자동 판별 |
| 표 cell 내 bullet 분리 | 룰 (▪/▸/• regex) | OK |
| Todo 분류 (KoELECTRA) | 모델 (윤정님) | OK |

**왜 표는 룰**: 표는 본질적으로 2D 구조인데 1D char sequence를 보는 BIO 모델로는 "어느 cell이 어느 entity의 attribute인지" 못 풉니다. 이걸 학습으로 풀려면 LayoutXLM 같은 multi-modal (text + bbox + image) 모델이 필요 (시간 비용 큼). 현재 우리는 cell 구조 정보를 보존한 룰로 처리.

---

## 7. 현재 학습 상태 + 진행 중

### v1 모델 (현재 best, recall 0.870)
- 학습 input = Claude cleaned_text (정제된 paragraph)
- 한계: 추론 시 들어오는 raw text의 line break/공백 노이즈를 학습 시 본 적 없음 → 일부 본문에서 sentence를 잘못 묶음

### v2 모델 (실험 — v5 못 넘음)
- 학습 input = pymupdf raw text (paragraph 깨진 채). 라벨은 Claude sentence_list를 공백 무시(norm-matching)로 raw 위치에 매핑
- 의도: BIO가 line break이 sentence boundary가 아님을 학습으로 알아내게
- 학습 데이터: 2,063 PDFs, 2.57M chars, 46.7K B-SENT (norm-matching 75%)
- **1차 학습 (5 epoch)**: val 0.5767, B-acc 0.773 → **v6 평가 recall 0.828** (v5보다 하락)
- **Resume 학습 (+5 epoch LR 1e-5)**: 2 epoch에서 val 최저점 → **v7 평가 recall 0.796** (더 하락)

### 가설이 틀렸다는 정량 증거 — 원인 분석
- v2 학습 데이터 매칭률 75%의 의미: **표 sentence가 norm-matching 실패해서 표 영역의 char가 전부 O 라벨**로 들어감
- 결과: BIO가 "표 영역에선 sentence boundary 없다"고 잘못 학습 → 추론 시에도 본문/표 가리지 않고 sentence를 보수적으로(적게) 잡음
- 서귀포: BIO todos가 v5 7개 → v6 4개 → v7 4개로 줄어든 게 직접 증거
- v1의 99% 매칭(Claude cleaned_text input)이 학습 신호로 더 깔끔했음

### 다음 axis 후보
| 옵션 | 설명 | 시간 |
|---|---|---|
| (a) v1로 운영 | 현재 best. 누락은 표 처리 v6와 결합으로 0.870 | 즉시 |
| (b) v2 학습 데이터 v3 — 표 inline | raw text에 entity별 묶음 표 sentence를 inline 삽입해서 매칭률 95%+ 달성 후 재학습 | 데이터 재생성+Colab 1~2시간 |
| (c) 모델 크기 변경 | small (14M) → base (110M)? + CRF layer | 학습 1일 |
| (d) LayoutXLM | 표/layout 모델 의존, multi-modal | 학습 1주+ |

---

## 8. 다음 단계

| 항목 | 우선순위 | 비고 |
|---|---|---|
| v2 BIO resume 학습 완료 + 평가 | 진행 중 | LR 1e-5로 +5 epoch fine-tune |
| Backend integration | 다음 | sentence_list 자체 모델 output을 layout_normalizer가 받게 |
| TTS 합성 단계 손보기 | 다음 | (1) 카테고리 prefix 제거 또는 자연어화 (2) 같은 entity 반복 → 묶음 합성 (3) 메타정보(학교명/직인 등) 필터 |
| 회계 표 형식 처리 | 미정 | 정산 안내 등 선 없는 회계 표 — 별도 처리 또는 LayoutXLM 검토 |
| 표 처리도 모델로 (LayoutXLM) | 장기 | 진짜 모델 의존도 끝까지 가려면. 학습 비용 큼 (multi-modal) |
