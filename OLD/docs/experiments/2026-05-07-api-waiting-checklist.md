# API Waiting Checklist

날짜: 2026-05-07  
담당: 세종 파트  
목적: Gemini Vision API 연결 전까지 팀 레포에서 정리할 범위 고정

---

## 현재 결정

```text
OCR main: drop
Gemini Vision: sentence_list 생성기
SchoolBridge 자체 레이어: slot preservation / A-B models / NLLB template / card UI
```

Gemini가 붙기 전까지는 Gemini 호출부를 직접 구현하지 않고, 다음 계약과 후속 레이어를 정리한다.

---

## API 연결 전 할 일

### 1. sentence_list 계약 유지

`backend/app/services/sentence_skeleton.py`

- `SentenceListDocument`
- `SentenceListItem`
- `role_hint`
- `contains_slots`
- `source_order`
- `raw_text_to_sentence_list()` fallback

Gemini API가 붙으면 이 JSON 계약만 맞추면 된다.

### 2. info_cards 흐름 유지

`backend/app/services/info_card_builder.py`

- `target`
- `application_period`
- `event_datetime`
- `application_url`
- `contact`
- `location`
- `fee`
- `supplies`

`/notice/analyze/{id}` 응답에는 기존 `cards`와 별도로 `info_cards`를 내려준다.

```json
{
  "cards": [],
  "info_cards": []
}
```

### 3. 번역 보호 정책 유지

다음 값은 NLLB 자유 번역 대상이 아니다.

- 날짜
- 시간
- 금액
- URL
- 전화번호
- 대상
- 준비물/제출물 glossary 확정 용어

짧은 날짜/시간 fragment는 번역하지 않고 원문 또는 언어별 포맷으로 보존한다.

### 4. OCR 기록 분리

OCR 메인 전략은 드랍하되, 연구 기록은 삭제하지 않는다.

팀 레포:

- `OLD/docs/experiments/2026-05-07-ocr-drop-highlight-strategy.md`

개인 레포:

- `translation-tts-lab/docs/ocr-research/`
- `translation-tts-lab/archive/ocr-research/`

---

## API 연결 후 할 일

1. Gemini Vision 호출부에서 문서/PDF/이미지를 sentence_list JSON으로 변환
2. JSON을 `parse_sentence_list_payload()`로 검증
3. `info_card_builder`에 연결
4. 기존 KoELECTRA/KcELECTRA 모델 입력은 sentence_list 기반으로 정리
5. NLLB/template/glossary 번역은 slot 보호 이후에만 수행
6. 서귀포 PDF와 백제권 PDF로 회귀 테스트

---

## 테스트 기준

API 연결 후 최소 통과 기준:

```text
1. 신청기간과 운영일시가 분리된다.
2. 대상이 "대 상" 공백 문제 없이 target으로 잡힌다.
3. URL과 문의 전화번호가 NLLB로 번역되지 않는다.
4. 날짜/시간 fragment가 "Tôi không biết" 같은 문장으로 번역되지 않는다.
5. 기존 cards와 info_cards가 분리되어 내려간다.
```

---

## 팀 공유 한 줄

Gemini API가 들어오기 전까지는 호출부를 억지로 만들지 않고, sentence_list 계약과 slot/info_cards 안전망을 먼저 고정한다.
