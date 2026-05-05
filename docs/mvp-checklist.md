# MVP 정의서 및 체크리스트

## 서비스 MVP 정의

선생님이 가정통신문을 발송하면 학부모가 앱에서 수신하고, AI가 핵심 행동 항목을 체크리스트로 정리한 뒤 쉬운 한국어 + 8개국어(베트남어/영어/러시아어/말레이시아어/몽골어/중국어/태국어/일본어) 번역과 언어별 음성 안내를 제공하는 서비스입니다.

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
| X-User-Id 헤더 인증 | 역할(teacher/parent) 기반 권한 검증 | 완료 |
| 분석 API | `POST /notice/analyze/{notice_id}` (target_language) | 실제 모델 연결 완료 |
| 체크리스트 표시 | 해야 할 일을 카테고리별로 보여 줌 | 실제 모델 결과 표시 |
| 쉬운 한국어 | 학부모가 이해하기 쉬운 문장으로 요약 | 완료 |
| 다국어 번역 | NLLB 기반 8개국어 번역(vi/en/ru/ms/mn/zh/th/ja) + 통화 오번역 후처리 | 완료 |
| 용어사전 검수 | 학교 안내 핵심 용어 누락 확인 | 완료 (용어 확장) |
| TTS 재생 | 언어별 Edge-TTS 음성(9개) 또는 앱 내장 mp3 fallback | 완료 |
| Android 실기기 데모 | Java 단일 Activity 앱 | 완료 |
| HWP/PDF/텍스트 파일 업로드 | `POST /notice/upload` — LibreOffice + H2Orestart 변환, `services/parser.py` | 완료 |
| 카메라 OCR (학부모) | `OcrActivity` — ML Kit Korean 온디바이스, 4종 전처리, 2-pass 표 재인식, `POST /notice/upload-self` | 완료 |
| **원본 가정통신문 표시 (학부모)** | 백엔드 `static/notices/{id}{ext}` 보존 + Notice 응답에 `original_file_url`/`mime_type`, 안드 카드 클릭 → PDF/이미지 풀화면 | 완료 |
| **HF Spaces 실서버 배포** | `https://maxmunzy-schoolbridge.hf.space` (Docker SDK, CPU basic, 24/7) | 완료 |

### 제외

| 기능 | 제외 이유 |
| --- | --- |
| 실제 학교 시스템 연동 | MVP 이후 확장 범위 |
| 자동 문자/푸시 알림 | 앱 내 수신함 시연을 우선 |
| 자동 일정 등록 | 핵심 안내 이해를 우선 |
| iOS 앱 | Android 실기기 데모 우선 |

---

## 체크리스트

### 데이터

- [x] 6개 카테고리 체계 정의: 일정, 준비물, 제출, 비용, 건강/안전, 기타
- [x] `data/labeled/notice_sample_v3.csv` 200개 샘플 확보 (초기)
- [x] **`v3_dual_labeled.jsonl` 28,890행 확보 (이중 라벨: is_todo + is_title)**
- [x] **`notice_sample_v5_clean_full_20260504.csv` 4,992행 (분류 모델 학습용 — Claude Haiku 자동 라벨링 + 73건 후처리)**
- [x] 컬럼 정의: `id`, `source_type`, `original_text`, `category`, `keywords`, `importance`, `action_required`, `easy_korean`, `vietnamese`, `tts_target`
- [x] 번역/TTS 입력 샘플: `data/translation_tts/easy_ko_text_sample.csv`

### 모델 A: 중요 문장 추출

- [x] baseline 추출 모델 구현 (KoELECTRA 하이브리드, `model/extraction/predict.py`)
- [x] 평가 기준 정의 (confidence 임계값 0.4, importance 임계값 0.3, 카테고리별 기본 점수)
- [x] 서버 연결용 `extract_todos_dict()` 인터페이스 설계
- [x] `POST /notice/analyze/{notice_id}` 응답에 실제 추출 결과 연결

### 모델 B: 분류/중요도

- [x] 6개 카테고리 분류 baseline 구현 (numpy LR / sklearn / SBERT 멀티트랙)
- [x] **KcELECTRA v3 파인튜닝 완료 — Macro F1 0.8545 (Simple 베이스라인 0.8116 대비 +4.29%p, 건강·안전 클래스 0.29 → 0.91 회복)**
- [x] **HF Hub 배포: `kysophia/kcelectra-category` (subfolder: `kcelectra-category-v3`)**
- [x] 중요도 점수 산출 기준 확정 (룰 기반 시급도 + Ridge 회귀 결합)
- [x] 서버 연결용 `model/classification/src/classifier_kcelectra.py` (HF Hub fallback 포함)
- [x] 메인 백엔드(`POST /notice/analyze`)와 실제 연결

### 모델 C: 번역/TTS

