"""
merge_split_v4_schoolalimi_20260525.py

기존 v3_1 데이터(15,948행)에 학교알리미 공공데이터 기반 증강 데이터를 병합하여
v4 학습/검증/테스트 분할 CSV를 생성한다.

병합 전략:
  - test 세트: 기존 v3_1 test (1,593행) 그대로 유지
    → v3_2 vs v4 모델을 동일 test 세트로 공정 비교 가능
  - 증강 데이터(schoolalimi_augment_20260525.csv)는 train/val에만 추가
    → 공공데이터 활용 효과를 모델 성능 향상으로 직접 측정

출력:
  data/split_v4_schoolalimi_20260525.csv  (text, category, split, source)

실행:
  python scripts/merge_split_v4_schoolalimi_20260525.py
"""

import pandas as pd
from pathlib import Path

SEED = 42
BASE = Path(__file__).resolve().parent.parent

V3_SPLIT   = BASE / "data" / "split_v3_1_20260509.csv"
AUGMENT    = BASE / "data" / "20260525" / "schoolalimi_augment_20260525.csv"
OUT_PATH   = BASE / "data" / "split_v4_schoolalimi_20260525.csv"


def main():
    # ── v3_1 원본 로드 ──────────────────────────────────────────
    orig = pd.read_csv(V3_SPLIT, encoding="utf-8-sig")
    orig["source"] = "original"

    print(f"[v3_1 원본] {len(orig)}행")
    print(orig["split"].value_counts().to_string())
    print()

    # ── 증강 데이터 로드 ─────────────────────────────────────────
    aug = pd.read_csv(AUGMENT, encoding="utf-8-sig")

    # train 80% / val 20% 분할 (test는 기존 v3_1만 사용)
    aug_shuffled = aug.sample(frac=1, random_state=SEED).reset_index(drop=True)
    n_aug_train  = int(len(aug_shuffled) * 0.8)

    aug_shuffled["split"] = "val"
    aug_shuffled.iloc[:n_aug_train, aug_shuffled.columns.get_loc("split")] = "train"

    print(f"[증강 데이터] {len(aug_shuffled)}행 (train: {n_aug_train}, val: {len(aug_shuffled)-n_aug_train})")
    print(aug_shuffled["category"].value_counts().to_string())
    print()

    # ── 병합 ────────────────────────────────────────────────────
    aug_for_merge = aug_shuffled[["text", "category", "split", "source"]]
    orig_v4 = orig.copy()

    merged = pd.concat([orig_v4, aug_for_merge], ignore_index=True)
    merged = merged.sample(frac=1, random_state=SEED).reset_index(drop=True)

    # ── 통계 출력 ────────────────────────────────────────────────
    print(f"[v4 병합 결과] 총 {len(merged)}행")
    print("\n분할별 행 수:")
    print(merged["split"].value_counts().to_string())
    print("\n카테고리 분포 (전체):")
    print(merged["category"].value_counts().to_string())

    train_df = merged[merged["split"] == "train"]
    print(f"\n[Train 카테고리 분포] ({len(train_df)}행)")
    for cat, cnt in train_df["category"].value_counts().items():
        pct = cnt / len(train_df) * 100
        # 기존 v3_1 train 수 비교
        orig_train = orig[orig["split"] == "train"]
        orig_cnt = (orig_train["category"] == cat).sum()
        added = cnt - orig_cnt
        sign = f"+{added}" if added > 0 else str(added)
        print(f"  {cat:8s}: {cnt:5d}개 ({pct:.1f}%)  [v3_1 대비 {sign}]")

    # ── 저장 ────────────────────────────────────────────────────
    merged.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[저장] {OUT_PATH}")

    # ── 검증: test 세트 동일성 확인 ─────────────────────────────
    v4_test = merged[merged["split"] == "test"][["text", "category"]].sort_values("text").reset_index(drop=True)
    v3_test = orig[orig["split"] == "test"][["text", "category"]].sort_values("text").reset_index(drop=True)
    assert len(v4_test) == len(v3_test), "test 크기 불일치!"
    assert (v4_test["text"] == v3_test["text"]).all(), "test text 불일치!"
    print("[OK] test 세트 동일성 확인 - v3_2와 동일 test로 공정 비교 가능")


if __name__ == "__main__":
    main()
