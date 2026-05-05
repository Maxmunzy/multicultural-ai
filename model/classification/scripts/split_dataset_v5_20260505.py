"""
split_dataset_v5_20260505.py
=============================
담당: 경이 (kyeongyi)
작성일: 2026-05-05

목적:
    notice_sample_v5_clean_full_20260504.csv (4992행 - 이미 라벨링 완료 데이터)를
    train/val/test로 고정 분할하여 split_v5_20260505.csv 저장.

    v5 데이터는 이미 정답 라벨이 존재하므로 자동 라벨링 없이 바로 사용 가능.
    베이스라인(Simple)과 KcELECTRA v3 파인튜닝이 '완전히 동일한 데이터'로
    학습·평가해야 공정한 비교가 가능하다.

v5 vs v4 비교:
    v4: 695행 (자동 라벨링, 노이즈 포함 가능성)
    v5: 4992행 (수동 라벨링 완료, 7배 이상 데이터) - KcELECTRA가 잘 학습될 최소 규모 확보

분할 전략:
    Stratified Split - 카테고리 비율을 유지하며 분할
    Train 80% / Val 10% / Test 10%
    Seed = 42

실행:
    cd model/classification
    python scripts/split_dataset_v5_20260505.py
    python scripts/split_dataset_v5_20260505.py --force   # 강제 재생성
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

_BASE    = Path(__file__).parent.parent
DATA_CSV = _BASE / "data" / "notice_sample_v5_clean_full_20260504.csv"
OUT_CSV  = _BASE / "data" / "split_v5_20260505.csv"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]

TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
# TEST = 나머지 0.10

SEED = 42


def stratified_split(df: pd.DataFrame) -> pd.DataFrame:
    """
    카테고리별로 동일 비율로 train/val/test를 나눈다.

    v5 클래스 분포 (4992행):
      일정 ~1469, 건강·안전 ~1268, 제출 ~926, 기타 ~788, 준비물 ~322, 비용 ~219
    준비물·비용이 상대적으로 적으므로 Stratified가 특히 중요.
    """
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
        print(f"[split_v5] {OUT_CSV.name} 이미 존재합니다. 재생성하려면 --force 사용.")
        return

    if not DATA_CSV.exists():
        print(f"[오류] {DATA_CSV} 없음 - notice_sample_v5_clean_full_20260504.csv를 확인하세요.")
        return

    df = pd.read_csv(DATA_CSV, encoding="utf-8-sig")
    df = df.dropna(subset=["text", "category"])
    df = df[df["category"].isin(LABELS)].copy()
    df = df.drop_duplicates(subset=["text"])

    print(f"[split_v5] 입력 데이터: {len(df)}개 (중복 제거 후)")
    print("\n카테고리 분포:")
    for lbl in LABELS:
        cnt = (df["category"] == lbl).sum()
        print(f"  {lbl:8s}: {cnt:4d}개")

    df = stratified_split(df)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n[split_v5] 저장 완료: {OUT_CSV}")

    counts = df.groupby(["split", "category"]).size().unstack(fill_value=0)
    print("\n분할 결과 (split x category):")
    print(counts)
    print(f"\n전체: {len(df)}개")
    print(f"  train: {(df.split == 'train').sum():4d}개")
    print(f"  val:   {(df.split == 'val').sum():4d}개")
    print(f"  test:  {(df.split == 'test').sum():4d}개")
    print("\n[참고] v4 대비 train 데이터 증가량:")
    print(f"  v4 train: 556개  →  v5 train: {(df.split == 'train').sum()}개  ({(df.split == 'train').sum() / 556:.1f}배 증가)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    main(force=args.force)
