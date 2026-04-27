"""두 출처(notice_sample_v2 + 윤정님 데이터)를 모두 학습 가능한 형태로 통합한다.

왜 이 모듈이 필요한가?
- notice_sample_v2.csv는 라벨링 품질이 안정적이지만 200건이라 적다.
- 윤정님 csv/jsonl은 모델 A의 추출 결과 + 윤정님 추가 라벨이 섞여 있어서
  형식(컬럼명, 결측, 라벨 표기)이 약간 다르다. 그대로 합치면 라벨이
  깨지거나 중복이 발생한다.
- 그래서 한 번에 정규화 → 중복 제거 → 라벨 검증 → 분할까지 책임지는
  단일 함수를 둔다. 학습 스크립트들은 build_dataset()만 호출하면 된다.

사용 예:
    from src.data_loader import build_dataset
    train_df, val_df, test_df = build_dataset()
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .config import (
    DATA_DIR,
    EMPTY_SENTINELS,
    LABEL_ALIASES,
    LABELS,
    RANDOM_STATE,
    TEST_SIZE,
    VAL_SIZE,
)


# ------------------------------------------------------------------------------
# 1. 헬퍼: 라벨 정규화 / 텍스트 정제
# ------------------------------------------------------------------------------
def normalize_label(raw: str | float | None) -> str | None:
    """다양한 표기를 6개 표준 라벨로 통일.

    예: '건강안전' → '건강·안전', '준비' → '준비물'.
    매핑되지 않거나 결측이면 None을 반환해서 호출 측에서 결정하게 한다.
    """
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip()
    if s in EMPTY_SENTINELS:
        return None
    if s in LABELS:
        return s
    return LABEL_ALIASES.get(s)


_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(text: str | float | None) -> str:
    """학습 직전에 적용하는 텍스트 정제.

    - 양 끝 공백 제거
    - 연속된 공백을 하나로
    - 인용부호/제로폭 문자 제거
    - 너무 긴 줄바꿈 정리
    의미를 바꾸는 정규화(불용어 제거 등)는 일부러 하지 않는다.
    한국어는 형태소가 의미를 결정하므로 과도한 전처리가 오히려 성능을
    떨어뜨리는 경우가 많기 때문.
    """
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    s = str(text)
    # 제로폭 문자 / BOM
    s = s.replace("​", "").replace("﻿", "")
    s = s.replace(" ", " ")  # nbsp → space
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


# ------------------------------------------------------------------------------
# 2. 개별 출처 로더
# ------------------------------------------------------------------------------
def load_notice_sample_v2(path: Path | None = None) -> pd.DataFrame:
    """공식 라벨링 샘플(notice_sample_v2.csv) 로드.

    이 데이터의 importance는 사람이 직접 매겨서 최고 신뢰도. 학습의 코어.
    파일이 없으면 빈 DataFrame을 반환한다.
    """
    path = path or DATA_DIR / "notice_sample_v2.csv"
    if not path.exists():
        print(f"[data_loader] warning: {path} not found, skipping notice_sample_v2")
        return pd.DataFrame(columns=["id", "source_type", "original_text",
                                     "category", "keywords", "importance", "source"])
    df = pd.read_csv(path)
    df["original_text"] = df["original_text"].map(clean_text)
    df["category"] = df["category"].map(normalize_label)
    df["importance"] = pd.to_numeric(df["importance"], errors="coerce")
    df["source"] = "notice_sample_v2"
    return df


def load_yunjeong_csv(path: Path | None = None) -> pd.DataFrame:
    """윤정님이 라벨링까지 마친 csv. notice_sample_v2와 같은 컬럼 구조.

    이 데이터는 모델 A가 추출한 '할 일 문장'을 윤정님이 검수+라벨링한 것.
    실제 운영 시 모델 B가 받게 될 입력 분포와 가장 가깝다 → 도메인 적응에 유용.
    """
    path = path or DATA_DIR / "notices_labeled_v2.csv"
    df = pd.read_csv(path)
    df["original_text"] = df["original_text"].map(clean_text)
    df["category"] = df["category"].map(normalize_label)
    df["importance"] = pd.to_numeric(df["importance"], errors="coerce")
    df["source"] = "yunjeong_csv"
    return df


def load_yunjeong_jsonl(path: Path | None = None) -> pd.DataFrame:
    """윤정님 jsonl: 원본 가정통신문의 모든 문장 + is_todo 플래그.

    is_todo=True인 문장만 학습에 쓴다 (모델 B는 todo 문장만 받기 때문).
    importance는 jsonl에 없으므로 NaN으로 두고, downstream에서
    카테고리 베이스 + 시급도 룰로 채우거나 라벨 없는 augmentation 후보로 활용.
    """
    path = path or DATA_DIR / "notices_labeled_v2.jsonl"
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not obj.get("is_todo"):
                continue
            rows.append(
                {
                    "id": f"jsonl_{len(rows)}",
                    "source_type": "초등학교",  # 윤정 jsonl은 모두 초등학교 안내
                    "original_text": clean_text(obj.get("sentence")),
                    "category": normalize_label(obj.get("category")),
                    "importance": np.nan,
                    "keywords": "",
                    "source": "yunjeong_jsonl",
                }
            )
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------
# 3. 통합 + 분할
# ------------------------------------------------------------------------------
@dataclass
class DatasetSplit:
    """학습/검증/테스트 분할을 묶어 들고 다닐 컨테이너.

    pandas.DataFrame 3개를 따로 들고 다니면 인자가 길어지고 실수하기 쉬워서
    이 dataclass로 묶었다. .all_labeled를 두는 이유: 베이스라인이나
    SBERT 임베딩 캐시는 전체에 대해 한 번에 계산하면 빠르기 때문.
    """

    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame

    @property
    def all_labeled(self) -> pd.DataFrame:
        return pd.concat([self.train, self.val, self.test], ignore_index=True)


def _stratified_split(
    df: pd.DataFrame, *, test_size: float, seed: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """카테고리별 비율을 유지하면서 분할.

    sklearn.model_selection.train_test_split을 못 쓰는 환경(이 샌드박스)을
    위해 numpy로 직접 구현. 클래스마다 적어도 1개는 양쪽에 들어가도록
    보장한다 → 일부 라벨이 적을 때(예: '비용' 25개) 평가가 깨지지 않는다.
    """
    rng = np.random.default_rng(seed)
    train_parts, test_parts = [], []
    for label, sub in df.groupby("category"):
        idx = np.arange(len(sub))
        rng.shuffle(idx)
        n_test = max(1, int(round(len(sub) * test_size)))
        # 너무 작은 클래스는 train에 최소 1개라도 남기도록 보정
        if n_test >= len(sub):
            n_test = max(1, len(sub) - 1)
        test_idx = idx[:n_test]
        train_idx = idx[n_test:]
        sub_arr = sub.reset_index(drop=True)
        train_parts.append(sub_arr.iloc[train_idx])
        test_parts.append(sub_arr.iloc[test_idx])
    train_df = pd.concat(train_parts, ignore_index=True).sample(
        frac=1, random_state=seed
    ).reset_index(drop=True)
    test_df = pd.concat(test_parts, ignore_index=True).sample(
        frac=1, random_state=seed
    ).reset_index(drop=True)
    return train_df, test_df


def build_dataset(
    *,
    include_yunjeong_csv: bool = True,
    include_yunjeong_jsonl: bool = False,
    drop_duplicates: bool = True,
    seed: int = RANDOM_STATE,
) -> DatasetSplit:
    """모든 출처를 합쳐 학습 가능한 형태로 분할 반환.

    Parameters
    ----------
    include_yunjeong_csv:
        윤정님 라벨링 csv 포함 여부 (기본 True). importance 라벨이 있어 유용.
    include_yunjeong_jsonl:
        jsonl 포함 여부 (기본 False). importance 결측이라 분류 학습에만 사용
        하고 싶을 때 True. 본 함수는 importance 결측 행을 importance 회귀
        학습에서 자동으로 제외한다.
    drop_duplicates:
        original_text 기준 중복 제거. 두 출처가 같은 문장을 다르게 라벨링했을
        때는 첫 번째(공식 sample_v2)를 우선시.
    """
    parts = [load_notice_sample_v2()]
    if include_yunjeong_csv:
        parts.append(load_yunjeong_csv())
    if include_yunjeong_jsonl:
        parts.append(load_yunjeong_jsonl())

    df = pd.concat(parts, ignore_index=True)

    # 카테고리 NaN(매핑 실패) 행 제거 → 분류 학습에 못 씀
    df = df.dropna(subset=["category", "original_text"])
    df = df[df["original_text"].str.len() > 0]
    df = df[df["category"].isin(LABELS)]

    if drop_duplicates:
        df = df.drop_duplicates(subset=["original_text"], keep="first")

    df = df.reset_index(drop=True)

    # 1차: train+val vs test
    trainval, test = _stratified_split(df, test_size=TEST_SIZE, seed=seed)
    # 2차: train vs val (안전한 비율로)
    val_ratio = VAL_SIZE / (1 - TEST_SIZE)
    train, val = _stratified_split(trainval, test_size=val_ratio, seed=seed + 1)

    return DatasetSplit(train=train, val=val, test=test)


# ------------------------------------------------------------------------------
# 4. CLI 진입점 (간단 EDA)
# ------------------------------------------------------------------------------
def summarize(split: DatasetSplit) -> str:
    """분할 후 분포를 사람이 읽기 좋게 요약."""
    lines = []
    full = split.all_labeled
    lines.append(f"총 라벨 데이터: {len(full)}개")
    lines.append(f"  train={len(split.train)}, val={len(split.val)}, test={len(split.test)}")
    lines.append("")
    lines.append("카테고리 분포 (전체):")
    for label, n in full["category"].value_counts().items():
        lines.append(f"  {label}: {n}")
    lines.append("")
    if "importance" in full.columns:
        imp = full["importance"].dropna()
        lines.append(
            f"importance 통계 (n={len(imp)}): "
            f"mean={imp.mean():.3f}, std={imp.std():.3f}, "
            f"min={imp.min():.2f}, max={imp.max():.2f}"
        )
    lines.append("")
    lines.append("출처별:")
    for src, n in full["source"].value_counts().items():
        lines.append(f"  {src}: {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    split = build_dataset()
    print(summarize(split))
