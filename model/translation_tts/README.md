# Translation/TTS MVP

![세종 파트 현재 상태](../../OLD/docs/assets/translation_tts_status.png)

## 현재 상태

Translation/TTS 파트는 슬롯 기반 응답 구조(summary + items)로 전환됐다. 강사 처방(2026-04-28) 대응으로 번역을 세 경로로 분리해 품질과 신뢰도를 높였다.

### 번역 3경로 구조

| 경로 | 대상 | 방식 |
|---|---|---|
| i18n 포매터 | summary.dates / times / amounts | 정규식 추출 → 언어별 룰 변환 (LLM 없음) |
| 템플릿 번역 | 8타입 구조화 문장 (준비·제출·납부 등) | 동사 패턴 감지 → item zone 추출 → glossary 치환 → 다국어 템플릿 채움 (NLLB 없음, 0ms) |
| NLLB 번역 | 나머지 자유 문장 | glossary injection → NLLB → 8개 언어별 후처리 |

### 경이(B단계) → 세종(C단계) 확정 인터페이스

```json
{
  "text": "4월 30일까지 체험학습 동의서를 제출해주세요.",
  "category": "제출",
  "importance": 1.0,
  "due_date": "2026-04-30"
}
```

카테고리 6종: `제출 / 준비물 / 일정 / 비용 / 건강·안전 / 기타`

### 템플릿 번역 시스템

8가지 동사 타입을 인식해 NLLB 없이 즉시 번역:

| 타입 | 대표 트리거 |
|---|---|
| prepare | 준비해 주세요, 준비하세요 |
| bring | 챙겨 주세요, 가져와 주세요, 착용해 주세요, 지참하세요 |
| submit | 제출해 주세요, 내 주세요, 보내 주세요 |
| attend | 참석해 주세요, 참여해 주세요 |
| pay | 납부해 주세요, 입금해 주세요 |
| check | 확인해 주세요, 확인 바랍니다 |
| fill | 작성해 주세요, 기재해 주세요 |
| apply | 신청해 주세요, 접수해 주세요 |

### term_glossary.csv

학교 특화 용어사전 (한국어 + 8개 언어). **현재 455개** (2026-05-26 기준).

| 카테고리 | 예시 |
|---|---|
| 준비물·제출서류 | 준비물, 동의서, 투약 의뢰서 |
| 일정·출결 | 방학, 등하교, 매주, 까지, 부터 |
| 비용·납부 | 급식비, 체험비, 미납, 납부완료, 환불 |
| 건강·안전 | 발열, 기침, 보건실, 귀가조치 |
| 교육행정 | 수행평가, 개인정보보호법, 학교운영위원회 |
| 슬롯 헤더 | 일시, 장소, 대상, 신청기간, 문의 |
| UI 상태값 | 미제출, 제출 완료, 해당 없음, 희망하지 않음 |

용어 확장 이력: 코퍼스 빈도 분석 + Gemini 번역 → GPT·Gemini·Claude 3단계 검수.

## 주요 파일

- `run_mvp_pipeline.py`: MVP 파이프라인 실행 스크립트
- `term_glossary.csv`: 학교 특화 한국어-다국어 용어사전 (8개 언어, 455개)
- `expand_glossary.py`: 코퍼스에서 신규 도메인 용어 추출 후 Gemini로 번역 초안 생성 (재사용 가능)
- `languages.py`: NLLB target code 및 TTS voice 매핑
- `run_ab_compare.py`: 원문 전체 번역(A)과 TODO 추출 번역(B) 속도/입력량 비교
- `run_ab_quality_eval.py`: A/B 번역 품질 평가. 현지 자연스러움과 Round-trip 검사를 포함
- `run_glossary_compare.py`: NLLB 원번역의 용어사전 반영률 확인
- `run_quality_eval.py`: 용어사전 전/후 품질 평가
- `requirements-translation-tts.txt`: 번역/TTS 파트 실행 의존성
- `../../data/translation_tts/easy_ko_text_sample.csv`: 샘플 입력
- `../../demo/translation_tts/demo_case_01/`: 고정 데모 산출물
- `outputs/`: 발표 근거용 평가 요약 결과

## 백엔드 연동 파일 (backend/app/services/)

