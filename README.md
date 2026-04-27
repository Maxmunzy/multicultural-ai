# 가정통신문 AI 도우미 - 베트남 결혼이민 학부모용

> 학교에서 온 가정통신문에서 "엄마가 오늘·내일 해야 할 일"을 뽑아 체크리스트로 정리하고,
> 쉬운 한국어와 베트남어 번역, 음성 안내까지 제공하는 개인화 TTS 서비스

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
[선생님 Android 앱]
    │ 가정통신문 제목/본문 작성
    ▼ POST /notice/send
[FastAPI 서버]
    │ 가정통신문 저장
    ▼
[학부모 Android 앱]
    │ 수신함 조회
    ▼ GET /notice/inbox/{parent_id}
[학부모 Android 앱]
    │ 선택한 가정통신문 분석 요청
    ▼ POST /notice/analyze/{notice_id}
[FastAPI 서버 + 모델 파이프라인]
    │ 할 일 추출 → 카테고리 분류 → 쉬운 한국어 → 베트남어 번역 → 용어사전 검수 → TTS 생성
    ▼
[학부모 Android 앱]
    체크리스트 + 쉬운 한국어 + 베트남어 번역 + 음성 재생
```

Android 앱은 모델을 직접 실행하지 않습니다.  
앱은 FastAPI 서버에 요청을 보내고, 서버와 모델 파이프라인이 만든 결과를 화면에 보여주는 역할을 합니다.

---

## API 목록

| 엔드포인트 | 메서드 | 설명 |
| --- | --- | --- |
| `/notice/send` | POST | 선생님이 학부모에게 가정통신문 발송 |
| `/notice/inbox/{parent_id}` | GET | 학부모 수신함 조회 |
| `/notice/analyze/{notice_id}` | POST | 가정통신문 → 체크리스트/쉬운 한국어/번역/검수 결과 생성 |
| `/tts/generate` | POST | 분석 결과 또는 번역문 → 음성 파일 생성 |
| `/user/{id}` | GET | 사용자 프로파일 조회 |
| `/user/` | POST | 사용자 프로파일 저장 |
| `/health` | GET | 서버 상태 확인 |

> Swagger UI: `http://localhost:8000/docs`

---

## 진도 현황

- [x] 태수: FastAPI 서버 뼈대 및 Android API 통신 흐름 1차 연결
- [x] 윤정: KoELECTRA 하이브리드 추출 모델 구현 + HuggingFace Hub 배포
- [x] 경이: 6개 카테고리 분류 + 중요도 모델 구현 (accuracy 0.857, MAE 0.038) + API 서버
- [x] 세종: NLLB 베이스라인 번역 + 용어사전 검수 루프 + Edge-TTS 음성 출력 1차 MVP 실행 성공
- [x] 찬영: Android 선생님/학부모 화면 및 실기기 데모 1차 구현
- [ ] 팀 공통: 모델 A·B 백엔드 연결 및 최종 E2E 검증

---

## 기술 스택

| 이름 | 기술 스택 |
| --- | --- |
| 태수 | FastAPI, Python 3.11, Pydantic, Uvicorn, Docker, docker-compose, REST API |
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
2. Android 실기기의 USB 디버깅을 켭니다.
3. PC와 휴대폰을 같은 Wi-Fi 또는 같은 네트워크에 연결합니다.
4. Windows에서 `ipconfig`로 PC 내부 IP를 확인합니다.
5. `android/app/src/main/java/com/multicultural/demo/MainActivity.java` 상단의 `BASE_URL`을 PC 내부 IP로 수정합니다.

```java
private static final String BASE_URL = "http://192.168.x.x:8000";
```

6. 휴대폰 브라우저에서 아래 주소가 열리는지 확인합니다.

```text
http://PC_IP:8000/docs
```

7. Android Studio에서 Run 버튼을 눌러 실기기에 설치합니다.

주의: Android 실기기에서 `localhost`나 `127.0.0.1`은 PC가 아니라 휴대폰 자기 자신을 의미합니다.  
반드시 Docker/FastAPI 서버가 실행 중인 PC의 내부 IP를 사용해야 합니다.

---

## 데모 산출물

| 구분 | 위치 | 설명 |
| --- | --- | --- |
| 번역/TTS 고정 데모 | `demo/translation_tts/demo_case_01/` | 번역, 용어사전 검수, TTS 결과 샘플 |
| 번역/TTS 상세 설명 | `model/translation_tts/README.md` | 번역/TTS 실행 구조와 검수 루프 설명 |
| Android 데모 | `android/` | 선생님/학부모 실기기 데모 앱 |
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
