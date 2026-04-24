# 가정통신문 AI 도우미 — 베트남 결혼이민 학부모용

> 학교에서 온 가정통신문에서 "엄마가 오늘·내일 해야 할 일"만 뽑아 체크리스트로 정리하고,
> 한국어 수준에 맞춰 **베트남어 또는 한국어 음성**으로 안내하는 개인화 TTS 서비스

---

## 팀 역할 분담

| 이름 | 담당 | 폴더 |
| --- | --- | --- |
| 태수 | FastAPI 서버 · API 설계 · 모델 연결 · Android 통신 | `backend/` |
| (2) | 가정통신문 → 할 일 문장 추출 (baseline + 파인튜닝) | `ml/extraction/` |
| (3) | 추출 문장 → 카테고리 분류 + 중요도 점수 | `ml/classification/` |
| 세종 | Edge-TTS · 번역 API · 데이터 수집·라벨링 | `tts/` · `translation/` · `data/` |
| 찬영 | Android 데모 앱 UI · 시연 시나리오 · 발표자료 | `android/` · `docs/` |

---

## 서비스 흐름

```text
[Android 앱]
    │ 가정통신문 텍스트 입력
    ▼
POST /notice/analyze
    │ 할 일 추출 → 카테고리 분류 → 베트남어 번역
    ▼
POST /tts/generate
    │ 난이도별 음성 생성 (초급: 베트남어 / 중급: 한국어)
    ▼
[Android 앱]
    체크리스트 표시 + 음성 재생
```

---

## API 목록

| 엔드포인트 | 메서드 | 설명 |
| --- | --- | --- |
| `/notice/analyze` | POST | 가정통신문 텍스트 → 할 일 체크리스트 |
| `/tts/generate` | POST | 체크리스트 → 음성 파일 |
| `/user/{id}` | GET | 사용자 프로파일 조회 |
| `/user/` | POST | 사용자 프로파일 저장 |
| `/health` | GET | 서버 상태 확인 |

> Swagger UI: `http://localhost:8000/docs`

---

## 진도 현황

- [x] 태수: FastAPI 서버 뼈대
- [ ] (2): 할 일 추출 모델
- [ ] (3): 카테고리 분류 모델
- [ ] (4): TTS / 번역 연결
- [ ] (5): Android 앱 UI

---

## 기술 스택

```text
Backend   : FastAPI + Python 3.11
ML        : HuggingFace Transformers (KoELECTRA / mBERT 파인튜닝)
TTS       : Edge-TTS (vi-VN / ko-KR)
번역      : DeepL API / Papago API
Android   : Kotlin + Retrofit2 + Jetpack Compose
DB        : SQLite (로컬 프로파일)
```

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
