# MVP 정의서 및 체크리스트

## 서비스 MVP 정의

선생님이 가정통신문을 발송하면 학부모가 앱에서 수신하고, AI가 핵심 행동 항목을 체크리스트로 정리한 뒤 쉬운 한국어, 베트남어 번역, 음성 안내를 제공하는 서비스입니다.

이번 MVP의 목표는 완성형 서비스가 아니라, 아래 3가지를 보여 주는 것입니다.

1. 실제로 동작하는 모바일 시연 흐름
2. 번역/TTS 파이프라인의 고정 산출물
3. 모델 미완성 범위와 다음 연결 지점

---

## MVP 범위

### 포함

| 기능 | 설명 | 상태 |
| --- | --- | --- |
| 가정통신문 발송/수신 | 선생님 화면에서 발송, 학부모 화면에서 수신 | 완료 |
| 분석 API | `POST /notice/analyze/{notice_id}` | mock 완료 |
| 체크리스트 표시 | 해야 할 일을 카테고리별로 보여 줌 | mock 완료 |
| 쉬운 한국어 | 학부모가 이해하기 쉬운 문장으로 요약 | 데모 산출물 완료 |
| 베트남어 번역 | NLLB 기반 번역 | 1차 산출물 완료 |
| 용어사전 검수 | 학교 안내 핵심 용어 누락 확인 | 1차 산출물 완료 |
| TTS 재생 | Edge-TTS mp3 또는 앱 내장 mp3 재생 | 완료 |
| Android 실기기 데모 | Java 단일 Activity 앱 | 완료 |

### 제외

| 기능 | 제외 이유 |
| --- | --- |
| OCR 이미지/PDF 인식 | 텍스트 입력 흐름 검증을 우선 |
| 실제 학교 시스템 연동 | MVP 이후 확장 범위 |
| 자동 문자/푸시 알림 | 앱 내 수신함 시연을 우선 |
| 자동 일정 등록 | 핵심 안내 이해를 우선 |
| iOS 앱 | Android 실기기 데모 우선 |
| 완성형 추출/분류 모델 | 현재는 mock 응답으로 화면 흐름 검증 |

---

## 체크리스트

### 데이터

- [x] 6개 카테고리 체계 정의: 일정, 준비물, 제출, 비용, 건강/안전, 기타
- [x] `data/labeled/notice_sample_v3.csv` 200개 샘플 확보
- [x] 컬럼 정의: `id`, `source_type`, `original_text`, `category`, `keywords`, `importance`, `action_required`, `easy_korean`, `vietnamese`, `tts_target`
- [x] 번역/TTS 입력 샘플: `data/translation_tts/easy_ko_text_sample.csv`
- [ ] 데이터 인코딩 깨짐 여부 점검 및 원문 복구

### 모델 A: 중요 문장 추출

- [ ] baseline 추출 모델 구현
- [ ] 평가 기준 정의
- [ ] 서버 연결용 `services/extractor.py` 설계
- [ ] `POST /notice/analyze/{notice_id}` 응답에 실제 추출 결과 연결

### 모델 B: 분류/중요도

- [ ] 6개 카테고리 분류 baseline 구현
- [ ] 중요도 점수 산출 기준 확정
- [ ] 서버 연결용 `services/classifier.py` 설계
- [ ] Android 표시 포맷과 응답 스키마 확정

### 모델 C: 번역/TTS

- [x] NLLB 모델 기준 확정: `facebook/nllb-200-distilled-600M`
- [x] Edge-TTS 음성 기준 확정: `vi-VN-HoaiMyNeural`
- [x] 용어사전 파일 구성: `model/translation_tts/term_glossary.csv`
- [x] 고정 데모 산출물 생성: `demo/translation_tts/demo_case_01/`
- [x] Android 앱에 데모 산출물 포함
- [ ] 서버 API에 번역/TTS 파이프라인 직접 연결

### Backend

- [x] FastAPI 앱 구성
- [x] Docker 실행 환경 구성
- [x] 공통 응답 형식: `{ status, data, message }`
- [x] `POST /notice/send`
- [x] `GET /notice/inbox/{parent_id}`
- [x] `POST /notice/analyze/{notice_id}`
- [x] `POST /tts/generate`
- [x] `GET /user/{id}`, `POST /user/`
- [x] `GET /health`
- [ ] 깨진 한글 문자열 및 Python 문법 점검
- [ ] 실제 모델 서비스 연결

### Android

- [x] 시작 화면
- [x] 선생님 발송 화면
- [x] 학부모 수신함 화면
- [x] 분석 요청 버튼
- [x] 분석 결과 표시
- [x] 내장 데모 산출물 fallback
- [x] 내장 mp3 TTS 재생
- [ ] `BASE_URL` 환경별 설정 방식 개선

### 문서

- [x] `docs/team-brief.md` 최신화
- [x] `docs/mvp-checklist.md` 최신화
- [x] `docs/troubleshooting.md` 최신화
- [ ] `README.md` 깨진 한글 복구
- [ ] `data/README.md` 깨진 한글 복구
- [ ] `model/translation_tts/README.md` 깨진 한글 복구
- [ ] `android/README.md` 깨진 한글 복구

---

## 최소 완료 기준

- [ ] Android 실기기에서 앱 실행
- [ ] PC FastAPI 서버의 Swagger UI 접속 확인: `http://localhost:8000/docs`
- [ ] 선생님 화면에서 발송 성공
- [ ] 학부모 화면에서 수신함 조회 성공
- [ ] 분석 결과 화면 표시
- [ ] 베트남어 TTS 재생 확인
- [ ] 발표 시 mock 범위와 실제 구현 범위 구분 설명

---

## 현재 리스크

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| 일부 한글 파일 깨짐 | 문서/코드 설명 이해 어려움, Python 문자열 오류 가능 | UTF-8 기준으로 순차 복구 |
| 추출/분류 모델 미연결 | 분석 결과가 실제 AI 결과가 아님 | 발표에서 mock 범위 명시 |
| Android `BASE_URL` 고정 | 네트워크가 바뀌면 앱 수정 필요 | 시연 전 PC IP 확인 |
| NLLB 출력 품질 변동 | 자연스럽지 않은 번역 가능 | 용어사전 검수와 보정 번역으로 설명 |
