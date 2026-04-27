"""대화형 데모 스크립트 (Jupyter 변환 가능, %% 셀 구분).

각 셀은 # %% 로 구분되어 있어 VSCode/Jupytext에서 .ipynb로 자동 변환 가능.


- 교차검증, 카테고리별 오답 사례 분석, 중요도 분포 시각화까지.
"""

# %% [markdown]
# # 모델 B 데모: 가정통신문 분류 + 중요도
#
# ```
# 추출 문장 → [모델 B] → category + importance + action_required
# ```

# %% 1. 데이터 로드 + 분포 확인
from src.data_loader import build_dataset, summarize

split = build_dataset()
print(summarize(split))

# %% 2. 시급도 룰 단독 동작 확인
from src.feature_engineering import extract_features, rule_importance

samples = [
    "학생 기초조사서를 내일까지 담임선생님께 제출해 주세요",
    "다음 주 월요일 현장체험학습 참가 신청서를 담임선생님께 제출해 주세요",
    "방과후학교 수강료 25000원은 다음 달 5일 자동이체됩니다",
    "여름방학 과제 안내장은 방학식 당일 배부됩니다",
    "감염병 확진 시 등교하지 말고 학교로 즉시 연락해 주세요",
    "4월 30일까지 개인정보 수집 이용 동의서를 제출해 주세요",
]
for s in samples:
    f = extract_features(s)
    print(f"urgency={f.urgency_score:.2f} days={f.days_to_deadline} | {s}")

# %% 3. 분류기 학습 + 평가
from src.classifier_simple import SimpleNoticeClassifier
from src.importance_scorer import ImportanceScorer
from src.evaluate import evaluate_pipeline

clf = SimpleNoticeClassifier(epochs=300)
clf.fit(split.train["original_text"].tolist(), split.train["category"].tolist())
scorer = ImportanceScorer()
scorer.fit(
    split.train["original_text"].tolist(),
    split.train["category"].tolist(),
    split.train["importance"].tolist(),
)

result = evaluate_pipeline(clf, scorer, split.test, name="demo")
print(result["markdown"])

# %% 4. 오답 케이스 분석 (어디서 헷갈리는가?)
import pandas as pd

texts = split.test["original_text"].tolist()
y_true = split.test["category"].tolist()
y_pred = clf.predict(texts)
err = pd.DataFrame(
    [
        {"text": t, "true": y, "pred": p}
        for t, y, p in zip(texts, y_true, y_pred)
        if y != p
    ]
)
print(f"오답 {len(err)}/{len(texts)}건")
print(err.to_string(index=False))

# %% 5. importance 예측 vs 사람 라벨 산점도 (matplotlib 있을 때)
try:
    import matplotlib.pyplot as plt
    imp_pred = scorer.predict(texts, y_pred)
    imp_true = split.test["importance"].values
    plt.figure(figsize=(6, 6))
    plt.scatter(imp_true, imp_pred, alpha=0.6)
    plt.plot([0.3, 1.0], [0.3, 1.0], "r--", label="y=x")
    plt.xlabel("사람 라벨 importance")
    plt.ylabel("모델 예측 importance")
    plt.title(f"MAE={abs(imp_pred - imp_true).mean():.3f}")
    plt.legend()
    plt.savefig("outputs/reports/importance_scatter.png", dpi=120, bbox_inches="tight")
    print("저장 → outputs/reports/importance_scatter.png")
except ImportError:
    print("matplotlib 미설치, skip")

# %% 6. 단일 문장 추론 (운영 환경)
from src.predict import predict_one
from datetime import date

today = date(2026, 4, 27)
new_inputs = [
    "내일까지 동의서를 제출해 주세요",
    "5월 1일까지 글쓰기 대회 원고를 제출해 주세요",
    "방과후학교 수강료 25000원은 다음 달 5일 자동이체됩니다",
]
for text in new_inputs:
    out = predict_one(text, today=today)
    print(f"{out['category']:>6} | imp={out['importance']:.2f} | act={out['action_required']} | {text}")
