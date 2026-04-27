# Android 실기기 데모

가정통신문 AI MVP를 실제 Android 기기에서 시연하기 위한 최소 앱입니다.
앱 안에서 번역/TTS 모델을 직접 실행하지 않고, FastAPI 서버에 API를 요청한 뒤 결과를 화면에 표시합니다.

## 포함된 기능

- 시작 화면: `선생님으로 시작`, `학부모로 시작`
- 선생님 화면: 제목, 본문, `parent_id` 입력 후 `POST /notice/send` 호출
- 학부모 화면: `GET /notice/inbox/{parent_id}`로 수신함 조회
- 분석 버튼: `POST /notice/analyze/{notice_id}` 호출
- 분석 결과 표시: 체크리스트, 쉬운 한국어, 베트남어 번역, glossary check, review_needed/missing_term
- TTS 재생: 서버의 TTS URL이 있으면 그 주소를 재생하고, 없으면 내장된 `demo_case_01` mp3를 재생

## 준비물

- Android Studio
- Android 실기기
- PC에서 실행 중인 Docker/FastAPI 서버
- PC와 휴대폰이 같은 Wi-Fi 또는 같은 네트워크에 연결되어 있을 것

## 1. 서버 먼저 실행

팀 repo 루트에서 FastAPI 서버를 켭니다.

```powershell
cd C:\Users\user\Desktop\project\TEAM\multicultural-ai
docker-compose up --build
```

PC 브라우저에서 확인합니다.

```text
http://localhost:8000/docs
```

## 2. PC 내부 IP 확인

Windows에서 아래 명령을 실행합니다.

```powershell
ipconfig
```

`Wi-Fi` 또는 `이더넷`의 IPv4 주소를 확인합니다. 예:

```text
192.168.0.23
```

휴대폰 브라우저에서 아래 주소가 열리면 Android 앱도 서버에 붙을 가능성이 높습니다.

```text
http://192.168.0.23:8000/docs
```

## 3. BASE_URL 수정

`android/app/src/main/java/com/multicultural/demo/MainActivity.java` 상단의 `BASE_URL`을 본인 PC IP로 바꿉니다.

```java
private static final String BASE_URL = "http://192.168.0.23:8000";
```

주의: Android 실기기에서 `localhost`나 `127.0.0.1`은 PC가 아니라 휴대폰 자기 자신입니다.

## 4. Android Studio에서 실행

1. Android Studio에서 `multicultural-ai/android/` 폴더를 엽니다.
2. Gradle Sync를 기다립니다.
3. Android 실기기를 USB 또는 무선 디버깅으로 연결합니다.
4. Run을 눌러 설치합니다.

## 5. 시연 순서

1. `선생님으로 시작`
2. `샘플 가정통신문 채우기`
3. `발송`
4. 발송 결과에 `notice_id`가 나오는지 확인
5. 시작 화면으로 돌아가 `학부모로 시작`
6. `수신함 불러오기`
7. 방금 보낸 가정통신문이 보이는지 확인
8. `분석하기`
9. 체크리스트, 번역, glossary check 결과 확인
10. `베트남어 TTS 재생`

## 오프라인 fallback

서버 연결이 실패하거나 TTS URL이 없을 때는 앱에 포함된 `demo_case_01` 산출물을 이용합니다.

- 샘플 텍스트: `app/src/main/assets/demo_case_01/`
- 내장 TTS: `app/src/main/res/raw/tts_output.mp3`

이 fallback은 성공한 척하기 위한 기능이 아니라, 실기기 시연 중 서버/API가 불안정해도 MVP 흐름을 완전히 보여주기 위한 안전장치입니다.

## 트러블슈팅

- 휴대폰에서 `/docs`가 안 열림: 같은 Wi-Fi인지, Windows 방화벽, Docker 포트 `8000` 공개 확인
- 앱에서 서버 연결 실패: `BASE_URL`이 휴대폰 브라우저에서 열린 IP와 같은지 확인
- 수신함이 비어 있음: 먼저 선생님 화면에서 발송했는지, `parent_id`가 같은지 확인
- TTS URL이 없음: 정상입니다. 현재는 내장 `tts_output.mp3`로 fallback 재생합니다.
