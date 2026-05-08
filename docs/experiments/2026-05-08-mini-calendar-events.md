# Mini Calendar Event Track

## Context

강사님 피드백 이후 SchoolBridge의 차별점은 단순 요약/번역이 아니라, 가정통신문 속 핵심 정보를 실제 행동으로 연결하는 UX에 두기로 했다.

이번 작업은 slot preservation 결과를 앱 내부 미니 달력으로 연결하기 위한 PoC이다.

```text
가정통신문 분석
→ 날짜/시간/URL/문의/대상 slot 보존
→ calendar_events 생성
→ 앱 내부 미니 달력 표시
→ 날짜 클릭 시 일정 상세/QR/바로가기 제공
→ 이후 알림/문화 카드/퀴즈로 확장
```

## Added Backend Contract

`/notice/analyze/{notice_id}` 응답에 `calendar_events`를 추가했다.

```json
{
  "calendar_events": [
    {
      "event_id": "notice_s001_1",
      "notice_id": "notice_123",
      "title": "토요프로그램 안내",
      "type": "application_period",
      "label": "신청기간",
      "start_date": "2026-04-21",
      "end_date": "2026-04-24",
      "time": "10:00~24:00",
      "display_text": "신청기간: 2026. 4. 21.(화) 10:00 ~ 4. 24.(금) 24:00",
      "color": "blue",
      "actions": [
        {"type": "open_url", "label": "바로가기", "value": "https://..."},
        {"type": "show_qr", "label": "QR 보기", "value": "https://..."},
        {"type": "set_reminder", "label": "알림 설정", "value": "2026-04-21"}
      ]
    }
  ]
}
```

## Event Types

| Type | UI Meaning | Color |
|---|---|---|
| `application_period` | 신청기간 | blue |
| `event_datetime` | 운영일시/행사일 | green |
| `submit_deadline` | 제출 | orange |
| `payment_deadline` | 납부/비용 | red |
| `result_announcement` | 결과발표 | purple |
| `holiday` | 공휴일/재량휴업일/기념일 | red |
| `school_event` | 기타 일정 | gray |

## Android UI

AI 분석 화면 하단에 `📅 미니 달력` 버튼을 추가했다.

- 기간형 일정은 날짜 칸 안에 bar로 표시한다.
- 하루짜리 일정은 dot으로 표시한다.
- 휴업일/기념일 계열은 red로 표시한다.
- 날짜를 누르면 해당 날짜의 일정 상세를 보여준다.
- 일정에 URL action이 있으면 `바로가기`와 `QR 보기`를 제공한다.

## Why It Matters

Gemini나 일반 챗봇은 PDF 내용을 요약할 수 있지만, SchoolBridge는 일정 정보를 앱 내부 행동 데이터로 바꾼다.

```text
slot을 보존한다
→ 카드로 보여준다
→ 미니 달력에 표시한다
→ QR/바로가기/알림으로 행동까지 연결한다
```

이 흐름이 단순 번역 앱과의 차별점이다.

## Next

- Android 알림 권한 및 로컬 리마인더 구현
- 일정 클릭 시 원본 카드 위치로 이동
- 학사 일정/기념일 기반 문화 카드 연결
- 문화 카드에서 TTS 설명 및 선택형 퀴즈 제공
