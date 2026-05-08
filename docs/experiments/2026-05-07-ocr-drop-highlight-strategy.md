# OCR Drop and Highlight Strategy

날짜: 2026-05-07  
담당: 세종 파트  
상태: 전략 정리

---

## 결론

OCR을 메인 파이프라인으로 사용하는 전략은 드랍한다.

다만 하이라이트 UX 자체는 버리지 않는다. OCR bbox 기반이 아니라, 문서 유형별로 가능한 좌표 소스를 분리해 살린다.

```text
OCR main pipeline: drop
Highlight UX: keep as PDF text-layer / original-text comparison feature
```

---

## 왜 OCR을 드랍하는가

실기기 촬영과 실제 PDF 테스트에서 다음 문제가 확인되었다.

- ML Kit/Tesseract OCR 인식률이 실제 가정통신문에서 불안정하다.
- OCR 오인식이 모델 A/B, 카드 빌더, NLLB 번역까지 연쇄 전파된다.
- OpenCV 전처리나 OCR 후처리를 계속 붙여도 모든 양식과 촬영 조건을 커버하기 어렵다.
- Gemini Vision을 도입하는 순간 "완전 오프라인 처리"라는 OCR 메인 전략의 장점도 약해진다.
- 남은 일정에서 OCR 품질 개선에 계속 매달리면 서비스 핵심 품질인 정보 보존과 UX 개선이 밀린다.

따라서 OCR은 "문서 이해의 메인 엔진"이 아니라 fallback / 비교 실험 / 개인 연구 기록으로 남긴다.

---

## 보존할 OCR 연구 기록

OCR 실험은 실패 기록이 아니라 의사결정 근거로 보존한다.

관련 기록:

- `docs/experiments/2026-05-01-ocr-mlkit-korean-results.md`
- `docs/worklog-2026-05-06-ocr-pivot-bbox.md`
- `docs/worklog-2026-05-07-android-ocr-smoke.md`
- `docs/worklog-2026-05-07-ocr-slot-correction.md`
- `docs/experiments/2026-05-07-ocr-slot-correction-eval.md`

이 기록들은 다음 내용을 증명한다.

- OCR 엔진을 비교했고, ML Kit Korean을 선택한 근거가 있다.
- 실기기 OCR 플로우를 구현하고 앱 크래시를 복구했다.
- bbox 기반 하이라이트 PoC 방향을 검토했다.
- MNIST에서 착안한 confusable character slot correction 아이디어를 실험했다.
- 합성 OCR slot 샘플에서는 raw exact 1/7에서 corrected 7/7까지 개선했다.

즉, OCR을 드랍하는 것은 시도 부족이 아니라 실험 후 내린 범위 조정이다.

---

## 새 메인 파이프라인

```text
PDF / 이미지 / HWP
  ↓
입력 유형 분기

PDF:
  Gemini Vision → sentence_list
  + 필요 시 pdfplumber text-layer bbox → sentence-bbox 매칭

이미지 / 사진:
  Gemini Vision → sentence_list
  bbox overlay는 보류
  카드 + 원문 대조 영역 highlight로 대체

HWP / HWPX:
  PDF 변환
  → PDF와 동일 처리

  ↓
slot preservation
  날짜 / 시간 / 금액 / URL / 전화 / 대상 / 준비물 보호
  신청기간 / 운영일시 / 결과발표 / 문의 role 분리
  날짜·시간 fragment NLLB skip

  ↓
윤정 KoELECTRA / 경이 KcELECTRA
  todo / category 분류

  ↓
NLLB + vi template + glossary
  핵심 용어와 slot은 보호하고, 설명 문장만 번역

  ↓
card_builder
  해야 할 일
  꼭 확인할 정보

  ↓
Android UI
  카드 / TTS / 원문 대조 / PDF highlight 후보
```

---

## 하이라이트를 살리는 방법

하이라이트 UX는 다음처럼 문서 유형별로 분리한다.

| 입력 유형 | 하이라이트 방식 | 판단 |
| --- | --- | --- |
| 디지털 PDF | pdfplumber text-layer bbox + sentence_list 매칭 | 유지 가능 |
| HWP/HWPX | PDF 변환 후 PDF 방식 적용 | 유지 가능 |
| 이미지/사진 | bbox overlay 보류, 원문 대조 텍스트 highlight | 현실적 대체 |
| 스캔 PDF | Gemini Vision sentence_list 우선, bbox는 후속 | 보류 |

핵심은 다음과 같다.

```text
OCR bbox highlight는 드랍
PDF text-layer bbox highlight는 PoC 후보로 유지
이미지/사진은 카드 + 원문 대조 highlight로 대체
```

---

## 역할 분리

Gemini Vision을 쓰더라도 전체를 API에 맡기는 구조는 아니다.

| 레이어 | 역할 |
| --- | --- |
| Gemini Vision | 문서 이미지/PDF를 원문 기반 sentence_list로 구조화 |
| sentence_list contract | 후속 파이프라인이 흔들리지 않도록 중간 산출물 고정 |
| slot preservation | 날짜, 시간, 금액, URL, 전화, 대상 등 사실값 보호 |
| KoELECTRA/KcELECTRA | todo 여부와 카테고리 판단 |
| NLLB/template/glossary | 다국어 번역 안정화, 특히 VI 우선 품질 보정 |
| card_builder/UI | 해야 할 일과 꼭 확인할 정보를 분리 표시 |

한 줄로 정리하면:

```text
Gemini는 문서 뼈대를 만들고, SchoolBridge는 핵심 정보를 보호하고 행동 카드로 바꾼다.
```

---

## 팀 공유 문장

OCR 메인 전략은 정확도와 일정 리스크가 커서 드랍합니다. 대신 하이라이트 UX는 완전히 버리지 않고, 디지털 PDF/HWP→PDF에서는 pdfplumber text-layer bbox를 이용해 sentence_list와 매칭하는 방향으로 살립니다.

이미지/사진 입력은 Gemini Vision으로 sentence_list를 얻고, bbox overlay는 욕심내지 않습니다. 대신 카드와 원문 대조 영역에서 텍스트 highlight를 제공하는 방향이 현실적입니다.

기존 OCR 실험 문서는 실패가 아니라, OCR 메인 전략을 드랍하게 된 근거와 개인 연구 기록으로 보존합니다.

---

## 다음 작업

1. Gemini Vision sentence_list 호출부 연결
2. sentence_list → slot preservation → info_cards 흐름 강화
3. 신청기간 / 운영일시 / URL / 문의 / 대상 role 분리 검증
4. PDF text-layer bbox와 sentence_list 매칭 PoC 별도 검토
5. OCR 관련 기능은 fallback 또는 연구 기록으로 문서상 분리

