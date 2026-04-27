# 모델 A — 할 일 추출 & 분류 파이프라인

**담당: 윤정** · `model/extraction/` · KoELECTRA-base-v3 fine-tuned

---

## 한 줄 요약

> 가정통신문 전문을 넣으면, 학부모가 실행해야 할 **TodoItem 리스트**가 나옵니다.

---

## 파이프라인

```text
┌─────────────────────────────────────────────────────────┐
│                    가정통신문 원문 텍스트                  │
└────────────────────────┬────────────────────────────────┘
                         │
              ① split_sentences()
                문장 단위로 분리
                         │
              ② is_likely_todo()
              안부인사 · 서명 · 날짜표기 등 제거
                         │
              ③ extract_due_date()          ┐
              정규식으로 날짜 · 마감 추출    │ 병렬
                         │                 │
              ④ has_money()                ┘
              금액 패턴 감지 (비용 카테고리 직행)
                         │
              ⑤ classify_category()
              KoELECTRA → 5개 카테고리 분류
                         │
              ⑥ calc_importance()
              카테고리 · due_date · 긴급키워드 → 점수
                         │
┌─────────────────────────────────────────────────────────┐
│                    TodoItem [ ] 반환                      │
└─────────────────────────────────────────────────────────┘
```

---

## 기술 스택

| | |
| --- | --- |
| 분류 모델 | KoELECTRA-base-v3 · `yunjeong116/koelectra-extractor` |
| 날짜 / 비용 | 정규식 (regex) |
| 실행 환경 | CPU / GPU 자동 선택 |
| 의존성 | `torch` · `transformers` · `huggingface_hub` |

> **이전 → 현재:** Llama-3-Korean 8B (Colab T4, 4-bit 양자화) → KoELECTRA 하이브리드
> 추론 속도 ↑, 서버 배포 용이성 ↑

---

## 카테고리 & 중요도

| 카테고리 | 설명 | 기본 점수 |
| --- | --- | --- |
| `제출` | 서류 · 동의서 · 과제 | **1.00** |
| `준비물` | 지참물 안내 | 0.85 |
| `건강·안전` | 건강 · 안전 사항 | 0.80 |
| `비용` | 금액 포함 항목 (정규식) | 0.75 |
| `일정` | 행사 · 일정 안내 | 0.70 |
| `기타` | 위 외 항목 | 0.50 |

긴급 키워드(`반드시`, `마감`, `즉시` 등) 포함 시 +0.05 / due_date 있을 시 +0.05

---

## 파일 구성

```text
model/extraction/
├── predict.py                    ← 메인 파이프라인 (백엔드 import 진입점)
├── requirements-extraction.txt
├── data/
│   └── notices_labeled_v2.jsonl  ← 학습 레이블 데이터
├── checkpoints/
│   └── koelectra-extractor/      ← 로컬 체크포인트 (Hub 백업)
└── x/                            ← 구버전 보관 (Llama Few-shot)
    ├── MODEL.py
    ├── notices_labeled_v2.csv
    └── extracted_results.json
```

---

## 출력 예시

```json
[
  {
    "category": "준비물",
    "text_ko": "개인용 이어폰(3.5mm) 4월 20일까지 준비",
    "due_date": "2026-04-20",
    "importance": 0.9,
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

## 실행

```bash
pip install -r requirements-extraction.txt
python predict.py          # 하단 샘플 가정통신문으로 즉시 테스트
```

---

## 백엔드 연동

```python
from model.extraction.predict import extract_todos_dict

todos = extract_todos_dict(notice_text)   # list[dict]
```

모델은 첫 호출 시 HuggingFace Hub(`yunjeong116/koelectra-extractor`)에서 자동 다운로드됩니다.
`schemas.py` 임포트 가능 환경에서는 `extract_todos()`가 `TodoItem` 객체를 직접 반환합니다.
