# Gemini Sentence List Contract

날짜: 2026-05-07  
담당: 세종 파트  
목적: Gemini를 최종 요약/번역기가 아니라, 후속 파이프라인용 `sentence_list` 생성기로 사용하기 위한 중간 산출물 계약 정의

---

## 배경

강사님 피드백 이후 확인된 핵심 문제는 모델 A/B 자체만의 문제가 아니라, 모델 A/B에 들어가기 전에 문서 구조와 핵심 정보가 흐트러지는 것이었다.

실제 실패 예:

```text
대 상: 초등학생 3·4학년
→ header로 잡히지 않고 NLLB에서 "상금"으로 오역

23.(토) / 13:00 ~ 15:00
→ 날짜/시간 fragment가 일반 문장처럼 NLLB에 들어가 "Tôi không biết" 출력

신청기간 + 운영일시
→ 같은 "일시" 카드에 섞임
```

따라서 Gemini를 사용하더라도 최종 답을 받는 것이 아니라, 기존 Ollama normalizer 자리를 대체해 **원문 보존형 sentence list**를 받는 방향으로 정리한다.

---

## 전체 흐름

```text
PDF/HWP/이미지
  ↓
parser (HWP/PDF/OCR)
  ↓
Gemini API
  - 요약/번역 금지
  - 원문 기반 sentence list 생성
  - section / role_hint 부여
  ↓
세종 slot preservation
  - 날짜/시간/금액/URL/전화/대상/준비물 보호
  - 신청기간/운영일시/결과발표/문의 role 분리
  - 날짜/시간 fragment NLLB skip
  ↓
윤정 KoELECTRA todo 추출
경이 KcELECTRA category 분류
  ↓
NLLB + vi template + glossary
  ↓
card_builder
  - 해야 할 일
  - 꼭 확인할 정보
  ↓
Android UI / TTS / 시각화
```

---

## 출력 계약

Gemini 출력은 반드시 JSON만 사용한다.

```json
{
  "document_title": "2026년 5월 서귀포외국문화학습관 토요프로그램 추가모집 안내",
  "sentence_list": [
    {
      "sentence_id": "s001",
      "text": "① 토요영어체험교실",
      "section": "토요영어체험교실",
      "section_type": "program",
      "role_hint": "program_title",
      "is_action_candidate": false,
      "contains_slots": [],
      "source_order": 1
    },
    {
      "sentence_id": "s002",
      "text": "대상: 초등학생 3·4학년 8명 모집(모집정원 3명, 대기자 5명 추가 모집)",
      "section": "토요영어체험교실",
      "section_type": "program",
      "role_hint": "target",
      "is_action_candidate": false,
      "contains_slots": ["target"],
      "source_order": 2
    },
    {
      "sentence_id": "s003",
      "text": "신청기간: 2026. 4. 21.(화) 10:00 ~ 4. 24.(금) 24:00",
      "section": "토요영어체험교실",
      "section_type": "program",
      "role_hint": "application_period",
      "is_action_candidate": true,
      "contains_slots": ["date", "time"],
      "source_order": 3
    },
    {
      "sentence_id": "s004",
      "text": "운영일시: 2026. 5. 9.(토) 10:00 ~ 12:00",
      "section": "토요영어체험교실",
      "section_type": "program",
      "role_hint": "event_datetime",
      "is_action_candidate": false,
      "contains_slots": ["date", "time"],
      "source_order": 4
    },
    {
      "sentence_id": "s005",
      "text": "신청 URL: https://org.jje.go.kr/jiei/index.jje",
      "section": "신청 및 운영안내",
      "section_type": "application_info",
      "role_hint": "application_url",
      "is_action_candidate": true,
      "contains_slots": ["url"],
      "source_order": 5
    },
    {
      "sentence_id": "s006",
      "text": "문의: 064-767-9811~5",
      "section": "문의",
      "section_type": "contact",
      "role_hint": "contact",
      "is_action_candidate": false,
      "contains_slots": ["phone"],
      "source_order": 6
    }
  ]
}
```

---

## 필드 정의

| 필드 | 의미 |
| --- | --- |
| `document_title` | 문서 제목 |
| `sentence_id` | 후속 처리용 고유 ID |
| `text` | 원문 기반 문장 또는 필드. 요약/의역 금지 |
| `section` | 프로그램명 또는 섹션명 |
| `section_type` | `program`, `application_info`, `contact`, `notice`, `footer`, `unknown` |
| `role_hint` | `target`, `application_period`, `event_datetime`, `application_url`, `contact` 등 |
| `is_action_candidate` | 모델 A가 todo로 볼 후보인지 |
| `contains_slots` | `date`, `time`, `url`, `phone`, `amount`, `target`, `location` 등 |
| `source_order` | 원문 순서 |

---

## Gemini 프롬프트 규칙

