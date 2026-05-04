"""
split_dataset_v2_20260504.py
=============================
담당: 경이 (kyeongyi)
작성일: 2026-05-04

목적:
    notice_sample_v4_20260504.csv (695행 — 자동 라벨링으로 확장된 데이터)를
    train/val/test로 고정 분할하여 split_v2_20260504.csv 저장.

    베이스라인(Simple)과 KcELECTRA 파인튜닝이 '완전히 동일한 데이터'로
    학습·평가해야 공정한 비교가 가능하다.
    → 이 파일이 그 '공정한 기준점' 역할을 한다.

왜 v1과 별도로 v2를 만드나?
    split_v1.csv: 기존 244개 기준 분할 (KcELECTRA 실패의 원인)
    split_v2.csv: 695개 기준 분할 (KcELECTRA 재도전용)
    두 버전을 모두 유지해 '데이터 증가 전/후' 비교도 가능하게 함.

분할 전략:
    Stratified Split — 카테고리 비율을 유지하며 분할
    Train 80% / Val 10% / Test 10%
    Seed = 42

실행:
    cd model/classification
    python scripts/split_dataset_v2_20260504.py
    python scripts/split_dataset_v2_20260504.py --force   # 강제 재생성
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

_BASE    = Path(__file__).parent.parent
DATA_CSV = _BASE / "data" / "notice_sample_v4_20260504.csv"
OUT_CSV  = _BASE / "data" / "split_v2_20260504.csv"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]

TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
# TEST = 나머지 0.10

SEED = 42   # 고정 — 누가 실행해도 항상 동일한 분할


def stratified_split(df: pd.DataFrame) -> pd.DataFrame:
    """
    카테고리별로 동일 비율로 train/val/test를 나눈다.

    왜 Stratified가 필요한가?
      데이터가 695개로 늘었지만 카테고리별 수는 여전히 다르다.
      (일정 131, 준비물 80, 제출 136, 비용 98, 건강·안전 112, 기타 138)
      단순 랜덤 분할하면 특정 카테고리가 test에 몰리거나 빠질 수 있다.
      Stratified는 각 카테고리에서 동일 비율(80/10/10)로 뽑아
      모든 분할에서 클래스 분포를 유지한다.
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
        print(f"[split_v2] {OUT_CSV.name} 이미 존재합니다. 재생성하려면 --force 사용.")
        return

    if not DATA_CSV.exists():
        print(f"[오류] {DATA_CSV} 없음 — auto_label_from_new_data_20260504.py 먼저 실행하세요.")
        return

    df = pd.read_csv(DATA_CSV, encoding="utf-8-sig")
    df = df.dropna(subset=["text", "category"])
    df = df[df["category"].isin(LABELS)].copy()
    df = df.drop_duplicates(subset=["text"])

    print(f"[split_v2] 입력 데이터: {len(df)}개")

    df = stratified_split(df)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"[split_v2] 저장 완료: {OUT_CSV}")

    counts = df.groupby(["split", "category"]).size().unstack(fill_value=0)
    print("\n분할 결과 (split x category):")
    print(counts)
    print(f"\n전체: {len(df)}개")
    print(f"  train: {(df.split == 'train').sum()}개")
    print(f"  val:   {(df.split == 'val').sum()}개")
    print(f"  test:  {(df.split == 'test').sum()}개")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    main(force=args.force)