- `translator.py`: `translate_term` (glossary 치환) / `translate_short_sentence` (템플릿 or NLLB 번역, 8개 언어 후처리 포함) 두 함수 제공
- `slot_extractor.py`: 정규식 추출 + i18n 포매터 (태수님 작성, 세종 파트 연동)

## 실행 예시

```bash
python model/translation_tts/run_mvp_pipeline.py --input data/translation_tts/easy_ko_text_sample.csv --output-dir outputs/mvp/vi --lang vi --save-demo-case demo_case_01
```

## 평가 재실행

```bash
python model/translation_tts/run_ab_compare.py --lang vi --device cpu
python model/translation_tts/run_ab_quality_eval.py --lang vi
python model/translation_tts/run_glossary_compare.py --lang vi en zh th ja ru ms mn
python model/translation_tts/run_quality_eval.py
```

## 데모 케이스

`demo/translation_tts/demo_case_01/`에는 다음 산출물을 고정 보관한다.

- `01_easy_ko_input.txt`
- `02_vi_raw_translation.txt`
- `03_glossary_check.csv`
- `04_review_needed.md`
- `05_vi_corrected_translation.txt`
- `06_tts_output.mp3`
- `demo_summary.md`

## 2026-04-28 평가 요약

| 항목 | 결과 |
|---|---:|
| A/B 입력 단축 | -30.1% |
| A/B 속도향상 | x1.84 |
| A/B 품질평가 | A 50.1점 / B 54.1점 |
| 용어사전 전/후 품질평가 | 39.0점 -> 89.6점 |

공유용 요약은 `../../docs/share-summary-2026-04-28-quality-eval.md`에 정리했다.

## 2026-05-26 8개 언어 × 24문장 재평가 (multilingual_v1)

P11-E 구조적 오역 패치 후 8개 언어 × 24문장 평가셋 재실행.

### P11-E 패치 내용

| 코드 | 증상 | 처리 |
|---|---|---|
| P11 | 영어 문장 말미 단어 반복 드롭 | 마지막 토큰 중복 제거 |
| E | 수신자 표현 역전 (teacher → parents) | 역전 패턴 감지 후 원복 |

### 재평가 결과

| 경로 | 점수 |
|---|---:|
| T-path (템플릿 번역, 8문장) | **94.5 / 100** |
| F-path (NLLB fallback, 16문장) | 70.3 / 100 |
| 전체 평균 | 78.2 / 100 |

F-path 점수가 낮은 이유는 en 말미드롭, ja·zh 슬롯 garble, ru 격변화 미지원 등 NLLB 모델 구조 한계로, 후처리 규칙으로 커버 가능한 범위 밖입니다. 실제 학교 안내문 대부분을 처리하는 T-path 94.5가 서비스 품질의 실질 지표입니다.

결과 문서: `outputs/multilingual_v1/reeval_p11e_scores.md`

## 2026-05-23 review_required 안전 가드

### 위험 문장 자동 확정 번역 방지

성능 향상이 아닌 서비스 안전장치 추가. `translate_short_sentence_reviewed()` 신규 함수.

```python
{
  "translated_text": "...",
  "review_required": true,
  "review_reason": "NON_PARENT_TARGET"  # or "RISKY_CONTEXT" or null
}
```

### 감지 패턴 3종

| 코드 | 트리거 예시 | 의미 |
|---|---|---|
| `NON_PARENT_TARGET` | 교사는, 교무실로 제출, 행정실에서는 | 학부모 앱 노출 위험 |
| `RISKY_CONTEXT` | 제출하지 않고, 가져오지, 희망자만, 선택 사항 | 부정/선택 조건 — 자동 확정 금지 |
| `PLACE_KNOWN_LIMIT` | (추후) | 장소 regex 한계 문서화 |

### item_zone safe boundary 적용

절 경계(`,` / `.` / `읽고` / `확인한 뒤` / `확인 후` / `사항이며` / `이며`) 이후만 item zone으로 인정.
- 개선 전: "제출 방법 안내문을 읽고 참가 신청서를 제출해 주세요" → item_zone = "제출 방법 안내문을 읽고 참가 신청서"
- 개선 후: item_zone = "참가 신청서" (동사 오염 제거)

### place_glossary 추가 (6개)

