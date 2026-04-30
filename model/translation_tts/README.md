# Translation/TTS MVP

![세종 파트 현재 상태](../../docs/assets/translation_tts_status.png)

## 현재 상태

Translation/TTS 파트는 슬롯 기반 응답 구조(summary + items)로 전환됐다. 강사 처방(2026-04-28) 대응으로 번역을 세 경로로 분리해 품질과 신뢰도를 높였다.

### 번역 3경로 구조

| 경로 | 대상 | 방식 |
|---|---|---|
| i18n 포매터 | summary.dates / times / amounts | 정규식 추출 → 언어별 룰 변환 (LLM 없음) |
| glossary 치환 | summary.places / supplies / deadlines | term_glossary.csv exact 매칭, miss 시 한국어 노출 |
| NLLB 번역 | items[].title_translated | glossary injection → NLLB → vi 후처리 |

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

### term_glossary.csv

학교 특화 용어사전 (8개 언어). 최신 용어 수는 CSV 직접 참고.
주요 추가 이력: 학생/전세버스/생존수영/리코더/물통 등 오번역 방지 용어 중심으로 지속 확장 중.

## 주요 파일

- `run_mvp_pipeline.py`: MVP 파이프라인 실행 스크립트
- `term_glossary.csv`: 학교 특화 한국어-다국어 용어사전 (8개 언어, 최신 용어 수는 CSV 직접 참고)
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

- `translator.py`: `translate_term` (glossary 치환) / `translate_short_sentence` (NLLB 번역) 두 함수 제공
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

## 2026-04-28 구조 개편 (강사 처방 대응)

- 번역 입력을 원문 전체 → 추출된 할 일 문장(text)으로 변경
- 응답 구조 전환: 단일 translation 블롭 → summary(슬롯) + items(카드) 분리
- 번역 3경로 분리: i18n 포매터 / glossary 직접 치환 / NLLB
- term_glossary.csv 신규 용어 지속 추가 (물통, 학생, 전세버스 등 오번역 방지 중심)
- 윤정(A) → 경이(B) → 세종(C) 역할 확정: 경이가 6분류 + 중요도 전담
