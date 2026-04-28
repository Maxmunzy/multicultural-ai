# 가정통신문 AI 도우미 - 다문화 가정 학부모용

> 학교에서 온 가정통신문에서 "엄마가 오늘·내일 해야 할 일"을 뽑아 체크리스트로 정리하고,
> 쉬운 한국어 + 8개국어(베트남어/영어/러시아어/말레이시아어/몽골어/중국어/태국어/일본어) 번역과 음성 안내까지 제공하는 탑재형 AI 모듈 & TTS 서비스

---

## 팀 역할 분담

| 이름 | 담당 | 폴더 |
| --- | --- | --- |
| 태수 | FastAPI 서버, API 설계, 모델 연결, Android 통신 | `backend/` |
| 윤정 | 가정통신문에서 할 일 문장 추출 모델 | `model/extraction/` |
| 경이 | 추출 문장 카테고리 분류 및 중요도 모델 | `model/classification/` |
| 세종 | 베트남어 번역, 학교 용어사전, 번역 검수 루프, TTS 출력 | `model/translation_tts/` · `data/translation_tts/` · `demo/translation_tts/` |
| 찬영 | Android 데모 앱 UI, 실기기 시연 흐름, 발표자료 | `android/` · `docs/` |

---

## 서비스 흐름

```text
[선생님 Android 앱]  (X-User-Id: teacher_xxx)
    │ 가정통신문 제목/본문 + parent_id 작성
    ▼ POST /notice/send
[FastAPI 서버]
    │ 권한 검증 (teacher 역할 + body.teacher_id 일치)
    │ 가정통신문 저장
    ▼
[학부모 Android 앱]  (X-User-Id: parent_xxx)
    │ 본인 수신함 조회
    ▼ GET /notice/inbox/{parent_id}
[학부모 Android 앱]
    │ 통신문 상세 → 우측 상단 ✨ AI 번역 버튼
    ▼ POST /notice/analyze/{notice_id}  (target_language)
[FastAPI 서버 + 모델 파이프라인]
    │ 할 일 추출(윤정) → 카테고리 분류·중요도 검수(경이)
    │ → 쉬운 한국어 + 선택 언어 번역(세종 NLLB)
    │ → 학교 용어사전 검수 → 선택 언어 Edge-TTS 음성 생성
    ▼
[학부모 Android 앱]
    체크리스트 + 쉬운 한국어 + 모국어 번역(9개 중 선택) + 음성 재생
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
| `/notice/inbox/{parent_id}` | GET | parent 본인 | 학부모 본인 수신함 조회 |
| `/notice/inbox/{parent_id}` | DELETE | parent 본인 | 본인 수신함 초기화 (시연용) |
| `/notice/analyze/{notice_id}` | POST | parent 본인 | body의 `target_language`(vi/en/ru/ms/mn/zh/th/ja/ko_easy)로 분석 결과 생성 |
| `/tts/generate` | POST | — | 텍스트 → 음성 파일 생성 (선택 언어별 Edge-TTS) |
| `/user/{id}` | GET | — | 사용자 프로파일 조회 |
| `/user/` | POST | — | 사용자 프로파일 저장 |
| `/health` | GET | — | 서버 상태 확인 |

> Swagger UI: `http://localhost:8000/docs`

---

## 진도 현황

- [x] 태수: FastAPI 서버 + 다국어 분석 파이프라인(9개 언어) + X-User-Id 역할 인증 + Android UI 네이티브 재작성
- [x] 윤정: KoELECTRA 하이브리드 추출 모델 구현 + HuggingFace Hub 배포
- [x] 경이: 6개 카테고리 분류 + 중요도 모델 구현 (accuracy 0.857, MAE 0.038) + API 서버
- [x] 세종: NLLB 다국어 번역(8개 언어) + 용어사전 검수 루프 + Edge-TTS 음성 출력 (언어별 보이스 매핑)
- [x] 찬영: Android 선생님/학부모 화면 및 실기기 데모 1차 구현
- [x] 팀 공통: 모델 A·B·C 백엔드 연결 및 E2E 파이프라인 실기기 검증 완료

---

## 정량 검증 현황

2026-04-28 기준, 강사 피드백에 맞춰 모델·번역 파이프라인의 주요 실험을 `docs/experiments/`에 정리했습니다.

