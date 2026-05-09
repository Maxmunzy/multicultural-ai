"""
split_dataset_v3_1_20260509.py
================================
담당: 경이 (kyeongyi)
작성일: 2026-05-09

목적:
    notice_sample_v6_2_20260509.csv (15948행)를
    train/val/test로 고정 분할하여 split_v3_1_20260509.csv 저장.

    v3_1 변경점 (v6 대비):
      전체 15948행 (v6: 5412행, 약 3배 증가)
      기타  : 7410 (46.5%)
      제출  : 3158 (19.8%)
      건강·안전: 2147 (13.5%)
      일정  : 1940 (12.2%)
      비용  :  846 (5.3%)
      준비물:  447 (2.8%)

분할 전략:
    Stratified Split (카테고리 비율 유지)
    Train 80% / Val 10% / Test 10%
    Seed = 42

실행:
    cd model/classification
    python scripts/split_dataset_v3_1_20260509.py
    python scripts/split_dataset_v3_1_20260509.py --force
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

_BASE    = Path(__file__).parent.parent
DATA_CSV = _BASE / "data" / "20260509" / "notice_sample_v6_2_20260509.csv"
OUT_CSV  = _BASE / "data" / "split_v3_1_20260509.csv"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]

TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
SEED        = 42


def stratified_split(df: pd.DataFrame) -> pd.DataFrame:
    random.seed(SEED)
    df = df.copy()
    df["split"] = ""

    groups: defaultdict[str, list] = defaultdict(list)
    for i, row in df.iterrows():
        groups[row["category"]].append(i)

    for category, indices in groups.items():
        random.shuffle(indices)
        n       = len(indices)
        n_train = max(1, round(n * TRAIN_RATIO))
        n_val   = max(1, round(n * VAL_RATIO))

        for j, idx in enumerate(indices):
            if j < n_train:
                df.at[idx, "split"] = "train"
            elif j < n_train + n_val:
                df.at[idx, "split"] = "val"
            else:
                df.at[idx, "split"] = "test"

    return df


def main(force: bool = False) -> None:
    if OUT_CSV.exists() and not force:
        print(f"[split_v3_1] {OUT_CSV.name} 이미 존재합니다. 재생성하려면 --force 사용.")
        return

    if not DATA_CSV.exists():
        print(f"[오류] {DATA_CSV} 없음")
        return

    df = pd.read_csv(DATA_CSV, encoding="utf-8-sig")
    df = df.dropna(subset=["text", "category"])
    df = df[df["category"].isin(LABELS)].copy()
    df = df.drop_duplicates(subset=["text"])

    print(f"[split_v3_1] 입력 데이터: {len(df)}개 (중복 제거 후)")
    print("\n카테고리 분포:")
    for lbl in LABELS:
        cnt = (df["category"] == lbl).sum()
        pct = cnt / len(df) * 100
        print(f"  {lbl:8s}: {cnt:5d}개  ({pct:.1f}%)")

    df = stratified_split(df)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n[split_v3_1] 저장 완료: {OUT_CSV.name}")
    counts = df.groupby(["split", "category"]).size().unstack(fill_value=0)
    print("\n분할 결과 (split x category):")
    print(counts)
    print(f"\n전체: {len(df)}개")
    print(f"  train: {(df.split == 'train').sum():5d}개")
    print(f"  val  : {(df.split == 'val').sum():5d}개")
    print(f"  test : {(df.split == 'test').sum():5d}개")

    print(f"\n[참고] v6 대비 증가:")
    v6_total = 5412
    print(f"  v6 총계: {v6_total}개  →  v3_1 총계: {len(df)}개  (+{len(df) - v6_total}개, {(len(df)/v6_total - 1)*100:.0f}% 증가)")

    print("\n클래스 가중치 (train 기준 - 11_train_kcelectra_v3_1 셀 6 참고):")
    train_df = df[df["split"] == "train"]
    total = len(train_df)
    for lbl in LABELS:
        cnt = (train_df["category"] == lbl).sum()
        w = total / (len(LABELS) * cnt)
        print(f"  {lbl:8s}: {cnt:5d}개  가중치={w:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    main(force=args.force)