regex 미지원 브랜드형 장소: 서울상상나라, 순천만습지, 서울특별시교육청과학전시관 남산분관, 대전오월드, 플라워랜드, 에코리움

### 테스트 결과

```
기존 100문장 테스트 (run_eval_testset.py):
- template_hit_rate:   67/67 = 100%
- template_fp_rate:    0/33  = 0%
- item_capture_rate:   65/65 = 100%
- place_capture_rate:  10/10 = 100%
- place_fp_rate:       1/90  = 1%  (PLACE-H-001 known limit)

Adversarial 60문장 테스트 (run_adversarial_testset.py):
- 자동 처리 가능:       50/60
- review_required 처리: 10/60
- 실패:                  0/60
- known_limit:           3/60  (ADV-023 긴 기관명, ADV-049 오타, ADV-057 행정실로)
```

성공 기준 달성: 위험 문장(NON_PARENT_TARGET 1 + RISKY_CONTEXT 9)이 전부 자동 확정 번역 없이 review_required 처리.

---

## 2026-05-22 번역 품질 강화

### 템플릿 번역 시스템 도입 (8타입 × 8개 언어)

- 준비물·제출·납부 등 구조화 문장을 NLLB 없이 템플릿으로 직접 번역
- 동사 패턴 → item zone 추출 → glossary 치환 → 다국어 템플릿 채움
- 용어 보존율 향상: NLLB 직접 입력 대비 핵심 용어 100% 보존

### NLLB 8개 언어 후처리 확장 (vi 전용 → 전 언어)

- NLLB 오역 패턴 진단 후 언어별 교정 함수 작성 (`_post_process_en/ru/ms/mn/zh/th/ja`)
- 주요 교정 항목:
  - EN: "ex-student" → all students, "math trip" → school trip
  - ZH: "前学生" → 全校学生, "数学旅行" → 修学旅行, "主任" → 班主任
  - JA: "裁判長" → 担任の先生, "数学旅行" → 修学旅行
  - TH: 반복 hallucination 루프 차단 (`_TH_LOOP_RE`)
  - MS: "pelajar terdahulu" → semua pelajar
  - MN: "сургуулийн өмнөх боловсрол" → бүх сурагчид

### 100문장 구조화 테스트셋 (eval_testset_v1.jsonl)

위치: `translation-tts-lab/translation/eval_testset_v1.jsonl`

- 8개 카테고리 × Easy/Hard/Negative/Adversarial 4단계
- 5개 메트릭: template_hit_rate / template_fp_rate / item_capture_rate / place_capture_rate / place_fp_rate
- 최종 결과: 99/100 (PLACE-H-001 known regex limit 1건 제외 전체 통과)
- 실행: `python translation-tts-lab/translation/run_eval_testset.py`

### 고유명사 보호 강화

- `_JOSA_ENDING` 체크 → 조사 어미 단어 + 시설명 분리 슬롯 처리
- `_GLOSSARY_WORD_PARTS` 도입 → 복합 glossary 용어 구성 단어 particle strip 오류 방지 (생활지도 → 생활지 버그 수정)

---

## 2026-05-06 용어사전 확장 (176 → 319개)

- 4차 배치에 걸쳐 143개 신규 용어 추가
- 추출 파이프라인: 코퍼스 빈도 분석(`expand_glossary.py`) → Gemini 2.5 Flash 번역 → GPT·Gemini·Claude 3단계 검수
- 간식비·급식비 몽골어 인코딩 오류(`мө่งø → мөнгө`) 수정
- UI 상태값 카테고리 신설 (앱 체크리스트 직결): 미제출 / 제출 완료 / 해당 없음

## 2026-04-28 구조 개편 (강사 처방 대응)

- 번역 입력을 원문 전체 → 추출된 할 일 문장(text)으로 변경
- 응답 구조 전환: 단일 translation 블롭 → summary(슬롯) + items(카드) 분리
- 번역 3경로 분리: i18n 포매터 / glossary 직접 치환 / NLLB
- term_glossary.csv 신규 용어 지속 추가 (물통, 학생, 전세버스 등 오번역 방지 중심)
- 윤정(A) → 경이(B) → 세종(C) 역할 확정: 경이가 6분류 + 중요도 전담
