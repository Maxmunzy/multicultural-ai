# Android 실기기 데모 실행 가이드

가정통신문 AI MVP를 Android 실기기에서 테스트하기 위한 안내입니다. Android 앱은 모델을 직접 실행하지 않고, **NCP Seoul VM에 배포된 FastAPI 서버** 또는 로컬 Docker 서버에 요청을 보내 결과를 화면에 표시합니다.

**서버 IP/주소는 빌드 시점에 주입** — 코드/repo에 박혀 있지 않습니다 (보안 + 환경별 분리).

## 포함 기능

- 시작 화면: 선생님 / 학부모 모드 선택
- 선생님 화면: 가정통신문 작성 후 `POST /notice/send` / HWP·PDF·이미지 파일 업로드 `POST /notice/upload`
- 학부모 화면: `GET /notice/inbox/{parent_id}`로 수신함 조회 (카드 리스트)
- **학부모 카드 클릭 → 원본 가정통신문 풀화면 표시** — PDF는 페이지 네비, 이미지는 그대로 표시 (텍스트 직송 케이스는 텍스트 fallback)
- **학부모 홈 카메라 OCR**: 종이 통신문 촬영 → ML Kit Korean (4종 전처리 + 2-pass 표 재인식) → Quality Gate(0.80) → `POST /notice/upload-self`
- ✨ AI 분석 버튼 (원본 화면 우상단): `POST /notice/analyze/{notice_id}`
- 분석 결과 표시: 해야 할 일, 쉬운 한국어, 선택 언어 번역(9개국어), 용어 검수 결과
- **TTS 재생 속도 조절**: 단어별(0.5×) / 천천히(0.75×) / 오리지날(1.0×) 토글 — 선택 언어로 자동 표시
- **STT 음성 질문**: 마이크 버튼 → 음성 인식 → 카테고리 매칭 → TTS 답변 (온디바이스, 서버 불필요)
  - 앱에서 "이렇게 말해보세요" 팁 제시 → 팁 문장 그대로 말하면 매칭
  - 9개 언어 × 6개 카테고리 (주제/준비물/일정/비용/제출/건강)
  - `vi_demo` (시연용): 한국어 팁 + 한국어 STT / `vi` (실사용): 베트남어 팁 + 베트남어 STT
- TTS 재생: 서버 TTS URL이 있으면 해당 파일 재생, 없으면 앱 내장 mp3 재생

## 준비물

- Android Studio
- Android 실기기
- PC에서 실행 중인 Docker/FastAPI 서버
- PC와 Android 기기가 같은 Wi-Fi 또는 같은 네트워크에 연결된 상태

## 1. 서버 BASE_URL 주입

`MainActivity.java` 의 `BASE_URL` 은 `BuildConfig.BASE_URL` 로 분리. 빌드 시점에 gradle 옵션으로 주입.

빌드 명령:

```powershell
# NCP 실서버 시연용
./gradlew assembleDebug -Pschoolbridge.baseUrl=http://YOUR_NCP_VM_IP:8000

# 로컬 Docker 사용 시
./gradlew assembleDebug -Pschoolbridge.baseUrl=http://YOUR_PC_IP:8000

# 옵션 안 주면 emulator localhost (10.0.2.2:8000) 기본값
./gradlew assembleDebug
```

또는 `~/.gradle/gradle.properties` (사용자별, repo 외부) 에 `schoolbridge.baseUrl=http://...:8000` 설정해 두면 매번 -P 안 줘도 됨.

브라우저에서 헬스 체크: `http://YOUR_SERVER:8000/health` → `{"status":"ok"}` 응답이면 OK.

NCP 는 항상 켜져 있어 콜드스타트 없음 (~70ms 응답). 다만 **첫 분석 호출 시 NLLB ~2.4GB 다운로드로 5-10분 소요** — 시연 직전 한 번 워밍업 필수.

## 2. (옵션) 로컬 백엔드 사용

로컬 Docker로 테스트하고 싶을 때만:

```powershell
docker compose up --build
ipconfig  # PC 내부 IP 확인 (예: 192.168.0.23)
```

빌드 시 `-P` 옵션으로 PC IP 주입 (`MainActivity.java` 직접 수정 금지 — `BASE_URL`은 `BuildConfig`로 분리됨):

```powershell
./gradlew clean assembleDebug -Pschoolbridge.baseUrl=http://192.168.0.23:8000
```

휴대폰 브라우저에서 `http://192.168.0.23:8000/docs` 열리는지 먼저 확인. 안 열리면 PC와 휴대폰이 같은 Wi-Fi인지, Windows 방화벽이 8000 포트를 막지 않는지 확인.

