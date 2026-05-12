# Sentence Extraction — 1단계 자체화 PoC

가정통신문 1단계(`sentence_list` 추출)를 외부 LLM(Claude Haiku 4.5)에서 자체 모델로 옮기기 위한 비교 검증 노트북 보존소. 발표 §3-4 「자체화 시도 흔적」의 근거.

## 검증 이력

| 노트북 | 모델 | 셔플 정확도 | 결론 |
| --- | --- | --- | --- |
| `lilt_sentence_grouping_colab.ipynb` | LiLT (140M, text+bbox) | 43.3% | bbox만으론 layout 학습 불가 |
| `layoutxlm_sentence_grouping_colab.ipynb` | LayoutXLM (360M, +image stream) | 78.8% | image stream이 layout 학습에 결정적 |
| `layoutxlm_train_test_split_colab.ipynb` | LayoutXLM 4장 train / 2장 test | — | 일반화 9.7%, `sentence_id` task 한계 → BIO 의미 라벨 재설계 필요 |

> **셔플 검증**: 토큰 순서를 무작위로 섞어 시퀀스 신호를 제거한 뒤, 모델이 진짜 layout을 학습하는지(bbox·image만으로 분류 가능한지) 측정하는 방식.

## 향후 실험 후보

- **BIO 의미 라벨** (`B-SENDER`, `B-TITLE`, `B-BODY`, `B-LIST_ITEM`, `B-TABLE_*`) — `sentence_id` task의 페이지 의존성 해결
- **Entity Linking (RE)** — LiltForRelationExtraction, 토큰 쌍 binary 분류
- **라벨 규모 확장** — 학교 양식 다양성 100~300장

## 입력 스코프

PDF text layer / HWPX / HWP 5.0(LibreOffice 경유) 지원. JPG·스캔 PDF는 OCR 픽셀 의존성 때문에 배제 (변형 0 보장 충돌).
