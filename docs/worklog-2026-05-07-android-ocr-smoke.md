# 2026-05-07 워크로그 — Android 카메라 OCR 실기기 안정화

**작성자:** 모세종  
**작업 범위:** 학부모 홈 카메라 촬영 → ML Kit OCR → 업로드 → AI 번역 시연 흐름 복구

---

## 요약

실기기에서 `학부모 시작 → 통신문 직접 올리기 → 사진으로 찍기` 이후 앱이 홈 화면으로 돌아가는 문제가 있었다.

원인 확인 결과 카메라 촬영 자체는 성공했고, 사진 파일도 정상 저장되었다. 실제 문제는 OCR 전처리 단계에서 OpenCV 네이티브 라이브러리가 로드되지 않아 `Mat` 생성 시 앱 프로세스가 종료되는 것이었다.

따라서 시연 안정성을 우선해 OpenCV 전처리 실패 시 앱을 종료하지 않고, 원본 이미지 기반 ML Kit Korean OCR만으로 계속 진행하도록 방어 처리했다.

---

## 확인된 실제 원인

실기기 logcat:

```text
SchoolBridgeOcr: onActivityResult result=-1
photoFile=.../cache/ocr_....jpg exists=true length=2700208
SchoolBridgeOcr: runOcr fileReady=true

FATAL EXCEPTION: pool-7-thread-1
java.lang.UnsatisfiedLinkError:
No implementation found for long org.opencv.core.Mat.n_Mat()
  at org.opencv.core.Mat.<init>(Mat.java:23)
  at com.multicultural.demo.OcrActivity.toGrayscaleClahe(...)
  at com.multicultural.demo.OcrActivity.buildPreprocessVariants(...)
```

즉, 카메라/파일 저장 문제가 아니라 OpenCV native `.so` 로딩 문제였다.

---

## 수정 내용

파일:

```text
android/app/src/main/java/com/multicultural/demo/OcrActivity.java
```

적용한 안정화:

- 카메라 촬영 결과가 돌아왔을 때 사진 파일 존재 여부와 파일 크기 확인
- `RESULT_OK`가 정상이어도 파일이 없으면 화면을 닫지 않고 재촬영 안내
- 카메라 URI 권한을 `ClipData`와 read/write flag로 보강
- 액티비티 재생성 시 촬영 파일 경로 복원
- OCR 결과를 자동 업로드하지 않고 preview 확인 후 전송
- OpenCV 전처리 실패 시 `Throwable`로 방어
- OpenCV가 실패하면 원본 이미지 ML Kit OCR만 수행
- 디버그 로그 태그 `SchoolBridgeOcr` 추가

---

## 현재 성공 흐름

실기기에서 아래 흐름 확인:

```text
학부모 시작
→ 통신문 직접 올리기
→ 사진으로 찍기
→ ML Kit Korean OCR
→ 결과 확인
→ 그래도 전송
→ 업로드
→ AI 번역 시연
```

현재 상태는 **시연 가능한 안정 버전**이다.

---

## 현재 제한

OpenCV 기반 기능은 앱이 죽지 않도록 fallback 처리했다.

따라서 현재 실기기 APK에서는 다음 기능이 실패 시 skip될 수 있다.

- grayscale + CLAHE 전처리
- document warp
- 표 영역 감지
- 표 crop 2-pass OCR

이 경우에도 원본 이미지 기반 ML Kit OCR은 계속 진행된다.

---

## 후속 작업

1. OpenCV Android native 라이브러리 포함 방식 정리
   - `OpenCVLoader.initDebug()` 사용 가능 여부 확인
   - Maven dependency가 native `.so`를 APK에 포함하는지 확인
   - 필요 시 OpenCV Android SDK/AAR 방식으로 전환
2. 원본 ML Kit OCR vs OpenCV 전처리 OCR 비교 재실험
3. 실제 촬영 OCR 결과 20~30줄 수집
4. OCR slot correction 평가셋에 실제 촬영 결과 추가
5. bbox overlay PoC와 연결

---

## 2차 실기기 결과: 업로드 후 AI 번역까지 연결

카메라 OCR fallback 패치 이후 실제 학부모 플로우에서 다음 시나리오를 확인했다.

```text
사진 촬영
→ OCR 결과 확인
→ 그래도 전송
→ 업로드
→ AI 번역 화면 표시
```