주의: Android 실기기에서 `localhost`/`127.0.0.1`은 PC가 아니라 휴대폰 자기 자신을 의미합니다. 로컬 모드에선 반드시 PC IPv4 주소를 사용하세요.

## 3. clean 빌드가 필요한 경우

다음 상황에서는 반드시 **`clean`** 을 포함해 빌드해야 합니다:

- `-Pschoolbridge.baseUrl` 값(서버 IP)을 바꿀 때
- `drawable/` 에 새 이미지 파일을 추가했을 때
- Java 코드 변경이 반영되지 않는 것 같을 때

`clean` 없이 하면 이전 캐시가 남아 변경사항이 적용되지 않을 수 있습니다.

```powershell
# NCP 실서버로 전환
./gradlew clean assembleDebug "-Pschoolbridge.baseUrl=http://YOUR_NCP_VM_IP:8000"

# 빌드 직후 BuildConfig 확인 (값이 맞는지 검증)
Select-String -Path "app\build\generated\source\buildConfig\debug\com\multicultural\demo\BuildConfig.java" -Pattern "BASE_URL"
```

`clean` 없이 `assembleDebug`만 치면 이전 URL이 그대로 남아 서버 연결이 안 될 수 있습니다.

## 4. APK 설치 (adb 직접 설치)

Android Studio 없이 adb로 바로 설치하려면:

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r -t "app\build\outputs\apk\debug\app-debug.apk"
```

## 5. Android Studio 실행

1. Android Studio에서 `multicultural-ai/android/` 폴더를 엽니다.
2. Gradle Sync가 끝날 때까지 기다립니다.
3. Android 실기기를 USB 또는 무선 디버깅으로 연결합니다.
4. Run 버튼을 눌러 앱을 설치합니다.

## 6. 테스트 순서

1. `선생님으로 시작`
2. `샘플 가정통신문 채우기` 또는 **HWP/PDF/사진 파일 업로드** (`POST /notice/upload`)
3. `발송`
4. `notice_id`가 표시되는지 확인
5. 처음 화면으로 돌아가서 `학부모로 시작`
6. `수신함 불러오기` — 가정통신문 카드 리스트
7. **카드 클릭** → 원본 PDF/이미지 풀화면 표시 (텍스트 직송 케이스는 텍스트 본문)
8. **우상단 ✨ AI 버튼** → 분석 결과 화면
9. 해야 할 일, 쉬운 한국어, 베트남어 번역, 용어 검수 결과 확인
10. `베트남어로 듣기`
11. TTS 재생 중 속도 버튼(단어별 / 천천히 / 오리지날) 전환 확인
12. 마이크 버튼 누른 뒤 팁에 있는 문장 말하기 → TTS로 답변 확인

## 7. 문제 해결

| 문제 | 확인할 것 |
| --- | --- |
| 폰에서 `/docs`가 안 열림 | PC와 폰이 같은 Wi-Fi인지, Windows 방화벽이 8000 포트를 막지 않는지 확인 |
| 앱에서 서버 연결 실패 | `BASE_URL`이 폰 브라우저에서 열리는 주소와 같은지 확인 |
| 수신함이 비어 있음 | 선생님 화면에서 먼저 발송했는지, `parent_id`가 같은지 확인 |
| 예전 결과가 보임 | 새 가정통신문을 다시 발송하고 수신함을 다시 불러오기 |
| TTS URL이 없음 | 서버 TTS 실패 시 앱 내장 mp3로 fallback 재생될 수 있음 |
| STT 마이크가 반응 없음 | 앱에 마이크 권한이 허용되어 있는지 확인 (설정 → 앱 → 권한) |
| STT가 인식은 되는데 답변 없음 | 팁 카드에 적힌 문장과 비슷하게 말했는지 확인 — 키워드가 포함돼야 매칭됨 |
| TTS 속도 버튼이 안 보임 | 서버 TTS URL이 없을 때는 속도 행이 표시되지 않을 수 있음 |

## 8. 커밋 주의

`BASE_URL`은 `BuildConfig`로 분리되어 `MainActivity.java`에 하드코딩되어 있지 않습니다. 빌드 시 `-Pschoolbridge.baseUrl` 로 주입하므로, **소스 코드 커밋에는 URL이 포함되지 않습니다.**

- 로컬 IP로 빌드했던 APK를 커밋하지 마세요 (`.gitignore`에 `app/build/` 포함됨).
- 시연·평가는 항상 NCP 실서버(`-Pschoolbridge.baseUrl=http://NCP_IP:8000`) 기준으로 빌드된 APK를 사용하세요.
