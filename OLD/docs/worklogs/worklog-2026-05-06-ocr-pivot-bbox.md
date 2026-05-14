# 2026-05-06 워크로그 — OCR 피벗 PoC: bounding box 기반 하이라이트 준비

**작성일:** 2026-05-06  
**작성자:** 세종 (mosejong)  
**작업 범위:** ML Kit OCR line bbox 추출 + analyze highlights 응답 스키마 + 디지털 PDF bbox 검토

---

## 한 줄 요약

회의 피드백에 따라 "텍스트 추출 후 요약" 중심에서 "원본 문서 위 중요 정보 하이라이트" 방향으로 피벗하기 위해, OCR 결과에서 텍스트뿐 아니라 line 단위 bounding box를 추출하고 `/notice/analyze/{id}` 응답에 `highlights` 자리를 추가하는 PoC 기반을 마련했다.

---

## 배경

강사님 피드백의 핵심은 단순 PDF/text 추출·요약만으로는 ChatGPT에 파일을 업로드하는 것과 차별성이 약하다는 점이었다. 따라서 원본 문서의 위치 정보를 유지하고, AI가 판단한 중요 문장을 원본 위에 하이라이트하는 UX가 필요하다.

팀장님 작업 분리:

| 트랙 | 담당 | 내용 |
|---|---|---|
| OCR 피벗 | 세종 | ML Kit boundingBox 추출 + 디지털 PDF 처리 검토 |
| OCR 피벗 | 태수 | backend bbox 응답 + Android PDF overlay 하이라이트 |
| 라벨링 검토 | 윤정 + 경이 | random sample 라벨/모델 예측 비교, kappa 측정 |

---

## 작업 내용

### 1. Android ML Kit line bbox 추출

파일: `android/app/src/main/java/com/multicultural/demo/OcrActivity.java`

기존:

```text
TextBlock.getText()
→ OCR 텍스트만 합침
→ /notice/upload-self 에 txt 파일로 업로드
```

변경:

```text
TextBlock
  → Line
    → line.getText()
    → line.getBoundingBox()
```

추출 JSON 필드:

```json
{
  "page": 1,
  "source": "mlkit_line",
  "variant_index": 0,
  "block_index": 0,
  "line_index": 0,
  "text": "참가 동의서는 4월 28일(화)까지 제출",
  "x": 80,
  "y": 240,
  "width": 480,
  "height": 32
}
```

추가된 결과 키:

```java
RESULT_OCR_LAYOUT = "ocr_layout_json"
```

### 2. highlight 매핑 helper 추가

파일:

```text
backend/app/services/highlight_mapper.py
```

역할:

```text
OCR/PDF layout line JSON
  + analyze 카드 결과(value_ko/value_translated/value_easy_ko/category)
  → highlights 응답 후보
```

매칭 전략:

```text
1. normalized exact match
2. normalized substring match
3. SequenceMatcher fuzzy score
```

지원 입력:

- Android ML Kit flat line JSON
- OCR Lab `pdf_bbox_probe.py`의 `{pages: [{lines: [...]}]}` JSON

아직 `/notice/analyze/{id}`에 직접 연결하지는 않았다. 태수님 backend 저장/overlay 흐름에서 layout JSON 저장 위치가 확정되면 연결한다.

### 3. analyze 응답 highlights 스키마 추가

파일:

- `backend/app/models/schemas.py`
- `backend/app/routers/notice.py`

`NoticeAnalyzeResponse`에 overlay 하이라이트 후보 필드를 추가했다.

```json
{
  "page_count": 1,
  "highlights": []
}
```

하이라이트 1개는 다음 스키마를 따른다.

```json
{
  "highlight_id": "h_001",
  "page": 1,
  "source": "mlkit_line",
  "bbox": {"x": 120, "y": 340, "width": 380, "height": 28},
  "page_size": {"width": 1000, "height": 1414},
  "text": "4월 28일(화)까지 담임선생님께 제출 바랍니다",
  "category": "제출",
  "importance": 0.92,
  "translated": "Vui lòng gửi đến giáo viên chủ nhiệm trước ngày 28/4 (Thứ Ba)",
  "easy_ko": "..."
}
```

현재는 bbox 매핑 로직이 없으므로 `highlights`는 빈 배열로 내려준다.
태수님 backend bbox 매핑 트랙에서 OCR/PDF 좌표와 모델 결과를 연결해 채운다.

### 4. backend 업로드 연동은 보류

현재 Android bbox JSON은 Activity result에만 포함한다.
`/notice/upload-self` multipart payload는 기존 그대로 유지한다.

태수님 backend 저장/overlay 설계가 확정되면 다음 PR에서 `ocr_layout_json` 업로드와 저장을 연결한다.

---

## 디지털 PDF 처리 검토

OCR lab 레포에 디지털 PDF bbox PoC 스크립트를 추가했다.

레포:

```text
https://github.com/mosejong/schoolbridge-ocr-lab
```

파일:

```text
tools/pdf_bbox_probe.py
```

의도:

```text
텍스트 PDF는 OCR을 돌리지 않고 pdfplumber 좌표 기반으로 text + bbox 추출
스캔 PDF/촬영 이미지는 OCR bounding box 사용
HWP/HWPX는 우선 ODT/XML 구조 파싱, 필요 시 PDF 변환 후 위치 처리
```

---

## 검증

```powershell
python -m py_compile backend\app\models\schemas.py backend\app\routers\notice.py
```

통과.

```powershell
python -m py_compile backend\app\services\highlight_mapper.py
```

통과.

순수 함수 샘플 검증:

```text
layout line: "참가 동의서는 4월 28일(화)까지 담임선생님께 제출 바랍니다"
card value:  "4월 28일(화)까지 담임선생님께 제출 바랍니다"
→ highlight 1건 생성, category/bbox/page_size 보존 확인
```

```powershell
.\gradlew.bat :app:compileDebugJavaWithJavac "-Pschoolbridge.baseUrl=http://101.79.17.196:8000/"
```

통과.

`pytest backend\tests\test_analyze_routes.py`는 로컬 환경에 `fastapi`가 없어 실행하지 못했다.

---

## 남은 작업

- [ ] 태수님 backend overlay 응답 스키마와 `ocr_layout_json` 파싱 방식 합의
- [ ] Android 원본 이미지/PDF 위에 bbox rectangle overlay 렌더링
- [ ] 윤정/경이 모델이 뽑은 중요 문장과 OCR line text를 fuzzy match로 재매핑
- [ ] 1~2장 가통문 샘플로 PoC 시연
- [ ] 텍스트 PDF / 스캔 PDF / HWP 변환 PDF별 좌표 기준 통일