성공한 점:

- 앱이 더 이상 OpenCV 단계에서 종료되지 않음
- OCR 결과 확인 화면까지 진입
- 사용자가 확인 후 직접 전송 가능
- 업로드 후 AI 번역 화면까지 자연스럽게 이어짐

발견된 품질 이슈:

- 긴 OCR 본문이 `해야 할 일` 카드에 과도하게 들어감
- URL이 `http://bit.`처럼 잘릴 수 있음
- NLLB가 보호 토큰을 `__Slot1__`, `__SLOt2__`처럼 대소문자를 섞어 출력해 화면에 그대로 노출됨
- 번역 결과에서 `Khác:`가 반복되어 카테고리/요약 품질이 낮아 보임

즉, 현재 상태는 **앱 플로우는 성공**, 다음 단계는 **번역/요약 품질 안정화**다.

---

## 추가 수정: placeholder 복원 안정화

파일:

```text
backend/app/services/translator.py
backend/tests/test_translator_slot_restore.py
```

문제:

```text
원래 토큰: __SLOT1__
NLLB 출력: __Slot1__, __SLOt2__
결과: 복원 실패 후 사용자 화면에 placeholder 노출
```

수정:

```text
__SLOTn__ 복원 정규식을 대소문자 무시 + 내부 공백 허용으로 변경
```

검증:

```powershell
python -m py_compile backend\app\services\translator.py backend\tests\test_translator_slot_restore.py
```

통과.

`pytest backend\tests\test_translator_slot_restore.py`는 현재 로컬 환경에 `fastapi`가 없어 `conftest.py` import 단계에서 실행하지 못했다.

---

## 발표/공유용 문장

실기기 테스트에서 카메라 촬영 자체는 정상 동작했지만, OpenCV 전처리 네이티브 라이브러리 로딩 문제로 OCR 단계에서 앱이 종료되는 문제가 확인되었습니다. 시연 안정성을 위해 OpenCV 전처리 실패 시 원본 이미지 기반 ML Kit OCR로 fallback하도록 수정했으며, 현재는 사진 촬영부터 업로드, AI 번역 시연까지 연결되는 흐름을 확보했습니다. OpenCV 전처리는 품질 개선용 후속 트랙으로 분리해 네이티브 패키징을 복구한 뒤 재실험할 예정입니다.

---

## 3차 보정: 번역 화면 노이즈 감소

실기기 업로드 후 AI 번역 화면까지 진입하는 데 성공했지만, 번역 결과 화면에서 다음 문제가 확인되었다.

```text
1. NLLB가 보호 토큰을 __Slot1__, __SLOt2__처럼 대소문자를 섞어 출력
2. 복원 실패한 slot token이 화면에 그대로 노출
3. fallback 카드가 여러 개 나오면서 베트남어 번역에 Khac: prefix가 반복
4. OCR 본문이 길게 들어간 fallback 카드가 번역 영역을 과도하게 차지
```

수정 내용:

```text
backend/app/services/translator.py
- protected slot restore regex를 대소문자 무시 + 내부 공백 허용으로 확장
- 존재하지 않는 slot index가 출력되면 사용자 화면에 노출하지 않고 제거

backend/app/services/card_builder.py
- header 추출 실패 카드(기타)는 번역 header를 비워 Khac 반복을 줄임
- 긴 기타 카드는 한국어 80자 / 번역문 120자 기준으로 trim
- importance 정렬 후 기타 카드는 최대 3개까지만 유지
```

검증:

```powershell
python -m py_compile backend\app\services\translator.py backend\app\services\card_builder.py backend\tests\test_translator_slot_restore.py
```

결과: 통과.

주의:

```text
이 변경은 로컬 백엔드 코드 기준이다.
폰에서 다시 확인하려면 NCP 백엔드에 반영/재배포된 뒤 같은 이미지로 재테스트해야 한다.
```

다음 확인 포인트:

```text
1. __Slot / __SLOt token이 더 이상 화면에 노출되지 않는지
2. Khac: prefix 반복이 줄었는지
3. 해야 할 일 카드가 너무 긴 본문 대신 핵심 항목 위주로 보이는지
4. URL이 OCR 단계에서 잘리는 문제는 별도 OCR/bbox 트랙에서 샘플 수집
```
