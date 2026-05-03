# Android 실기기 데모 실행 가이드

가정통신문 AI MVP를 Android 실기기에서 테스트하기 위한 안내입니다. Android 앱은 모델을 직접 실행하지 않고, PC에서 실행 중인 Docker/FastAPI 서버에 요청을 보내 결과를 화면에 표시합니다.

## 포함 기능

- 시작 화면: 선생님 / 학부모 모드 선택
- 선생님 화면: 가정통신문 작성 후 `POST /notice/send` / HWP·PDF 파일 업로드 `POST /notice/upload`
- 학부모 화면: `GET /notice/inbox/{parent_id}`로 수신함 조회
- **학부모 홈 카메라 OCR**: 종이 통신문 촬영 → ML Kit Korean (4종 전처리 + 2-pass 표 재인식) → Quality Gate(0.80) → `POST /notice/upload-self`
- 분석 버튼: `POST /notice/analyze/{notice_id}`
- 분석 결과 표시: 해야 할 일, 쉬운 한국어, 선택 언어 번역(9개국어), 용어 검수 결과
- TTS 재생: 서버 TTS URL이 있으면 해당 파일 재생, 없으면 앱 내장 mp3 재생

## 준비물

- Android Studio
- Android 실기기
- PC에서 실행 중인 Docker/FastAPI 서버
- PC와 Android 기기가 같은 Wi-Fi 또는 같은 네트워크에 연결된 상태

## 1. 서버 실행

repo 루트에서 FastAPI 서버를 실행합니다.

```powershell
docker compose up --build
```

PC 브라우저에서 먼저 확인합니다.

```text
http://localhost:8000/docs
```

## 2. PC IP 확인

Windows PowerShell에서 실행합니다.

```powershell
ipconfig
```

`Wi-Fi` 또는 현재 사용 중인 네트워크 어댑터의 IPv4 주소를 확인합니다.

예시:

```text
192.168.0.23
```

Android 기기 브라우저에서 아래 주소가 열리는지 확인합니다.

```text
http://192.168.0.23:8000/docs
```

여기서 열리지 않으면 앱에서도 서버에 연결할 수 없습니다.

## 3. BASE_URL 수정 위치

각자 PC IP에 맞게 아래 파일의 `BASE_URL`만 수정합니다.

```text
android/app/src/main/java/com/multicultural/demo/MainActivity.java
```

수정 예시:

```java
private static final String BASE_URL = "http://192.168.0.23:8000";
```

주의: Android 실기기에서 `localhost` 또는 `127.0.0.1`은 PC가 아니라 휴대폰 자기 자신을 의미합니다. 반드시 PC의 IPv4 주소를 넣어야 합니다.

## 4. Android Studio 실행

1. Android Studio에서 `multicultural-ai/android/` 폴더를 엽니다.
2. Gradle Sync가 끝날 때까지 기다립니다.
3. Android 실기기를 USB 또는 무선 디버깅으로 연결합니다.
4. Run 버튼을 눌러 앱을 설치합니다.

## 5. 테스트 순서

1. `선생님으로 시작`
2. `샘플 가정통신문 채우기`
3. `발송`
4. `notice_id`가 표시되는지 확인
5. 처음 화면으로 돌아가서 `학부모로 시작`
6. `수신함 불러오기`
7. 방금 보낸 가정통신문이 보이는지 확인
8. `분석하기`
9. 해야 할 일, 쉬운 한국어, 베트남어 번역, 용어 검수 결과 확인
10. `베트남어로 듣기`

## 문제 해결

| 문제 | 확인할 것 |
| --- | --- |
| 폰에서 `/docs`가 안 열림 | PC와 폰이 같은 Wi-Fi인지, Windows 방화벽이 8000 포트를 막지 않는지 확인 |
| 앱에서 서버 연결 실패 | `BASE_URL`이 폰 브라우저에서 열리는 주소와 같은지 확인 |
| 수신함이 비어 있음 | 선생님 화면에서 먼저 발송했는지, `parent_id`가 같은지 확인 |
| 예전 결과가 보임 | 새 가정통신문을 다시 발송하고 수신함을 다시 불러오기 |
| TTS URL이 없음 | 서버 TTS 실패 시 앱 내장 mp3로 fallback 재생될 수 있음 |

## 커밋 주의

`MainActivity.java`의 `BASE_URL`은 각자 PC IP에 맞춘 로컬 테스트 값입니다. 개인 IP만 바꾼 변경은 팀원 환경을 깨뜨릴 수 있으므로 보통 커밋하지 않습니다.