```text
너는 가정통신문 문서를 후속 AI 파이프라인이 처리하기 좋게 구조화하는 parser다.
요약가나 번역가가 아니다.

목표:
문서를 예쁘게 요약하지 말고, 원문 정보를 최대한 보존한 sentence list를 생성한다.

중요 규칙:
- 날짜, 시간, 금액, URL, 전화번호는 원문 그대로 보존한다.
- 신청기간과 운영일시는 반드시 구분한다.
- 프로그램이 여러 개 있으면 section으로 분리한다.
- 원문에 없는 정보는 추측하지 않는다.
- 번역하지 않는다.
- JSON만 출력한다.
```

---

## 코드 위치

```text
backend/app/services/sentence_skeleton.py
backend/app/services/info_card_builder.py
```

포함 기능:

```text
- SentenceListItem / SentenceListDocument 계약 모델
- Gemini prompt template
- header normalize
- role_hint fallback inference
- raw_text_to_sentence_list fallback adapter
- sentence_list → "꼭 확인할 정보" SlotCard 생성
```

`info_card_builder.py`는 기본적으로 value를 NLLB에 보내지 않는다. 이 레이어의 1차 책임은 날짜/시간/URL/전화/대상 같은 사실값 보존이며, 번역은 `translate_values=True` 옵션을 켰을 때만 수행한다.

스모크 결과:

```text
대 상 → 대상 / target
수강신청 2026.4.21~4.24 → 신청기간
운영일시 2026.5.9 10:00~12:00 → 운영일시
문의 → 문의
신청 URL → 신청 URL
```

---

## 다음 작업

1. Gemini API 호출부가 이 JSON 계약을 따르도록 연결
2. `sentence_list`를 slot preservation layer 입력으로 사용
3. `role_hint=application_period/event_datetime/contact/application_url/target` 우선 처리
4. `info_cards` 응답 필드 설계 및 카드 빌더 연결
5. 서귀포/백제권 PDF 회귀 테스트 추가

---

## Backend 연결 현황

`/notice/analyze/{notice_id}` 응답에 `info_cards` 필드를 추가했다.

```json
{
  "cards": [],
  "info_cards": [],
  "highlights": []
}
```

역할:

```text
cards:
  모델 A/B와 기존 card_builder 중심의 "해야 할 일" 카드

info_cards:
  sentence_list / slot preservation 중심의 "꼭 확인할 정보" 카드
  신청기간, 운영일시, 신청 URL, 문의, 대상 등

highlights:
  cards + info_cards 모두를 원본 layout_json과 매칭한 bbox 후보
```

현재는 Gemini 호출 전 단계이므로 `raw_text_to_sentence_list()` fallback adapter로 `info_cards`를 생성한다. 태수님 Gemini sentence list가 붙으면 이 입력만 Gemini JSON으로 교체하면 된다.

---

## OCR layout persistence

촬영 OCR에서 bbox가 사라지는 문제를 줄이기 위해 업로드 시점의 `layout_json` 저장 경로를 추가했다.

변경:

```text
backend/app/models/schemas.py
- Notice.layout_json 추가

backend/app/routers/notice.py
- /notice/upload, /notice/upload-self 에 optional Form layout_json 추가
- 업로드 시 JSON parse 후 Notice에 저장
- analyze 시 req.layout_json이 있으면 우선 사용
- req.layout_json이 없으면 notice.layout_json fallback
- highlights/page_count/reconstruct 모두 analysis_layout 기준 사용

android/app/src/main/java/com/multicultural/demo/OcrActivity.java
- upload-self multipart에 bestOcrLayoutJson을 layout_json field로 함께 전송
- OCR_RESULT.TXT와 별도로 촬영 원본 jpg를 original_file field로 함께 전송
```

효과:

```text
촬영 OCR 후 앱 화면 재진입/재분석 상황에서도 서버에 저장된 layout_json을 사용할 수 있다.
기존처럼 MainActivity 메모리에만 의존하지 않는다.
원본 파일 URL도 OCR_RESULT.TXT가 아니라 촬영 이미지 쪽을 바라볼 수 있다.
```

남은 과제:

```text
Android 원본 보기 화면에서 촬영 이미지와 highlights overlay를 실제로 그리는 UI 연결이 필요하다.
layout_json 좌표계와 서버에 저장된 촬영 이미지 렌더링 크기 간 scale 검증이 필요하다.
```

검증:

```powershell
python -m py_compile backend\app\models\schemas.py backend\app\routers\notice.py
cd android
.\gradlew.bat assembleDebug "-Pschoolbridge.baseUrl=http://101.79.17.196:8000/"
```

---

## 한 줄 요약

Gemini에게 정답을 달라고 하는 것이 아니라, SchoolBridge가 원하는 문서 뼈대를 조립하게 한다.
