"""
데이터셋 분할 스크립트 — 반드시 딱 한 번만 실행하세요!
=========================================================
담당: 경이
목적: 공정한 모델 비교를 위해 train/val/test를 한 번만 나누고
      split_v1.csv로 고정 저장. 이후 모든 모델(베이스라인·KcELECTRA)이
      동일한 분할을 사용.

실행:
    python scripts/split_dataset.py

생성 파일: data/split_v1.csv
  - 컬럼: text, category, split ("train" | "val" | "test")
  - 비율: train 80% / val 10% / test 10%
  - 시드: 42 (재현성 보장)
  - 전략: Stratified (각 카테고리에서 균등 비율 분리)

주의: split_v1.csv가 이미 존재하면 덮어쓰지 않습니다.
      강제 재생성이 필요하면 --force 옵션 사용.
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

_BASE = Path(__file__).parent.parent
DATA_CSV   = _BASE / "data" / "notice_sample_v3.csv"
LEGACY_CSV = _BASE / "data" / "notices_labeled_v2.csv"   # 기존 라벨 데이터 (원래 컬럼명: original_text)
SPLIT_CSV  = _BASE / "data" / "split_v1.csv"

LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]
TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
# TEST = 나머지 (0.10)

SEED = 42


def stratified_split(df: pd.DataFrame) -> pd.DataFrame:
    """카테고리별로 동일 비율 train/val/test 분리."""
    random.seed(SEED)

    split_labels: list[str] = []
    groups = defaultdict(list)

    for i, row in df.iterrows():
        groups[row["category"]].append(i)

    for category, indices in groups.items():
        random.shuffle(indices)
        n = len(indices)
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
    if SPLIT_CSV.exists() and not force:
        print(f"[split] {SPLIT_CSV} 이미 존재합니다. 재생성하려면 --force 사용.")
        return

    # 기본 데이터 + legacy 데이터 병합
    frames = [pd.read_csv(DATA_CSV)]
    if LEGACY_CSV.exists():
        legacy = pd.read_csv(LEGACY_CSV)
        # legacy CSV는 'original_text' 컬럼 사용
        if "original_text" in legacy.columns and "text" not in legacy.columns:
            legacy = legacy.rename(columns={"original_text": "text"})
        frames.append(legacy[["text", "category"]])
        print(f"[split] legacy 데이터 {len(legacy)}개 병합: {LEGACY_CSV.name}")

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["text", "category"])
    df = df[df["category"].isin(LABELS)].copy()
    df = df.drop_duplicates(subset=["text"])
    df["split"] = ""

    df = stratified_split(df)
    df.to_csv(SPLIT_CSV, index=False, encoding="utf-8-sig")

    print(f"[split] 저장 완료: {SPLIT_CSV}")
    counts = df.groupby(["split", "category"]).size().unstack(fill_value=0)
    print("\n분할 결과 (split × category):")
    print(counts)
    print(f"\n전체: {len(df)}개 → train: {(df.split=='train').sum()}, "
          f"val: {(df.split=='val').sum()}, test: {(df.split=='test').sum()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="기존 split_v1.csv 덮어쓰기")
    args = parser.parse_args()
    main(force=args.force)
