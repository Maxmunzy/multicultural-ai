"""
split_dataset_v6_20260506.py
=============================
담당: 경이 (kyeongyi)
작성일: 2026-05-06

목적:
    notice_sample_v6_clean_full_20260505_1.csv (5412행)를
    train/val/test로 고정 분할하여 split_v6_20260506.csv 저장.

    v6 vs v5 변경점:
      기타  : 788 → 1088 (+300)
      비용  : 322 → 382  (+60)
      준비물: 219 → 279  (+60)
      합계  : 4992 → 5412 (+420)

분할 전략:
    Stratified Split (카테고리 비율 유지)
    Train 80% / Val 10% / Test 10%
    Seed = 42

실행:
    cd model/classification
    python scripts/split_dataset_v6_20260506.py
    python scripts/split_dataset_v6_20260506.py --force
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

_BASE    = Path(__file__).parent.parent
DATA_CSV = _BASE / "data" / "notice_sample_v6_clean_full_20260505_1.csv"
OUT_CSV  = _BASE / "data" / "split_v6_20260506.csv"

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
        print(f"[split_v6] {OUT_CSV.name} 이미 존재합니다. 재생성하려면 --force 사용.")
        return

    if not DATA_CSV.exists():
        print(f"[오류] {DATA_CSV} 없음")
        return

    df = pd.read_csv(DATA_CSV, encoding="utf-8-sig")
    df = df.dropna(subset=["text", "category"])
    df = df[df["category"].isin(LABELS)].copy()
    df = df.drop_duplicates(subset=["text"])

    print(f"[split_v6] 입력 데이터: {len(df)}개 (중복 제거 후)")
    print("\n카테고리 분포:")
    for lbl in LABELS:
        cnt = (df["category"] == lbl).sum()
        print(f"  {lbl:8s}: {cnt:4d}개")

    df = stratified_split(df)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n[split_v6] 저장 완료: {OUT_CSV.name}")
    counts = df.groupby(["split", "category"]).size().unstack(fill_value=0)
    print("\n분할 결과 (split x category):")
    print(counts)
    print(f"\n전체: {len(df)}개")
    print(f"  train: {(df.split == 'train').sum():4d}개")
    print(f"  val  : {(df.split == 'val').sum():4d}개")
    print(f"  test : {(df.split == 'test').sum():4d}개")
    print(f"\n[참고] v5 대비 train 데이터 증가량:")
    v5_train = round(4992 * TRAIN_RATIO)
    v6_train = (df.split == "train").sum()
    print(f"  v5 train: {v5_train}개  →  v6 train: {v6_train}개  (+{v6_train - v5_train}개)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    main(force=args.force)
