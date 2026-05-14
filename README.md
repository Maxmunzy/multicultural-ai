# 가정통신문 AI 도우미 - 다문화 가정 학부모용

> 학교에서 온 가정통신문에서 "엄마가 오늘·내일 해야 할 일"을 뽑아 체크리스트로 정리하고,
> 쉬운 한국어 + 8개국어(베트남어/영어/러시아어/말레이시아어/몽골어/중국어/태국어/일본어) 번역과 음성 안내까지 제공하는 탑재형 AI 모듈 & TTS 서비스
>
> **SchoolBridge** — 2026년 5월 기준 NCP Seoul VM(101.79.17.196:8000) 실서버 운영 중

---

## 팀 역할 분담

| 이름 | 담당 | 폴더 |
| --- | --- | --- |
| 태수 | FastAPI 서버, API 설계, 모델 연결, Android 통신 | `backend/` |
| 윤정 | 가정통신문에서 할 일 문장 추출 모델 | `model/extraction/` |
| 경이 | 추출 문장 카테고리 분류 및 중요도 모델 | `model/classification/` |
| 세종 | 다국어 번역, 학교 용어사전, 번역 검수 루프, TTS 출력, TTS 속도 조절, STT 음성 질문, 카메라 OCR (Android ML Kit) | `model/translation_tts/` · `android/` (OcrActivity) |
| 찬영 | 발표자료 | `docs/` |

---

## 서비스 흐름

```text
[선생님 Android 앱]  (X-User-Id: teacher_xxx)
    │ 방법 1: 가정통신문 제목/본문 직접 입력
    ▼ POST /notice/send
    │
    │ 방법 2: HWP·PDF·TXT 파일 선택
    ▼ POST /notice/upload  → parser(태수): HWP→ODT→텍스트 / PDF→pdfplumber
    │
    │ 방법 3: 카메라 사진 촬영 (OcrActivity, 학부모 홈)
    │   ML Kit Korean OCR (4종 전처리 + 2-pass 표 재인식) → Quality Gate(0.80) → POST /notice/upload-self
    ▼
[FastAPI 서버]
    │ 권한 검증 (teacher 역할) · 가정통신문 저장
    ▼
[학부모 Android 앱]  (X-User-Id: parent_xxx)
    │ 본인 수신함 조회
    ▼ GET /notice/inbox/{parent_id}
[학부모 Android 앱]
    │ 통신문 상세 → ✨ AI 번역 버튼
    ▼ POST /notice/analyze/{notice_id}  (target_language)
[FastAPI 서버 + 모델 파이프라인]
    │ [1] Claude Haiku 4.5 — sentence_list 정제 + role_hint 태깅 (13종)
    │ [2] 윤정 KoELECTRA — 행동 문장(is_todo) 추출
    │ [3] 경이 KcELECTRA — 6개 카테고리 분류
    │ [4] 세종 NLLB-200 + 글로사리(340+) — 9개 언어 번역
    │       → info_cards (준비물·비용·제출 체크리스트)
    │       → calendar_events (일정·기한·신청기간 달력 표시)
    │       → Edge-TTS 음성 생성
    ▼
[학부모 Android 앱]
    체크리스트 카드 + info_cards + 달력/미니달력
    + 모국어 번역(9개 중 선택) + TTS 재생 + STT 음성 질문(6카테고리)
```

Android 앱은 모델을 직접 실행하지 않습니다.  
앱은 FastAPI 서버에 요청을 보내고, 서버와 모델 파이프라인이 만든 결과를 화면에 보여주는 역할을 합니다.

### 인증

모든 `/notice/*` 엔드포인트는 **`X-User-Id` 헤더**로 요청자를 식별하고 역할(`teacher`/`parent`) 권한을 검증합니다. MVP 단계라 비밀번호 없이 헤더 한 줄로 처리(JWT/세션은 운영 단계 도입 예정).

시연용 시드 계정 (서버 시작 시 자동 등록):

| user_id | 역할 |
| --- | --- |
| `teacher_001`, `teacher_002` | teacher |
| `parent_001`, `parent_002`, `parent_003` | parent |

---

## API 목록

모든 `/notice/*` 호출은 **`X-User-Id` 헤더 필수**.

| 엔드포인트 | 메서드 | 권한 | 설명 |
| --- | --- | --- | --- |
| `/notice/send` | POST | teacher 본인 | 선생님이 학부모에게 가정통신문 발송 (body의 `teacher_id`가 헤더와 일치해야 함) |
| `/notice/upload` | POST | teacher 본인 | HWP·PDF·TXT·이미지 파일 업로드 → 텍스트 변환 후 저장 |
| `/notice/upload-self` | POST | parent 본인 | 학부모 자가 업로드 (종이 통신문 사진 촬영 → OcrActivity → 서버 전송) |
| `/notice/inbox/{parent_id}` | GET | parent 본인 | 학부모 본인 수신함 조회 |
| `/notice/inbox/{parent_id}` | DELETE | parent 본인 | 본인 수신함 초기화 (시연용) |
| `/notice/analyze/{notice_id}` | POST | parent 본인 | body의 `target_language`(vi/en/ru/ms/mn/zh/th/ja/ko_easy)로 분석 결과 생성 |
| `/tts/generate` | POST | — | 텍스트 → 음성 파일 생성 (선택 언어별 Edge-TTS) |
| `/user/{id}` | GET | — | 사용자 프로파일 조회 |
| `/user/` | POST | — | 사용자 프로파일 저장 |
| `/health` | GET | — | 서버 상태 확인 |

