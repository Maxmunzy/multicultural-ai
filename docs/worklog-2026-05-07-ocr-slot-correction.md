# 2026-05-07 워크로그 — OCR 핵심 slot confusable 문자 보정 PoC

**작성자:** 세종 (mosejong)  
**작업 범위:** OCR 결과 중 날짜/시간/금액/학년/전화번호 같은 핵심 slot의 오인식 후보 보정

---

## 출발점

MNIST처럼 제한된 문자 집합을 분류하는 예제에서 착안했다. 전체 한글 OCR을 새로 만드는 것은 범위가 너무 크지만, 가정통신문에서 중요한 날짜, 시간, 금액, 학년, 제출기한 같은 정보는 형식이 제한되어 있다.

따라서 OCR 전체를 다시 만들기보다, 기존 OCR 결과에서 서비스 품질에 직접 영향을 주는 핵심 slot만 골라 confusable character를 재검증하는 방향으로 잡았다.

---

## 핵심 방향

```text
OCR 전체 교체 X
OCR이 자주 틀리는 핵심 정보만 좁혀서 보정 O
```

예시:

| OCR 결과 | 보정 결과 | slot |
|---|---|---|
| `44,B70완` | `44,870원` | 금액 |
| `8:5O` | `8:50` | 시간 |
| `5원 6일(묵)` | `5월 6일(목)` | 날짜/요일 |
| `l-6확년` | `1-6학년` | 학년 |
| `O10-1234-567S` | `010-1234-5675` | 전화번호 |

중요한 점은 `B -> 8`, `O -> 0` 같은 치환을 전체 텍스트에 적용하지 않는 것이다. 금액/시간/전화번호처럼 형식이 제한된 slot 내부에서만 보정한다.

---

## 추가 파일

```text
backend/app/services/ocr_slot_corrector.py
backend/tests/test_ocr_slot_corrector.py
data/ocr_slot_correction_eval_sample.csv
scripts/evaluate_ocr_slot_correction.py
outputs/ocr_slot_correction_eval.csv
outputs/ocr_slot_correction_eval.md
```

### ocr_slot_corrector.py

역할:

```text
OCR text
  -> high-value slot 후보 탐지
  -> confusable 문자 교정
  -> corrected_text + correction audit metadata 반환
```

지원 slot:

- amount
- time
- date
- weekday
- grade
- class
- phone

반환 예시:

```json
{
  "slot_type": "amount",
  "raw_text": "44,B70완",
  "corrected_text": "44,870원",
  "reason": "amount slot: digit/unit confusable correction",
  "review_required": false
}
```

---

## 검증

컴파일:

```powershell
python -m py_compile backend\app\services\ocr_slot_corrector.py backend\tests\test_ocr_slot_corrector.py
```

통과.

평가 스크립트:

```powershell
python scripts\evaluate_ocr_slot_correction.py
```

결과:

```text
OCR slot correction eval: raw=1/7, corrected=7/7
```

합성/가정 OCR 오류 샘플 7건 기준:

| 지표 | OCR 원본 | 보정 후 |
|---|---:|---:|
| exact match | 1/7 (14%) | 7/7 (100%) |
| avg CER | 0.1282 | 0.0000 |

출력:

```text
outputs/ocr_slot_correction_eval.csv
outputs/ocr_slot_correction_eval.md
```

직접 smoke assertion:

```powershell
$env:PYTHONPATH='backend'
python -c "... apply_ocr_slot_corrections smoke assertions ..."
```

통과.

`pytest backend\tests\test_ocr_slot_corrector.py -q`는 로컬 환경에 `fastapi`가 없어 기존 `backend/tests/conftest.py` import 단계에서 실패했다.

```text
ModuleNotFoundError: No module named 'fastapi'
```

---

## 현재 한계

- 아직 실제 ML Kit bbox crop 이미지를 다시 분류하는 모델은 붙이지 않았다.
- 현재는 OCR 텍스트 후처리 기반의 1차 PoC이며, 평가 샘플도 실제 촬영본이 아니라 합성/가정 오류 샘플이다.
- 실제 OCR confidence/bbox와 연결하면 의심 문자 crop 재검증까지 확장할 수 있다.
- 디지털 PDF/HWP는 OCR 보정보다 text+bbox 직접 추출이 우선이며, 이 모듈은 스캔/사진/OCR 결과에 적용하는 보조 레이어다.

---

## 번역 개선과의 연결

```text
번역:
NLLB가 핵심 용어를 틀림
-> 준비물/제출물/날짜/금액을 구조화와 템플릿으로 보호

OCR:
OCR이 핵심 문자를 틀림
-> 날짜/금액/시간/학년 slot을 validator와 confusable 보정으로 보호
```

즉, 모델이 틀리는 부분을 모델 교체로만 해결하지 않고, 서비스 도메인에서 중요한 정보를 구조화하여 보호하는 전략이다.

---

## 다음 작업

- [x] correction 전/후 비교 CSV/MD 생성 스크립트 추가
- [ ] 실제 ML Kit OCR 결과 20~30줄을 `data/ocr_slot_correction_eval_sample.csv` 형식으로 추가
- [ ] Android ML Kit line bbox JSON과 correction audit metadata 연결
- [ ] correction이 발생한 line을 `review_required` 또는 highlight tooltip에 표시
- [ ] 날짜/요일 validator 강화: 실제 날짜와 요일 일치 여부 확인
- [ ] 금액/시간/학년 slot 정확도 지표 추가
