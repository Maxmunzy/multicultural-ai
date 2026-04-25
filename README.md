# 가정통신문 AI 도우미 — 베트남 결혼이민 학부모용

> 학교에서 온 가정통신문에서 "엄마가 오늘·내일 해야 할 일"만 뽑아 체크리스트로 정리하고,
> 한국어 수준에 맞춰 **베트남어 또는 한국어 음성**으로 안내하는 개인화 TTS 서비스

---

## 팀 역할 분담

| 이름 | 담당 | 폴더 |
| --- | --- | --- |
| 태수 | FastAPI 서버 · API 설계 · 모델 연결 · Android 통신 | `backend/` |
| 윤정 | 가정통신문 → 할 일 문장 추출 모델 (파인튜닝) | `model/extraction/` |
| 경이 | 추출 문장 → 카테고리 분류 + 중요도 모델 | `model/classification/` |
| 세종 | NLLB 번역 모델 + MMS-TTS + 데이터 수집·라벨링 | `data/` |
| 찬영 | Android 데모 앱 UI · 시연 시나리오 · 발표자료 | `android/` · `docs/` |

---

## 서비스 흐름

```text
[선생님 디바이스]
    │ 가정통신문 작성 → 발송
    ▼ POST /notice/send
[서버]
    │ 저장
    ▼
[부모 디바이스]
    │ 수신함 확인 → GET /notice/inbox/{parent_id}
    ▼ POST /notice/analyze/{notice_id}
[서버]
    │ 할 일 추출 → 카테고리 분류 → 베트남어 번역
    ▼ POST /tts/generate
[부모 디바이스]
    체크리스트 표시 + 음성 재생
```

---

## API 목록

| 엔드포인트 | 메서드 | 설명 |
| --- | --- | --- |
| `/notice/send` | POST | 선생님 → 부모 가정통신문 발송 |
| `/notice/inbox/{parent_id}` | GET | 부모 수신함 조회 |
| `/notice/analyze/{notice_id}` | POST | 가정통신문 → 할 일 체크리스트 |
| `/tts/generate` | POST | 체크리스트 → 음성 파일 |
| `/user/{id}` | GET | 사용자 프로파일 조회 |
| `/user/` | POST | 사용자 프로파일 저장 |
| `/health` | GET | 서버 상태 확인 |

> Swagger UI: `http://localhost:8000/docs`

---

## 진도 현황

- [x] 태수: FastAPI 서버 뼈대
- [ ] 윤정: 할 일 추출 모델
- [ ] 경이: 카테고리 분류 모델
- [ ] 세종: NLLB 번역 + MMS-TTS 연결
- [ ] 찬영: Android 앱 UI

---

## 기술 스택

> 각자 본인이 사용한 기술로 업데이트해주세요

| 이름 | 기술 스택 |
| --- | --- |
| 태수 | FastAPI, Python 3.11, Pydantic, Uvicorn, Docker, docker-compose |
| 윤정 | (작성 예정) |
| 경이 | (작성 예정) |
| 세종 | facebook/nllb-200-distilled-600M, facebook/mms-tts-vie, (작성 예정) |
| 찬영 | (작성 예정) |

---

## 로컬 실행

```bash
git clone https://github.com/Maxmunzy/multicultural-ai.git
cd multicultural-ai
cp backend/.env.example backend/.env
docker-compose up --build
```

> 접속: [http://localhost:8000/docs](http://localhost:8000/docs)

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