> Swagger UI:
> - 배포 (NCP Seoul, 24/7): `http://YOUR_NCP_VM_IP:8000/docs` (실 IP는 팀 디스코 공유)
> - 로컬 개발: `http://localhost:8000/docs`

---

## 진도 현황

- [x] 태수: FastAPI 서버 + 다국어 분석 파이프라인(9개 언어) + X-User-Id 역할 인증 + Android UI 네이티브 재작성 + **NCP Seoul VM 실서버 배포 (101.79.17.196:8000)** + 원본 가정통신문 PDF/이미지 풀화면 표시 + FCM 푸시 알림
- [x] 윤정: KoELECTRA 추출 모델 — 학습 데이터 **47,148행** · 테스트 Recall **0.868** (v1 대비 +11.2%p) · HF Hub 배포
- [x] 경이: KcELECTRA v3 6분류 — 학습 데이터 **15,948행** · Macro F1 **0.8374** (Simple 베이스라인 0.7590 대비 +10.3%) · HF Hub 배포
- [x] 세종: NLLB + 글로사리 **340+ 항목**(9개 언어) + 용어 보존 검수 루프 + Edge-TTS 9보이스 + TTS 속도 조절 + STT 음성 질문(9언어×6카테고리) + 카메라 OCR (ML Kit + OpenCV) + **info_cards 파이프라인(준비물/비용/제출 체크리스트)** + **calendar_events(달력/미니달력 다국어)** + **미등록 용어 자동 감지 API**
- [x] 찬영: 가정통신문 **3,300장 이상** 수집(8개 초등학교) + 발표 자료
- [x] 팀 공통: E2E 파이프라인 실기기 검증 완료 + self_test **125+ ALL PASS** + Claude Haiku 4.5 sentence_list 정제 통합

---

## 정량 검증 현황

2026-04-28 기준, 강사 피드백에 맞춰 모델·번역 파이프라인의 주요 실험을 `OLD/docs/experiments/`에 정리했습니다.

| 항목 | 결과 | 문서 |
| --- | --- | --- |
| TODO 피처 추출 번역 속도 | 청크 보정 후 평균 ×1.84, 입력 -30.1% | `OLD/docs/experiments/2026-04-28-translation-feature-extraction-speed.md` |
| 용어사전 전/후 품질 | 엄격 재평가 NLLB 39.0점 → 사전 적용 89.6점 | `OLD/docs/experiments/2026-04-28-translation-glossary-quality.md` |
| Round-trip 의미 검증 | 18개 공지 A 50.1점 / B 54.1점, 반복 왜곡 유형 도출 | `docs/roundtrip-full-eval-2026-04-28.md` |
| 데이터/권한/사전 자동 테스트 | backend pytest 27개 + GitHub Actions PR 게이트 | `backend/tests/`, `.github/workflows/backend-tests.yml` |
| OCR 모델 비교 · 전처리 실험 | ML Kit Korean F1 0.95~0.97, CER 28.2% (정면 BEST) — EasyOCR·Tesseract 한국어 실패(CER 97%) | `OLD/docs/experiments/2026-05-01-ocr-mlkit-korean-results.md` |

번역 품질평가는 단순 용어 포함 여부가 아니라 현지 상용 표현, 학교 문맥, 정보 보존, 한국어 의미 역번역(Round-trip)을 함께 봅니다.

---

## 기술 스택

| 이름 | 기술 스택 |
| --- | --- |
| 태수 | FastAPI, Python 3.11, Pydantic, Uvicorn, Docker, NCP Seoul VM, FCM, REST API, X-User-Id 인증 |
| 윤정 | KoELECTRA-base-v3, HuggingFace Hub, PyTorch, Transformers (47,148행 학습) |
| 경이 | KcELECTRA v3, TF-IDF+LR 베이스라인, scikit-learn, HF Hub (15,948행 학습) |
| 세종 | facebook/nllb-200-distilled-600M, 글로사리 CSV 340+항목, Edge-TTS, ML Kit Korean OCR, OpenCV 4.9, Android SpeechRecognizer, Android TextToSpeech, Claude Haiku 4.5 (sentence_list 정제) |
| 찬영 | 가정통신문 3,300장 수집, 발표자료 |

---

## 로컬 실행

### 1. 서버 실행

```bash
git clone https://github.com/Maxmunzy/multicultural-ai.git
cd multicultural-ai
cp backend/.env.example backend/.env
docker-compose up --build
```

