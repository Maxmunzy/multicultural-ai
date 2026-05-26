# 3-way 비교 설계 설명 — v4_improved (2026-05-26)

**담당:** 경이 (kyeongyi)  
**관련 파일:**
- `notebooks/15_train_kcelectra_v4_improved_20260526.ipynb`
- `notebooks/15_visualize_comparison_v4_improved_20260526.ipynb`
- `scripts/evaluate_compare_v4_schoolalimi_20260525.py`

---

## 비교 대상 3개 모델

| 모델 | 학습 데이터 | 학습 행 수 | 테스트 데이터 |
|------|-----------|-----------|------------|
| Simple (TF-IDF + LogReg) | split_v4 train | 13,210행 | split_v4 test original (1,593건) |
| KcELECTRA v3_2 | split_v3_1 train | 12,759행 | split_v3_1 test (1,593건) |
| KcELECTRA v4_improved | split_v4 train | 13,210행 | split_v4 test original (1,593건) |

---

## 왜 학습 데이터가 다른데 비교가 가능한가?

### 핵심: test set이 완전히 동일하다

- `split_v4_schoolalimi_20260525.csv`의 `(split == 'test') & (source == 'original')` = 1,593건
- `split_v3_1`의 `(split == 'test')` = 1,593건
- 두 test set은 **완전히 동일한 샘플**

학교알리미 증강 데이터는 train에만 배정되었기 때문에 test set에는 포함되지 않는다.  
따라서 세 모델 모두 **같은 1,593건에 대한 답을 내고 있으며**, 점수 직접 비교가 가능하다.

### split_v4 구성

```
split_v4_schoolalimi_20260525.csv (총 16,512행)
├── train: 13,210행
│   ├── original: 12,646행 (split_v3_1 train에서 이어짐)
│   └── augmented: 564행 (학교알리미 공공데이터)
│       ├── 건강·안전: +152행
│       ├── 일정: +237행 (train 배정분)
│       └── 비용: +62행 (train 배정분)
├── val: 1,596행 (original only — 증강 데이터 제외)
└── test: 1,593행 (original only — split_v3_1 test와 동일)
```

> **v4_improved val/test purity 처리:**
> ```python
> train_df = df[df['split'] == 'train']                              # 13,210 (original + augmented)
> val_df   = df[(df['split'] == 'val')  & (df['source'] == 'original')]  # 1,596 (original만)
> test_df  = df[(df['split'] == 'test') & (df['source'] == 'original')]  # 1,593 (original만)
> ```
> v4 실패 원인이 val에 증강 데이터가 섞인 것이었기 때문에 명시적으로 필터링한다.

---

## 각 비교 쌍의 의미

### 1. Simple vs v4_improved — 메인 비교
- **조건**: 완전히 공평 (둘 다 split_v4 train 13,210행으로 학습, 동일 test)
- **목적**: "왜 KcELECTRA(트랜스포머)를 써야 하는가?"에 대한 수치적 답변
- **기준**: Macro F1 5%+ 향상 → 딥러닝 도입 당위성 확보

### 2. v3_2 vs v4_improved — 개선 검증
- **조건**: v4_improved가 더 많은 학습 데이터(+451행 증강)와 개선된 기법을 사용
- **목적**: 학교알리미 증강 + 학습 기법 개선(LabelSmoothing, cosine schedule 등)이 실제로 효과가 있는지 검증
- **해석**: v4_improved가 v3_2보다 높으면 → 증강 + 기법 개선이 유효함을 증명

> v4_improved는 더 유리한 조건(더 많은 학습 데이터)에서 v3_2를 이겨야 하므로, 이기지 못한다면 오히려 증강이 노이즈로 작용한다는 의미가 된다.

---

## v3_2를 split_v4로 재학습하지 않는 이유

완전히 동일한 학습 조건으로 비교하려면 v3_2도 split_v4 train으로 재학습해야 한다.  
그러나 이 경우 두 가지 문제가 생긴다:

1. **기존 실험 이력과 단절**: v3_2의 "원래 성능(Macro F1=0.8374)"이 바뀌어버려 v1→v2→v3 추이가 의미를 잃는다.
2. **비교 목적 훼손**: 이 프로젝트의 목적은 "v4_improved가 v3_2의 성능을 넘어서는가"이지, 동일 조건 재현 실험이 아니다.

---

## 비교의 공정성 요약

| 비교 항목 | 공정한가? | 근거 |
|----------|---------|------|
| test set 동일성 | ✓ 공정 | 세 모델 모두 동일한 1,593건 |
| Simple vs v4_improved 학습 데이터 | ✓ 공정 | 둘 다 split_v4 train 13,210행 |
| v3_2 vs v4_improved 학습 데이터 | 비대칭 (의도적) | v4_improved가 451행 더 많음 → v4_improved에 유리한 조건 |
| 평가 지표 | ✓ 공정 | 세 모델 모두 Macro F1 (클래스 불균형 보정) |

---

## 관련 파일 경로

| 파일 | 설명 |
|------|------|
| `data/split_v4_schoolalimi_20260525.csv` | 학습·평가용 통합 데이터셋 (16,512행) |
| `data/20260525/eval_results_simple_v4_20260525.json` | Simple — split_v4 기반 평가 결과 |
| `data/20260509/eval_results_kcelectra_v3_2_20260509.json` | KcELECTRA v3_2 — split_v3_1 기반 평가 결과 |
| `data/20260526/eval_results_kcelectra_v4_improved_20260526.json` | KcELECTRA v4_improved — Colab 학습 후 생성 |
