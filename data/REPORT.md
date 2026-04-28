# 데이터셋 리포트

> 자동 생성 — `python scripts/validate_data.py` 재실행 시 갱신됨.  
> 강사 피드백(2026-04-28) 대응: *"데이터를 잘 이해하고 커스텀하는 게 근본 핵심."*

## 1. notices_labeled_v2 (모델 학습/검증용)

### `notices_labeled_v2.jsonl`

- **총 행 수**: 147건
- **고유 가정통신문 ID**: 19개 (`notice_id` 기준)
- **`original_id` 결측**: 23건 (N16~N19 알림장 4건 — 27장 원문 외 자료)

**`is_todo` 분포** (할 일 vs 정보성 문장)

| 라벨 | 건수 |
| --- | --- |
| True | 102 |
| False | 45 |

**카테고리 분포** (is_todo=True 행만)

| 카테고리 | 건수 | 비율 |
| --- | --- | --- |
| 건강·안전 | 35 | 34.3% |
| 준비물 | 22 | 21.6% |
| 제출 | 18 | 17.6% |
| 일정 | 18 | 17.6% |
| 기타 | 7 | 6.9% |
| 비용 | 2 | 2.0% |

⚠️ **클래스 불균형**: 최다 35 : 최소 2 = 17.5:1 → 클래스 가중치(`balanced`) 적용 권장

**문장 길이 (문자 수)**

- min/median/mean/max: 7/43/45.6/139
- stdev: 22.7

## 2. notices_original2 (원문 가정통신문)

### `notices_original2.jsonl` (원문 데이터)

- **총 가정통신문**: 27장
- **카테고리 채워진 행**: 27/27건

**출처(`source_type`) 분포**

| 출처 | 건수 |
| --- | --- |
| 초등학교 | 19 |
| 유치원 | 8 |

**원문 길이 (문자)**: min/median/mean/max = 373/979/961.4/1664, stdev 374.0

## 3. term_glossary (학교 용어사전)

### `term_glossary.csv` (학교 도메인 용어사전)

- **총 용어 수**: 144개 한국어 키워드

**언어별 채워진 셀 수**

| 언어 컬럼 | 채워진 행 | 누락 |
| --- | --- | --- |
| preferred_vi | 144 | 0 |
| preferred_en | 144 | 0 |
| preferred_zh | 144 | 0 |
| preferred_th | 144 | 0 |
| preferred_ms | 144 | 0 |
| preferred_mn | 144 | 0 |
| preferred_ru | 144 | 0 |
| preferred_ja | 144 | 0 |

## 4. 구버전 데이터

### 구버전 / 기타

- `data\labeled\notice_sample_v1.csv` — 30건
- `data\labeled\notice_sample_v2.csv` — 200건
- `data\labeled\notice_sample_v3.csv` — 200건

---

## 검증 인사이트

- **클래스 불균형 여전** — '기타' 카테고리가 검증셋에 1건만 있어 F1 신뢰도 낮음. 데이터 추가 필요.
- **`original_id` 결측 4건(N16~N19 알림장)** — 27장 원문 외 자료. 추가 원문 확보 시 매핑 가능.
- **사전 144 용어 × 8개 언어 풀 셀** — 누락 없음 (Gemini 자동 채움 + GPT 교차검증).
- **새 데이터 추가 시 본 스크립트 재실행** → 통계 변화 추적.
