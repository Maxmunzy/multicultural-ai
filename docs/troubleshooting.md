# 트러블슈팅 및 제한사항

## 문서 목적

MVP 시연 중 자주 막히는 지점과 현재 구현상 제한사항을 정리합니다. 기준일은 2026-04-27이며, 현재 저장소 상태를 기준으로 작성했습니다.

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

### 분석 결과가 실제 모델 결과가 아님 (해결됨)

`POST /notice/analyze/{notice_id}`는 실제 모델 파이프라인과 연결되어 있습니다.

- 모델 A (추출): `backend/app/services/extractor.py` → `extract_todos()`
- 모델 B (분류 교차검증): `backend/app/services/classifier.py` → `review_todos()`
- 번역/TTS: `backend/app/services/translator.py` + `tts.py`

결과가 고정 샘플처럼 보이는 경우: 추출 모델이 해당 텍스트에서 항목을 뽑지 못하면 `MOCK_TODOS`로 fallback됩니다. 실제 가정통신문 형식의 텍스트로 테스트하세요.

### NLLB 첫 실행이 너무 오래 걸림

첫 실행 시 HuggingFace Hub에서 모델(약 2.4GB)을 다운로드합니다. 10~15분 소요될 수 있습니다. 이후 `hf_cache` 볼륨에 캐시되어 재시작 시 빠르게 로드됩니다.

시연 전 warmup 필수:

```bash
curl -s -X POST http://localhost:8000/notice/send \
  -H "Content-Type: application/json" \
  -d '{"teacher_id":"t1","parent_id":"p1","text":"6월 12일 수요일에 학부모 공개수업이 진행됩니다."}' | python -m json.tool
```

send 후 반환된 `notice_id`로 analyze 한 번 호출하면 모델이 메모리에 로드됩니다.

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
| 모델 A·B 백엔드 미연결 | 모델은 구현 완료. 메인 백엔드 `/notice/analyze`는 아직 mock 응답 사용 |
| OCR 없음 | 이미지/PDF가 아니라 텍스트 입력 기준 |
| 실제 학교 시스템 연동 없음 | MVP에서는 앱 내부 발송/수신 흐름만 시연 |
| Android IP 수동 설정 | 네트워크가 바뀌면 `BASE_URL` 수정 필요 |

---

## 설계 결정

### 왜 알림장 앱 전체가 아니라 AI 도우미 모듈인가

이번 MVP의 목표는 새 알림장 서비스를 완성하는 것이 아니라, 기존 학교 알림장이나 가정통신문 서비스가 가져다 쓸 수 있는 AI 기능을 검증하는 것입니다.

따라서 Android 앱은 최종 제품이라기보다 실기기에서 흐름을 보여 주는 데모 클라이언트입니다. 핵심 기능은 서버 API와 모델 파이프라인입니다.

```text
기존 학교 앱/알림장 서비스
  -> 우리 FastAPI 서버 호출
  -> 체크리스트, 쉬운 한국어, 베트남어 번역, TTS 결과 수신
  -> 기존 앱 화면에 표시
```

### 왜 OCR은 이번 MVP에서 제외했나

OCR은 이미지나 PDF에서 글자를 읽어 오는 별도 문제입니다. 이번 MVP에서는 OCR까지 넣으면 입력 품질, 이미지 촬영 환경, 문서 레이아웃 처리 문제가 함께 들어와서 핵심 검증 범위가 흐려질 수 있습니다.

그래서 현재는 텍스트 가정통신문을 입력으로 고정하고, 아래 흐름을 먼저 검증합니다.

- 선생님이 텍스트 가정통신문을 발송한다.
- 학부모가 수신함에서 확인한다.
- 서버가 체크리스트/번역/검수/TTS 결과를 만든다.
- Android 실기기에서 결과와 음성을 확인한다.

OCR은 이후 단계에서 앞단 입력 모듈로 붙일 수 있습니다. 즉 OCR을 뺀 것은 기능 포기가 아니라, MVP에서 검증할 핵심을 `텍스트 이해 -> 번역/검수 -> 음성 안내`로 좁힌 설계 결정입니다.

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
