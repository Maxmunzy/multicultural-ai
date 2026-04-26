# 트러블슈팅 및 제한사항

## 문서 목적

MVP 시연 중 자주 막히는 지점과 현재 구현상 제한사항을 정리합니다. 기준일은 2026-04-26이며, 현재 저장소 상태를 기준으로 작성했습니다.

---

## 빠른 점검 순서

1. Docker/FastAPI 서버 실행
2. PC 브라우저에서 `http://localhost:8000/docs` 확인
3. 같은 네트워크의 휴대폰 브라우저에서 `http://PC_IP:8000/docs` 확인
4. Android `MainActivity.java`의 `BASE_URL`이 PC IP와 같은지 확인
5. 선생님 화면에서 발송 후 학부모 화면에서 같은 `parent_id`로 수신함 조회
6. 분석 결과가 안 나오면 앱의 고정 데모 결과 보기로 fallback 확인

---

## 서버 실행 문제

### `docker-compose up --build` 후 `/docs`가 열리지 않음

확인할 것:

- Docker Desktop이 실행 중인지 확인
- 8000 포트를 다른 프로세스가 쓰고 있지 않은지 확인
- repo 루트에서 실행했는지 확인

```powershell
docker-compose up --build
```

정상 접속 주소:

```text
http://localhost:8000/docs
```

### Python 문법 오류가 발생함

현재 일부 한글 문자열이 깨진 파일이 있어 Python 문자열 리터럴 오류가 날 수 있습니다. 우선 확인할 파일:

- `backend/app/main.py`
- `backend/app/routers/tts.py`
- `backend/app/services/mock.py`
- `backend/app/models/schemas.py`
- `model/translation_tts/run_mvp_pipeline.py`

대응:

- 깨진 한글 문자열을 UTF-8 한국어 또는 ASCII 메시지로 복구
- `python -m py_compile`로 backend 파일을 먼저 점검
- 발표 시 급하면 Android 내장 데모 산출물 fallback으로 시연

---

## Android 연결 문제

### 휴대폰에서 서버 연결 실패

Android 실기기에서 `localhost`는 PC가 아니라 휴대폰 자기 자신입니다. `BASE_URL`에는 PC의 같은 네트워크 IP를 넣어야 합니다.

PC IP 확인:

```powershell
ipconfig
```

수정 위치:

```text
android/app/src/main/java/com/multicultural/demo/MainActivity.java
```

예시:

```java
private static final String BASE_URL = "http://192.168.0.23:8000";
```

휴대폰 브라우저에서 먼저 확인:

```text
http://192.168.0.23:8000/docs
```

### PC에서는 되는데 휴대폰에서는 안 됨

확인할 것:

- PC와 휴대폰이 같은 Wi-Fi인지 확인
- VPN, 핫스팟, 게스트 Wi-Fi가 분리망을 만들고 있지 않은지 확인
- Windows 방화벽에서 8000 포트 접근이 막히지 않았는지 확인
- Docker 컨테이너가 `0.0.0.0:8000`으로 노출되는지 확인

---

## 데이터/분석 문제

### 학부모 수신함이 비어 있음

가능한 원인:

- 선생님 화면에서 발송을 먼저 하지 않음
- 발송 시 `parent_id`와 학부모 수신함 조회 `parent_id`가 다름
- 서버가 재시작되어 임시 메모리 저장소가 비워짐

현재 backend는 DB가 아니라 프로세스 메모리에 가정통신문을 저장합니다. 서버를 재시작하면 이전 발송 데이터는 사라집니다.

### 분석 결과가 실제 모델 결과가 아님

정상입니다. 현재 `POST /notice/analyze/{notice_id}`는 `backend/app/services/mock.py`의 고정 `MOCK_TODOS`를 반환합니다. 추출/분류 모델 연결은 다음 단계입니다.

---

## 번역/TTS 문제

### TTS URL이 없는데도 앱에서 소리가 남

정상입니다. 서버가 TTS URL을 주지 않으면 Android 앱은 `android/app/src/main/res/raw/tts_output.mp3`에 포함된 고정 mp3를 재생합니다.

### 번역이 어색하거나 학교 용어가 빠짐

MVP의 중요한 관찰 지점입니다. NLLB 원번역은 자연스럽지 않거나 `도시락` 같은 핵심 용어를 놓칠 수 있습니다. 그래서 현재 번역/TTS 파트는 단순 번역만 보여 주지 않고 아래 산출물을 함께 둡니다.

- `02_vi_raw_translation.txt`: 원번역
- `03_glossary_check.csv`: 용어사전 검수 결과
- `04_review_needed.md`: 사람이 확인해야 할 항목
- `05_vi_corrected_translation.txt`: 보정 번역
- `06_tts_output.mp3`: 음성 출력

위 파일들은 `demo/translation_tts/demo_case_01/`에 있습니다.

---

## 현재 제한사항

| 제한사항 | 설명 |
| --- | --- |
| DB 없음 | 가정통신문은 서버 메모리에 저장되므로 재시작 시 사라짐 |
| 실제 추출/분류 모델 미연결 | 분석 API는 mock 응답 사용 |
| OCR 없음 | 이미지/PDF가 아니라 텍스트 입력 기준 |
| 실제 학교 시스템 연동 없음 | MVP에서는 앱 내부 발송/수신 흐름만 시연 |
| Android IP 수동 설정 | 네트워크가 바뀌면 `BASE_URL` 수정 필요 |
| 일부 파일 한글 깨짐 | 문서와 코드 일부가 인코딩 복구 필요 |

---

## 시연 전 최종 확인

- [ ] `docker-compose up --build` 실행
- [ ] PC에서 `http://localhost:8000/docs` 접속
- [ ] 휴대폰에서 `http://PC_IP:8000/docs` 접속
- [ ] `MainActivity.java`의 `BASE_URL` 확인
- [ ] 선생님 화면 발송 성공
- [ ] 학부모 화면 수신함 조회 성공
- [ ] 분석 결과 표시
- [ ] TTS 재생
- [ ] 서버 실패 상황에서도 고정 데모 결과 보기 동작
