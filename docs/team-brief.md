# 팀 진행 브리프

## 현재 프로젝트 한 줄 설명

가정통신문 AI 도우미는 선생님이 보낸 안내문에서 학부모가 바로 확인해야 할 일을 뽑고, 쉬운 한국어 + 8개국어(베트남어/영어/러시아어/말레이시아어/몽골어/중국어/태국어/일본어) 번역과 언어별 음성 안내까지 이어 주는 MVP입니다.

현재 저장소 기준 핵심은 다음 흐름입니다.

```text
선생님 Android 화면  (X-User-Id: teacher_xxx)
  -> POST /notice/send (teacher 권한 검증)
FastAPI 서버
  -> 임시 메모리 저장
학부모 Android 화면  (X-User-Id: parent_xxx)
  -> GET /notice/inbox/{parent_id} (본인만)
  -> POST /notice/analyze/{notice_id} (target_language 지정)
분석 결과
  -> 체크리스트, 쉬운 한국어, 선택 언어 번역, 용어 검수, 언어별 TTS 재생
```

Android 앱은 모델을 직접 실행하지 않습니다. 서버 API를 호출하고, 서버 응답이 없거나 TTS URL이 없을 때는 앱에 포함된 고정 데모 산출물을 fallback으로 보여 줍니다.

`/notice/*` 엔드포인트는 모두 `X-User-Id` 헤더로 요청자를 식별하고 역할(teacher/parent) 권한을 검증합니다. MVP 단계라 토큰 없이 헤더 한 줄로 처리하며, 시드 계정은 `teacher_001/002`와 `parent_001/002/003`입니다.

---

## 탑재형 AI 도우미 모듈

이 프로젝트의 핵심은 새로운 알림장 앱 자체를 만드는 것이 아니라, 기존 학교 알림장/가정통신문 서비스가 가져다 쓸 수 있는 AI 도우미 모듈을 만드는 것입니다. Android 앱은 이 모듈의 동작을 보여 주기 위한 실기기 데모 클라이언트입니다.

서버와 모델 파이프라인은 가정통신문 텍스트와 학부모가 선택한 언어 코드(target_language)를 받아 체크리스트, 쉬운 한국어, 선택 언어 번역(8개국어 중 1), 용어 검수 결과, 해당 언어 TTS 음성을 만들어 반환합니다. 이후에는 기존 학교 앱이나 알림장 서비스가 같은 API를 호출하는 방식으로 확장할 수 있습니다.

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
| Backend | 완료 | FastAPI, Docker, `/notice`, `/tts`, `/user`, `/health` 라우터 구성. X-User-Id 헤더 + 역할 권한 검증. 분석 API 다국어(9개) 실제 모델 연결 완료 |
| Android | 완료 | Java 단일 Activity 실기기 데모. 로그인→역할 탭→통신문 상세→AI 오버레이 4단 흐름. ReadTimeout 60초, 내장 TTS fallback 포함 |
| 데이터 | 완료 | `notice_sample_v3.csv` 200개, 6개 카테고리 체계 |
| 번역/TTS | 완료 | NLLB 다국어 번역(vi/en/ru/ms/mn/zh/th/ja), 용어사전 검수(확장), Edge-TTS 언어별 음성 매핑(9개), 통화 오번역 후처리 포함 |
| 추출 모델 | 연결 완료 | KoELECTRA 하이브리드 (`predict.py`), HuggingFace Hub 배포 (`yunjeong116/koelectra-extractor`). 백엔드 연결 완료 |
| 분류 모델 | 연결 완료 | numpy/sklearn/SBERT 멀티트랙, accuracy 0.857, MAE 0.038. 백엔드 교차검증 연결 완료 |
| 통합 E2E | 완료 | 전체 파이프라인 실기기 동작 확인. 초기 warmup 후 약 30초 내 응답 |

---

## 모델 파이프라인 기준

```text
가정통신문 텍스트 + target_language
  -> 모델 A: 중요 문장 추출 (윤정 KoELECTRA)
  -> 모델 B: 6개 카테고리 분류 + 중요도 산출 (경이) → 교차검증 결과 review_needed에 합침
  -> 모델 C: 쉬운 한국어 + 선택 언어 번역(NLLB, 8개국어)
  -> 용어사전 검수: 학교 안내 핵심 용어 누락 확인
  -> Edge-TTS: 선택 언어 음성 mp3 생성 (9개 보이스 매핑)
  -> Android 출력
```

현재 `model/translation_tts/run_mvp_pipeline.py`는 번역/TTS 파트의 독립 실행 스크립트입니다. 기본 NLLB 모델은 `facebook/nllb-200-distilled-600M`, TTS는 언어별 보이스 매핑(`vi-VN-HoaiMyNeural`, `en-US-JennyNeural`, `ru-RU-SvetlanaNeural`, `ms-MY-YasminNeural`, `mn-MN-YesuiNeural`, `zh-CN-XiaoxiaoNeural`, `th-TH-PremwadeeNeural`, `ja-JP-NanamiNeural`, `ko-KR-SunHiNeural`)을 사용합니다.

---

## 다음 우선 과제

1. 추출 모델 인사말 필터 보강 (체크리스트에 인사말 포함되는 문제)
2. 모델 튜닝: 체크리스트 정밀도 향상, NLLB 번역 품질 개선
3. 용어사전 지속 확장
4. 발표에서 E2E 파이프라인 시연 및 검수 루프 설명

---

## 발표용 핵심 문장

선생님이 가정통신문을 보내면 학부모 앱에서 핵심 체크리스트와 쉬운 한국어, 모국어 번역(8개국어 중 선택), 음성 안내를 확인할 수 있습니다. 추출 모델(KoELECTRA), 분류 모델(SBERT 기반), 번역/TTS 파이프라인(NLLB + Edge-TTS 9개 보이스)이 모두 메인 백엔드에 연결되어 실기기에서 E2E 동작이 확인된 상태입니다. 백엔드는 X-User-Id 헤더 기반의 역할 권한 검증으로 선생님/학부모 흐름을 분리합니다.
