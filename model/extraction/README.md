# 모델 A: 할 일 추출 및 통합 분류 (Extraction & Classification)

> **담당: 윤정**
> **위치:** `model/extraction/`
> **핵심 기능:** 가정통신문 원문에서 학부모가 해야 할 '할 일(To-Do)'을 추출하고, 카테고리 분류 및 중요도를 산출

---

## 1. 개요

선생님이 보낸 가정통신문 텍스트에서 학부모가 확인해야 할 **핵심 행동 지침**을 뽑아냅니다.
백엔드 `schemas.py`의 `TodoItem` 구조와 100% 호환되는 JSON 리스트를 반환합니다.

---

## 2. 현재 구조 (경로 B 하이브리드)

```text
가정통신문 텍스트
    ↓
[1] split_sentences()       문장 단위 분리
    ↓
[2] is_likely_todo()        안부인사·서명 등 1차 필터
    ↓
[3] extract_due_date()      정규식: 날짜·마감 추출
    ↓
[4] classify_category()     KoELECTRA: 5개 카테고리 분류
                            (비용은 정규식으로 별도 처리)
    ↓
[5] calc_importance()       카테고리 + due_date + 긴급키워드 → 중요도 점수
    ↓
TodoItem 리스트
```

---

## 3. 기술 스택

| 구성 요소 | 내용 |
| --- | --- |
| **분류 모델** | `KoELECTRA-base-v3` (fine-tuned, HuggingFace Hub) |
| **Hub ID** | `yunjeong116/koelectra-extractor` |
| **날짜·비용 추출** | 정규식 (regex) |
| **실행 환경** | CPU / GPU 자동 선택 (`torch.cuda.is_available()`) |
| **의존성** | `torch`, `transformers`, `huggingface_hub` |

> **이전 접근법 (`x/MODEL.py`):** Llama-3-Korean-8B-Instruct + Few-shot + 4-bit 양자화 (Colab T4)
> → 현재는 KoELECTRA 하이브리드로 전환 (추론 속도·배포 용이성 개선)

---

## 4. 카테고리 정의

| 카테고리 | 설명 | 기본 중요도 |
| --- | --- | --- |
| `제출` | 서류·동의서·과제 제출 | 1.0 |
| `준비물` | 지참물 안내 | 0.85 |
| `건강·안전` | 건강·안전 관련 사항 | 0.80 |
| `비용` | 금액 포함 항목 (정규식 처리) | 0.75 |
| `일정` | 행사·일정 안내 | 0.70 |
| `기타` | 위에 해당하지 않는 항목 | 0.50 |

---

## 5. 파일 구성

```text
model/extraction/
├── predict.py                          # 메인 추출 파이프라인 (백엔드 연동용)
├── requirements-extraction.txt         # 의존성 패키지
├── data/
│   └── notices_labeled_v2.jsonl        # 학습용 레이블 데이터
├── checkpoints/
│   └── koelectra-extractor/            # 로컬 체크포인트 (HuggingFace Hub 백업)
│       ├── pytorch_model.bin
│       ├── config.json
│       ├── labels.json
│       └── tokenizer_config.json (외)
└── x/                                  # 구버전 (참고용, 미사용)
    ├── MODEL.py                        # Llama 기반 초기 구현
    ├── notices_labeled_v2.csv          # 원본 CSV 데이터
    └── extracted_results.json          # 초기 LLM 추출 결과
```

---

## 6. 입출력 규격

**입력:** 가정통신문 전문 텍스트 (string)

**출력:** `TodoItem` 리스트 (백엔드 `schemas.py` 호환)

```json
[
  {
    "category": "준비물",
    "text_ko": "개인용 물병 및 실내화 지참",
    "due_date": "2026-04-20",
    "importance": 0.85,
    "text_vi": ""
  },
  {
    "category": "비용",
    "text_ko": "구입비는 5,000원 이내의 잔돈으로 준비합니다.",
    "due_date": null,
    "importance": 0.75,
    "text_vi": ""
  }
]
```

---

## 7. 실행 방법

```bash
# 의존성 설치
pip install -r requirements-extraction.txt

# 단독 테스트 실행 (predict.py 하단 샘플 데이터 사용)
python predict.py
```

백엔드에서는 `predict.py`의 `extract_todos()` 또는 `extract_todos_dict()`를 import하여 사용합니다.
모델은 첫 호출 시 HuggingFace Hub에서 자동으로 다운로드됩니다.

---

## 8. 백엔드 연동

```python
from model.extraction.predict import extract_todos_dict

todos = extract_todos_dict(notice_text)  # list[dict] 반환
```

`schemas.py` 사용 가능 환경에서는 `extract_todos()`가 `TodoItem` 객체 리스트를 직접 반환합니다.
