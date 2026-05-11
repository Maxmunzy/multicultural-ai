# 트러블슈팅 — A단계 추출 모델 (2026-04-29)

**담당**: 윤정  
**환경**: Windows 11 / Miniconda (multicultural 환경) / CPU

---

## 1. NumPy 버전 충돌

### 증상
```
A module that was compiled using NumPy 1.x cannot be run in NumPy 2.2.6
Failed to initialize NumPy: _ARRAY_API not found
```

### 원인
torch 2.1.0이 NumPy 1.x 기반으로 컴파일됐으나 NumPy 2.2.6이 설치됨.

### 해결
```bash
pip install "numpy<2"
```

### 상태
✅ 해결 완료

---

## 2. PDF 줄 끊김으로 문장 잘림

### 증상
```
출력: "생 및 학부모(보호자) 모두 기한 내 신청하여 주시기 바랍니다."
원문: "...다문화가정 학↵
       생 및 학부모(보호자) 모두..."
```

### 원인
`preprocess_txt_to_jsonl.py`에는 `join_broken_lines()`가 있었지만 `predict.py`에는 없었음.  
PDF에서 추출된 텍스트는 단어 중간에 줄 바꿈이 있어 문장이 잘림.

### 해결
`predict.py`에 `_join_broken_lines()` 함수 추가 후 `predict()` 내에서 호출.

```python
def _join_broken_lines(text: str) -> str:
    text = re.sub(r" ([가-힣])\n([가-힣])", r" \1\2", text)  # 단어 중간 끊김
    text = re.sub(r"([^.!?\n])\n([^\n])", r"\1 \2", text)    # 문장 이어짐
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def predict(notice_text, source=None):
    notice_text = _join_broken_lines(notice_text)  # ← 추가
    ...
```

### 상태
✅ 해결 완료

---

## 3. TypedStorage deprecated 경고

### 증상
```
UserWarning: TypedStorage is deprecated. It will be removed in the future and
UntypedStorage will be the only storage class.
```

### 원인
torch 내부 구현 변경으로 인한 deprecated 경고. 기능에는 영향 없음.

### 해결
`predict.py` 상단에 경고 필터 추가.

```python
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="torch")
```

### 상태
✅ 해결 완료

---

## 4. HF Hub 모델 로드 실패 (404 config.json)

### 증상
```
EntryNotFoundError: 404 Client Error.
Entry Not Found for url: https://huggingface.co/yunjeong116/koelectra-extractor/resolve/main/config.json
```

### 원인
두 가지 문제가 겹침:
1. `predict.py`의 `_LOCAL_CHECKPOINT_DIR` 경로가 한 단계 틀림 (`file/checkpoints/` → `checkpoints/` 이어야 함)
2. 로컬 체크포인트에 `pytorch_model.bin`만 있고 `config.json` 없어 `_local_ready=True`가 되었지만 실제 로드 실패 → HF Hub fallback → HF Hub에도 파일 없음

```python
# 수정 전 (잘못된 경로)
_LOCAL_CHECKPOINT_DIR = os.path.join(os.path.dirname(__file__), "checkpoints/koelectra-binary")
# → extraction/file/checkpoints/ (존재하지 않음)

# 수정 후 (올바른 경로)
_LOCAL_CHECKPOINT_DIR = os.path.join(os.path.dirname(__file__), "..", "checkpoints", "koelectra-binary")
# → extraction/checkpoints/ (실제 위치)
```

### 해결
1. 경로 수정 (`..` 추가)
2. `_local_ready` 체크에 `config.json` 존재 여부 추가

```python
_local_ready = (
    any(os.path.exists(os.path.join(_LOCAL_CHECKPOINT_DIR, f))
        for f in ("pytorch_model.bin", "model.safetensors"))
    and os.path.exists(os.path.join(_LOCAL_CHECKPOINT_DIR, "config.json"))
)
```

3. HF Hub(`yunjeong116/koelectra-extractor`)에 전체 파일 업로드

### 상태
✅ 해결 완료 — 현재 HF Hub fallback으로 정상 로드

---

## 5. 날짜·기간 형식 문장 미추출 (미해결)

### 증상
아래 문장이 추출되지 않음:
```
"2. 신청 기간: 2023. 3. 6. (월) ~ 3. 17. (금) 정기 모집 기간 신청 시 3.20.(월)까지 승인"
```

### 원인
모델이 "신청 기간: 날짜" 형식 문장에 낮은 confidence를 부여함.  
`v2.1_notices_galsan.jsonl` 학습 데이터에 이 패턴이 `is_todo: false`로 라벨링됐거나 부족한 것으로 추정.

### 임시 대응
없음. 현재는 "주시기 바랍니다" 등 명시적 행동 요청 문장만 추출됨.

### 해결 방향
- `v2.1` 데이터에서 날짜+기간 형식 문장을 `is_todo: true`로 추가 라벨링
- 추가 데이터로 재학습

### 상태
❌ 미해결 — 추후 데이터 보강 후 재학습 예정

---

## 6. 비용 관련 문장 다중 추출 → 카드 4개 생성 이슈

### 증상
통신문에 비용 항목이 여러 줄 있을 때 (버스비 23,000원 / 보험료 3,000원 / 체험학습비 납부 안내 등)  
KoELECTRA가 각 문장을 별도 todo로 추출하여, 파이프라인에서 카드를 각각 생성 → 비용 탭에 카드 4개가 동시에 노출됨.

예시 문장:

```text
비용: 체험학습비: 양주시농업기술센터 '농촌사랑 자연체험 학습 지원사업'에서 버스 1대 지원,
※ 체험학습비는 4. 13. (월)~4. 15. (수)에 스쿨뱅킹계좌에서 자동으로 이체되니 잔액을 확인하시기 바랍니다.
```

### 원인

- dedup 로직이 value가 다른 카드는 제거하지 않음
- 파이프라인에서 같은 chip끼리 강제 병합 시 실제 복수 비용 항목이 있는 통신문에서 정보 손실 발생 가능

### 해결 방향 (검토 중)

1. **모델 단 개선**: 비용 관련 문장들을 하나의 청크로 묶어 추출하도록 학습 데이터 보강
2. **파이프라인 단 처리**: 같은 chip의 카드가 N개 이상이면 합치는 후처리 로직 추가

### 상태
❌ 미해결 — 개선 방안 검토 중 (발표 시 트러블슈팅 사례로 설명 예정)