PC 브라우저에서 아래 주소가 열리는지 확인합니다.

```text
http://localhost:8000/docs
```

### 2. Android 실기기 실행

서버 BASE_URL 은 빌드 시점에 gradle 옵션으로 주입 (`BuildConfig.BASE_URL`).

```powershell
# 실서버 (NCP Seoul) — 실 IP는 팀 디스코 공유
./gradlew assembleDebug -Pschoolbridge.baseUrl=http://YOUR_NCP_VM_IP:8000

# 로컬 백엔드 — PC 내부 IP (ipconfig 로 확인)
./gradlew assembleDebug -Pschoolbridge.baseUrl=http://YOUR_PC_IP:8000

# 옵션 안 주면 emulator localhost (10.0.2.2:8000) 기본값
```

또는 `~/.gradle/gradle.properties` (사용자별, repo 외부) 에 `schoolbridge.baseUrl=http://...` 한 번 설정해 두면 매번 -P 안 줘도 됨.

설치:

1. Android 실기기의 USB 디버깅을 켭니다.
2. `adb install -r app/build/outputs/apk/debug/app-debug.apk`
3. 또는 Android Studio Run 버튼 (Studio 가 gradle.properties 의 값 사용)

로컬 백엔드 사용 시: PC와 휴대폰이 같은 Wi-Fi여야 하고, 휴대폰 브라우저에서 `http://PC_IP:8000/docs`가 열리는지 먼저 확인하세요.

주의: Android 실기기에서 `localhost`/`127.0.0.1`은 PC가 아니라 휴대폰 자기 자신을 의미합니다. 로컬 모드에선 반드시 PC의 내부 IP를 사용하세요.

---

## 데모 산출물

| 구분 | 위치 | 설명 |
| --- | --- | --- |
| 번역/TTS 고정 데모 | `demo/translation_tts/demo_case_01/` | 번역, 용어사전 검수, TTS 결과 샘플 |
| 번역/TTS 상세 설명 | `model/translation_tts/README.md` | 번역/TTS 실행 구조와 검수 루프 설명 |
| 실험 노트 인덱스 | `OLD/docs/experiments/README.md` | 모델·번역·데이터 정량 실험 모음 |
| 번역 품질 공유 요약 | `docs/share-summary-2026-04-28-quality-eval.md` | Gemini 평가 강화, 청크 번역, Round-trip 검사 요약 |
| Android 데모 | `android/` | 선생님/학부모 실기기 데모 앱 |
| 디자인 핸드오프 | `android/design_reference/` | UI 디자인 시안 HTML/CSS 산출물 — APK 빌드 미포함 |
| 이미지 자료 | `OLD/docs/assets/` | 발표/공유용 이미지 자료 |

---

## 브랜치 전략

```text
main         배포 가능한 안정 버전
dev          통합 개발 브랜치
feature/xxx  기능 단위 브랜치 (PR → dev)
```

---

## 주요 카테고리

| 카테고리 | 예시 키워드 |
| --- | --- |
| 일정 | 체험학습일, 소풍, 상담일, 시험, 운동회 |
| 준비물 | 색종이, 풀, 실내화, 체육복, 개인 물병 |
| 제출 | 동의서, 신청서, 확인서, 예방접종 서류 |
| 비용 | 체험학습비, 급식비, 방과후 수업비 |
| 건강·안전 | 독감 예방, 알레르기 조사, 안전교육 |

---

## Todo 라벨 초안 생성

JSONL 문장 데이터의 기존 `is_todo`를 `original_is_todo`로 보존하고, 사람이 검수할 수 있는 `draft_is_todo`, `reason`, `review_required` 초안을 생성합니다.

```bash
python scripts/prepare_todo_labels.py \
  --input_path data/raw/todo_raw.jsonl \
  --output_jsonl_path data/processed/todo_labeled_draft.jsonl \
  --output_csv_path data/processed/todo_labeled_draft.csv
```

Gemini API 키가 있으면 긴 원문을 먼저 의미 단위로 나눈 뒤 draft 라벨을 만들 수 있습니다. 실제 API 키는 `.env`에 넣고, `.env`는 GitHub에 올리지 않습니다. 공유용 샘플은 `.env.example`만 올립니다.

```bash
cp .env.example .env
```

`.env` 파일에 본인 Gemini API 키를 입력합니다.

```bash
python scripts/prepare_todo_labels.py \
  --input_path data/raw/todo_raw.jsonl \
  --output_jsonl_path data/processed/todo_labeled_draft.jsonl \
  --output_csv_path data/processed/todo_labeled_draft.csv \
  --use_gemini_segment
```

API 키가 없거나 Gemini 응답 파싱에 실패하면 기존 rule split으로 자동 fallback됩니다.

이 스크립트의 결과는 정답 라벨이 아니라 검수용 초안입니다. `review_required=true` 행을 먼저 확인한 뒤 최종 라벨을 확정하세요.
