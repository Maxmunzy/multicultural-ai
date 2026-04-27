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

## 탑재형 AI 도우미 모듈

이 프로젝트의 핵심은 새로운 알림장 앱 자체를 만드는 것이 아니라, 기존 학교 알림장/가정통신문 서비스가 가져다 쓸 수 있는 AI 도우미 모듈을 만드는 것입니다. Android 앱은 이 모듈의 동작을 보여 주기 위한 실기기 데모 클라이언트입니다.

서버와 모델 파이프라인은 가정통신문 텍스트를 받아 체크리스트, 쉬운 한국어, 베트남어 번역, 용어 검수 결과, TTS 음성을 만들어 반환합니다. 이후에는 기존 학교 앱이나 알림장 서비스가 같은 API를 호출하는 방식으로 확장할 수 있습니다.

---

## 역할 분담

| 이름 | 담당 | 주요 위치 |
| --- | --- | --- |
| 태수 | FastAPI 서버, API 설계, Android 통신 연결 | `backend/` |
| 윤정 | 중요 문장 추출 모델 | `model/extraction/` |
| 경이 | 카테고리 분류, 중요도 모델 | `model/classification/` |
| 세종 | NLLB 번역, 학교 용어사전 검수, Edge-TTS 출력, 데이터셋 | `model/translation_tts/`, `data/`, `demo/translation_tts/` |
| 찬영 | Android 실기기 데모, UI, 발표 자료 | `android/`, `docs/` |

---

## 현재 구현 상태

| 영역 | 상태 | 메모 |
| --- | --- | --- |
| Backend | 완료 | FastAPI, Docker, `/notice`, `/tts`, `/user`, `/health` 라우터 구성. 분석 API 실제 모델 연결 완료 |
| Android | 완료 | Java 기반 단일 Activity 실기기 데모, ReadTimeout 60초, 내장 TTS fallback 포함 |
| 데이터 | 완료 | `notice_sample_v3.csv` 200개, 6개 카테고리 체계 |
| 번역/TTS | 완료 | NLLB 번역, 용어사전 검수(확장), Edge-TTS mp3, 통화 오번역 후처리 포함 |
| 추출 모델 | 연결 완료 | KoELECTRA 하이브리드 (`predict.py`), HuggingFace Hub 배포 (`yunjeong116/koelectra-extractor`). 백엔드 연결 완료 |
| 분류 모델 | 연결 완료 | numpy/sklearn/SBERT 멀티트랙, accuracy 0.857, MAE 0.038. 백엔드 교차검증 연결 완료 |
| 통합 E2E | 완료 | 전체 파이프라인 실기기 동작 확인. 초기 warmup 후 약 30초 내 응답 |

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

## 다음 우선 과제

1. 추출 모델 인사말 필터 보강 (체크리스트에 인사말 포함되는 문제)
2. 모델 튜닝: 체크리스트 정밀도 향상, NLLB 번역 품질 개선
3. 용어사전 지속 확장
4. 발표에서 E2E 파이프라인 시연 및 검수 루프 설명

---

## 발표용 핵심 문장

선생님이 가정통신문을 보내면 학부모 앱에서 핵심 체크리스트와 쉬운 한국어, 베트남어 번역, 음성 안내를 확인할 수 있습니다. 추출 모델(KoELECTRA), 분류 모델(SBERT 기반), 번역/TTS 파이프라인(NLLB + Edge-TTS)이 모두 메인 백엔드에 연결되어 실기기에서 E2E 동작이 확인된 상태입니다.
