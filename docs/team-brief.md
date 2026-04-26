# 팀 진행 브리프

## 현재 프로젝트 한 줄 설명

가정통신문 AI 도우미는 선생님이 보낸 안내문에서 학부모가 바로 확인해야 할 일을 뽑고, 쉬운 한국어와 베트남어 번역, 음성 안내까지 이어 주는 MVP입니다.

현재 저장소 기준 핵심은 다음 흐름입니다.

```text
선생님 Android 화면
  -> POST /notice/send
FastAPI 서버
  -> 임시 메모리 저장
학부모 Android 화면
  -> GET /notice/inbox/{parent_id}
  -> POST /notice/analyze/{notice_id}
분석 결과
  -> 체크리스트, 쉬운 한국어, 베트남어 번역, 용어 검수, TTS 재생
```

Android 앱은 모델을 직접 실행하지 않습니다. 서버 API를 호출하고, 서버 응답이 없거나 TTS URL이 없을 때는 앱에 포함된 고정 데모 산출물을 fallback으로 보여 줍니다.

---

## 역할 분담

| 이름 | 담당 | 주요 위치 |
| --- | --- | --- |
| 지수 | FastAPI 서버, API 설계, Android 통신 연결 | `backend/` |
| 수정 | 중요 문장 추출 모델 | `model/extraction/` |
| 경이 | 카테고리 분류, 중요도 모델 | `model/classification/` |
| 세종 | NLLB 번역, 학교 용어사전 검수, Edge-TTS 출력, 데이터셋 | `model/translation_tts/`, `data/`, `demo/translation_tts/` |
| 차영 | Android 실기기 데모, UI, 발표 자료 | `android/`, `docs/` |

---

## 현재 구현 상태

| 영역 | 상태 | 메모 |
| --- | --- | --- |
| Backend | 1차 구현 | FastAPI, Docker, `/notice`, `/tts`, `/user`, `/health` 라우터 구성 |
| Android | 1차 구현 | Java 기반 단일 Activity 실기기 데모, `HttpURLConnection`, 내장 TTS fallback 포함 |
| 데이터 | 1차 정리 | `notice_sample_v3.csv` 200개, 6개 카테고리 체계 |
| 번역/TTS | 1차 MVP 산출물 있음 | NLLB 번역, 용어사전 검수, Edge-TTS mp3 산출물 |
| 추출 모델 | 미완료 | 현재 서버 분석 응답은 mock 데이터 |
| 분류 모델 | 미완료 | 현재 서버 분석 응답은 mock 데이터 |
| 통합 E2E | 부분 완료 | Android 화면 흐름은 연결됨. 실제 모델 서버 연결은 남음 |

---

## 모델 파이프라인 기준

```text
가정통신문 텍스트
  -> 모델 A: 중요 문장 추출
  -> 모델 B: 6개 카테고리 분류 + 중요도 산출
  -> 모델 C: 쉬운 한국어 기반 베트남어 번역(NLLB)
  -> 용어사전 검수: 학교 안내 핵심 용어 누락 확인
  -> Edge-TTS: 베트남어 음성 mp3 생성
  -> Android 출력
```

현재 `model/translation_tts/run_mvp_pipeline.py`는 번역/TTS 파트의 독립 실행 스크립트입니다. 기본 모델은 `facebook/nllb-200-distilled-600M`, TTS 음성은 `vi-VN-HoaiMyNeural`입니다.

---

## 다음 미팅 전 우선 산출물

1. Android 실기기에서 선생님 발송 -> 학부모 수신 -> 분석 결과 확인 -> TTS 재생까지 시연
2. `demo/translation_tts/demo_case_01/` 산출물로 번역/TTS 검수 루프 설명
3. `data/labeled/notice_sample_v3.csv` 기준 데이터셋과 6개 라벨 체계 설명
4. 추출/분류 모델은 mock 상태임을 명확히 표시하고, 다음 연결 계획 제시

---

## 발표용 핵심 문장

선생님이 가정통신문을 보내면 학부모 앱에서 핵심 체크리스트와 쉬운 한국어, 베트남어 번역, 음성 안내를 확인할 수 있습니다. 현재 MVP는 실기기 화면 흐름과 번역/TTS 검수 산출물을 먼저 고정했고, 추출/분류 모델은 다음 단계에서 서버에 연결합니다.