| 항목 | 결과 | 문서 |
| --- | --- | --- |
| KoELECTRA 베이스 vs 파인튜닝 | accuracy 0.17 → 0.75, macro F1 0.07 → 0.60 | `docs/experiments/2026-04-28-extraction-base-vs-finetune.md` |
| TODO 피처 추출 번역 속도 | 청크 보정 후 평균 ×1.84, 입력 -30.1% | `docs/experiments/2026-04-28-translation-feature-extraction-speed.md` |
| 용어사전 전/후 품질 | 엄격 재평가 NLLB 39.0점 → 사전 적용 89.6점 | `docs/experiments/2026-04-28-translation-glossary-quality.md` |
| Round-trip 의미 검증 | 18개 공지 A 50.1점 / B 54.1점, 반복 왜곡 유형 도출 | `docs/roundtrip-full-eval-2026-04-28.md` |
| 데이터/권한/사전 자동 테스트 | backend pytest 27개 + GitHub Actions PR 게이트 | `backend/tests/`, `.github/workflows/backend-tests.yml` |

번역 품질평가는 단순 용어 포함 여부가 아니라 현지 상용 표현, 학교 문맥, 정보 보존, 한국어 의미 역번역(Round-trip)을 함께 봅니다.

---

## 기술 스택

| 이름 | 기술 스택 |
| --- | --- |
| 태수 | FastAPI, Python 3.11, Pydantic, Uvicorn, Docker, docker-compose, REST API, X-User-Id 헤더 인증 |
| 윤정 | KoELECTRA-base-v3, HuggingFace Hub, PyTorch, Regex, Transformers |
| 경이 | numpy TF-IDF, scikit-learn LR, SBERT + LightGBM, Ridge 회귀, FastAPI |
| 세종 | Python, Hugging Face Transformers, facebook/nllb-200-distilled-600M, Pandas/CSV, Edge-TTS, 학교 용어사전, fallback 처리 |
| 찬영 | Android Studio, Java, Android SDK, HttpURLConnection, JSONObject, MediaPlayer |

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

1. Android Studio에서 `android/` 폴더를 엽니다.
1. Android 실기기의 USB 디버깅을 켭니다.
1. PC와 휴대폰을 같은 Wi-Fi 또는 같은 네트워크에 연결합니다.
1. Windows에서 `ipconfig`로 PC 내부 IP를 확인합니다.
1. `android/app/src/main/java/com/multicultural/demo/MainActivity.java` 상단의 `BASE_URL`을 PC 내부 IP로 수정합니다.

   ```java
   private static final String BASE_URL = "http://192.168.x.x:8000";
   ```

1. 휴대폰 브라우저에서 아래 주소가 열리는지 확인합니다.

   ```text
   http://PC_IP:8000/docs
   ```

1. Android Studio에서 Run 버튼을 눌러 실기기에 설치합니다.

주의: Android 실기기에서 `localhost`나 `127.0.0.1`은 PC가 아니라 휴대폰 자기 자신을 의미합니다.  
반드시 Docker/FastAPI 서버가 실행 중인 PC의 내부 IP를 사용해야 합니다.

---

## 데모 산출물

| 구분 | 위치 | 설명 |
| --- | --- | --- |
| 번역/TTS 고정 데모 | `demo/translation_tts/demo_case_01/` | 번역, 용어사전 검수, TTS 결과 샘플 |
| 번역/TTS 상세 설명 | `model/translation_tts/README.md` | 번역/TTS 실행 구조와 검수 루프 설명 |
| 실험 노트 인덱스 | `docs/experiments/README.md` | 모델·번역·데이터 정량 실험 모음 |
| 번역 품질 공유 요약 | `docs/share-summary-2026-04-28-quality-eval.md` | Gemini 평가 강화, 청크 번역, Round-trip 검사 요약 |
| Android 데모 | `android/` | 선생님/학부모 실기기 데모 앱 |
| 디자인 핸드오프 | `android/design_reference/` | UI 디자인 시안 HTML/CSS 산출물 — APK 빌드 미포함 |
| 이미지 자료 | `docs/assets/` | 발표/공유용 이미지 자료 |

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