- [x] NLLB 모델 기준 확정: `facebook/nllb-200-distilled-600M`
- [x] Edge-TTS 다국어 음성 매핑(9개): `vi-VN-HoaiMyNeural`, `en-US-JennyNeural`, `ru-RU-SvetlanaNeural`, `ms-MY-YasminNeural`, `mn-MN-YesuiNeural`, `zh-CN-XiaoxiaoNeural`, `th-TH-PremwadeeNeural`, `ja-JP-NanamiNeural`, `ko-KR-SunHiNeural`
- [x] 용어사전 파일 구성: `model/translation_tts/term_glossary.csv`
- [x] 고정 데모 산출물 생성: `demo/translation_tts/demo_case_01/`
- [x] Android 앱에 데모 산출물 포함
- [x] 서버 API에 번역/TTS 파이프라인 직접 연결 (target_language 파라미터로 8개국어 동적 라우팅)

### Backend

- [x] FastAPI 앱 구성
- [x] Docker 실행 환경 구성
- [x] 공통 응답 형식: `{ status, data, message }`
- [x] `POST /notice/send` (teacher 권한 + body.teacher_id 일치 검증)
- [x] `POST /notice/upload` (HWP/PDF/text multipart, teacher 권한)
- [x] `POST /notice/upload-self` (parent 자가 업로드 — 종이 통신문 촬영본)
- [x] `GET /notice/inbox/{parent_id}` (parent 본인만)
- [x] `DELETE /notice/inbox/{parent_id}` (parent 본인만, 시연용)
- [x] `POST /notice/analyze/{notice_id}` (parent 본인만, target_language 동적)
- [x] `POST /tts/generate` (언어별 Edge-TTS 보이스 자동 매핑)
- [x] `services/parser.py` — HWP/PDF/text/이미지 → clean_text (LibreOffice + H2Orestart + Tesseract fallback)
- [x] `GET /user/{id}`, `POST /user/`
- [x] `GET /health`
- [x] X-User-Id 헤더 인증 + 역할 기반 권한(teacher/parent) 검증
- [x] 시연용 시드 계정: `teacher_001/002`, `parent_001/002/003`
- [x] 실제 모델 서비스 연결

### Android

- [x] 로그인 화면 (역할 선택 → ID 입력 → 들어가기)
- [x] 선생님 화면: 가정통신문 작성/발송 (X-User-Id 자동 첨부)
- [x] 학부모 화면: 수신함 카드 리스트
- [x] 통신문 상세 화면 (우측 상단 ✨ AI 번역 버튼)
- [x] AI 분석 화면: 체크리스트 + 쉬운 한국어 + 모국어 번역 + 학교 용어 + TTS
- [x] 9개 언어 선택 드롭다운 (변경 시 자동 재분석)
- [x] 글자 크기 조절(A−/A+)
- [x] TTS 재생/정지 토글
- [x] 내장 데모 산출물 fallback (서버 연결 실패 시)
- [x] 내장 mp3 TTS 재생
- [x] 학부모 홈 카메라 OCR (OcrActivity — ML Kit Korean, 4종 전처리, 2-pass 표 재인식)
- [x] 선생님 홈 HWP/PDF/이미지 파일 업로드
- [x] **학부모 알림 카드 클릭 → 원본 PDF/이미지 풀화면 표시 (PdfRenderer + ImageView, 다중 페이지 PDF 네비)**
- [x] **`BASE_URL`을 HF Spaces 실서버(`https://maxmunzy-schoolbridge.hf.space`)로 통일 — 팀 시연 환경 일관성**

### 문서

- [x] `docs/team-brief.md` 최신화
- [x] `docs/mvp-checklist.md` 최신화
- [x] `docs/troubleshooting.md` 최신화

---

## 최소 완료 기준

- [x] Android 실기기에서 앱 실행
- [x] FastAPI 서버 Swagger UI 접속 확인: `https://maxmunzy-schoolbridge.hf.space/docs` (배포) 또는 `http://localhost:8000/docs` (로컬)
- [x] 선생님 화면에서 발송 성공
- [x] 학부모 화면에서 수신함 조회 성공
- [x] 분석 결과 화면 표시 (실제 모델 결과)
- [x] 선택 언어별 TTS 재생 확인 (vi/en/ru/ms/mn/zh/th/ja/ko_easy)
- [x] 발표 시 mock 범위와 실제 구현 범위 구분 설명

---

## 현재 리스크

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| HF Spaces 콜드스타트 | 분류기/추출기/NLLB 첫 호출 시 HF Hub에서 가중치 다운로드(~1.5GB), 3-5분 소요 | 시연 30분 전 `/notice/analyze` 1회 호출로 warmup 필수 (이후 hf_cache로 빠름) |
| HF Spaces ephemeral storage | 컨테이너 재시작 시 업로드된 가정통신문 원본·notice 메모리 초기화 | 시연 직전 1회 업로드 권장 (영구 저장 필요한 운영 단계는 별도 storage 도입) |
| NLLB 출력 품질 변동 | 일부 문장 어색한 번역 가능 | 용어사전 검수와 교차검증 결과로 보완 설명 |
| 체크리스트 인사말 포함 | "학부모님 안녕하세요" 등 인사말이 TODO로 분류될 수 있음 | 추출 모델 필터 개선 예정 |
