"""순수 numpy로 구현한 TF-IDF + char/word n-gram 토크나이저.

왜 sklearn 대신 직접?
- 이 코드는 샌드박스(scikit-learn 미설치)에서도 실제로 동작하는 데모를
  보여주기 위한 백업이다.
- production에서는 `classifier_sklearn.py`의 sklearn 파이프라인을 쓰면 된다.
- 동일한 인터페이스(`fit`, `transform`, `fit_transform`)로 만들었기 때문에
  나중에 sklearn으로 갈아끼우는 것도 쉽다.

한국어 특화 포인트
------------------
1. char n-gram (2~4)을 메인으로 쓴다. 한국어는 띄어쓰기가 일관되지 않고
   조사가 붙어 어휘가 폭발하기 때문에 문자 n-gram이 더 강력하다.
2. word(공백 분리) 1-gram을 보조로 더해 의미 단위 신호도 잡는다.
3. sublinear_tf (1+log(tf))를 쓴다. 짧은 학교 안내문에서 같은 단어 반복은
   드물지만, 긴 문장의 흔한 단어(예: '제출')가 과도하게 가중되는 것을
   완화한다.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

import numpy as np


def char_ngrams(text: str, ns: Iterable[int] = (2, 3, 4)) -> list[str]:
    """문자 n-gram. 공백은 '_'로 치환해서 단어 경계를 보존."""
    if not text:
        return []
    s = re.sub(r"\s+", "_", text)
    out: list[str] = []
    for n in ns:
        if len(s) < n:
            continue
        out.extend(s[i : i + n] for i in range(len(s) - n + 1))
    return out


def word_tokens(text: str) -> list[str]:
    """매우 단순한 공백 분리 + 길이 1 토큰 제거.

    형태소 분석기(konlpy 등)를 쓰면 더 좋지만 환경 종속성이 커서 제외.
    char n-gram이 이미 형태소를 어느 정도 흉내내므로 보조 정도면 충분.
    """
    return [w for w in re.split(r"\s+", text) if len(w) > 1]


def tokenize(text: str) -> list[str]:
    """char n-gram + word 1-gram을 prefix를 붙여 합친다.

    prefix는 같은 토큰이라도 char/word 출처를 구분하기 위함이다.
    예: 'c:제출', 'w:제출해'
    """
    chs = char_ngrams(text)
    ws = word_tokens(text)
    return [f"c:{t}" for t in chs] + [f"w:{t}" for t in ws]


# ------------------------------------------------------------------------------
# TF-IDF 벡터라이저 (numpy)
# ------------------------------------------------------------------------------
class TfidfVectorizer:
    """sklearn TfidfVectorizer를 numpy로 축약 구현.

    핵심 동작:
    - fit: 토큰별 document frequency(df) 집계 → idf = log((1+N)/(1+df)) + 1
    - transform: 문서별 sublinear tf(1+log(tf)) * idf, 그리고 L2 정규화
    """

    def __init__(self, min_df: int = 2, max_features: int | None = 50000):
        self.min_df = min_df
        self.max_features = max_features
        self.vocab_: dict[str, int] = {}
        self.idf_: np.ndarray = np.array([])

    def fit(self, texts: list[str]) -> "TfidfVectorizer":
        df = Counter()
        for t in texts:
            for tok in set(tokenize(t)):
                df[tok] += 1
        items = [(tok, c) for tok, c in df.items() if c >= self.min_df]
        items.sort(key=lambda x: (-x[1], x[0]))  # 빈도 많은 순
        if self.max_features:
            items = items[: self.max_features]
        self.vocab_ = {tok: i for i, (tok, _) in enumerate(items)}
        N = len(texts)
        self.idf_ = np.zeros(len(self.vocab_), dtype=np.float32)
        for tok, idx in self.vocab_.items():
            self.idf_[idx] = float(np.log((1 + N) / (1 + df[tok])) + 1.0)
        return self

    def transform(self, texts: list[str]) -> np.ndarray:
        V = len(self.vocab_)
        out = np.zeros((len(texts), V), dtype=np.float32)
        for i, t in enumerate(texts):
            tf = Counter(tokenize(t))
            for tok, count in tf.items():
                idx = self.vocab_.get(tok)
                if idx is None:
                    continue
                out[i, idx] = (1.0 + np.log(count)) * self.idf_[idx]
            # L2 정규화 (코사인 분류에 유리)
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out

    def fit_transform(self, texts: list[str]) -> np.ndarray:
        self.fit(texts)
        return self.transform(texts)
