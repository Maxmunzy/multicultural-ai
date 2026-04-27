"""전역 설정. 카테고리 라벨, 경로, 학습 하이퍼파라미터를 한 곳에서 관리한다.

이렇게 분리하는 이유:
- 데이터 라벨 체계가 바뀌어도(`기타` 정의 변경 등) 코드 수정이 한 파일로 끝난다.
- 다른 모듈에서 동일한 LABELS 순서를 참조하기 때문에 confusion matrix /
  one-hot 인코딩이 항상 일관된다 (라벨 순서가 어긋나면 평가가 무의미해짐).
- 태수님 백엔드(`services/classifier.py`)도 이 파일만 import 하면 된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# --- 경로 설정 -----------------------------------------------------------------
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
OUTPUT_DIR: Final[Path] = PROJECT_ROOT / "outputs"
MODEL_DIR: Final[Path] = OUTPUT_DIR / "models"
REPORT_DIR: Final[Path] = OUTPUT_DIR / "reports"
PRED_DIR: Final[Path] = OUTPUT_DIR / "predictions"

for _d in (MODEL_DIR, REPORT_DIR, PRED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- 라벨 체계 -----------------------------------------------------------------
# README의 6개 카테고리. 순서가 평가/저장의 표준이 되므로 절대 바꾸지 말 것.
LABELS: Final[tuple[str, ...]] = (
    "일정",       # 0 - 현장학습, 운동회, 평가 등 날짜성 정보
    "준비물",     # 1 - 도시락, 실내화, 체육복 등 가져올 물건
    "제출",       # 2 - 동의서/신청서/조사서/확인서/활동지 (가장 중요한 그룹)
    "비용",       # 3 - 급식비, 참가비, 자동이체 안내
    "건강·안전",  # 4 - 감염병, 미세먼지, 안전교육
    "기타",       # 5 - 위 5개에 안 잡히는 일반 안내
)
LABEL2ID: Final[dict[str, int]] = {l: i for i, l in enumerate(LABELS)}
ID2LABEL: Final[dict[int, str]] = {i: l for i, l in enumerate(LABELS)}

# 윤정님 데이터에 가끔 다른 표기가 들어와도 정상화하기 위한 동의어 사전
LABEL_ALIASES: Final[dict[str, str]] = {
    "건강안전": "건강·안전",
    "건강 안전": "건강·안전",
    "건강/안전": "건강·안전",
    "안전": "건강·안전",
    "건강": "건강·안전",
    "준비": "준비물",
    "제출물": "제출",
    "기타사항": "기타",
}

# --- 카테고리별 기본 중요도 (룰 베이스) ---------------------------------------
# README 기준을 카테고리 prior로 쓴다. 시급도(urgency) 가산이 더해진다.
CATEGORY_BASE_IMPORTANCE: Final[dict[str, float]] = {
    "제출":       0.85,  # 동의서/신청서: 기본적으로 행동 필요
    "준비물":     0.80,  # 가져갈 것: 까먹으면 문제
    "건강·안전":  0.75,  # 안전 관련: 중요하지만 가정 행동 강도는 다양
    "일정":       0.70,  # 날짜 확인: 행동 강도 중간
    "비용":       0.75,  # 자동이체면 N, 직접 납부면 Y
    "기타":       0.45,  # 일반 공지: 낮은 베이스
}

# --- 학습 하이퍼파라미터 -------------------------------------------------------
RANDOM_STATE: Final[int] = 42
TEST_SIZE: Final[float] = 0.2
VAL_SIZE: Final[float] = 0.1  # train 안에서 다시 잘라 검증용

# 권장 SBERT 임베딩 모델 (CPU에서도 빠른 것부터)
SBERT_MODELS: Final[tuple[str, ...]] = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",  # 50MB 가장 가벼움
    "jhgan/ko-sroberta-multitask",                                  # 한국어 특화 권장
    "BM-K/KoSimCSE-roberta",                                        # 한국어 STS 강함
)

# KoBERT/Qwen 옵션 모델
KOBERT_MODEL: Final[str] = "monologg/kobert"
KOELECTRA_MODEL: Final[str] = "monologg/koelectra-base-v3-discriminator"
QWEN_SMALL: Final[str] = "Qwen/Qwen2.5-0.5B"  # CPU에서도 LoRA 가능한 최소 사이즈

# 중요도 회귀 모델 가중치 (룰 vs 학습된 회귀)
# 데이터가 200건 정도일 때는 룰을 약간 더 신뢰하는 게 안전하다.
IMPORTANCE_RULE_WEIGHT: Final[float] = 0.45
IMPORTANCE_MODEL_WEIGHT: Final[float] = 0.55

# 추론 시 빈 칸으로 인식할 값 (notice_sample_v2.csv에서 비어있는 셀 식별)
EMPTY_SENTINELS: Final[tuple[str, ...]] = ("", "nan", "NaN", "None", "null", "-")
