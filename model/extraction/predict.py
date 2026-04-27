"""
model/extraction/predict.py
============================
가정통신문 → TodoItem 리스트 추출 (경로 B 하이브리드)

담당:   윤정
구조:   문장 분리 → 정규식 추출 → KoELECTRA 카테고리 분류 → importance 계산
출력:   schemas.py 의 TodoItem 과 100% 호환

─────────────────────────────────────────
파이프라인
─────────────────────────────────────────
가정통신문 텍스트
    ↓
[1] split_sentences()       문장 단위로 나눔
    ↓
[2] is_likely_todo()        안부인사·서명 등 1차 제외
    ↓
[3] extract_due_date()      정규식: 날짜·마감 추출
    ↓
[4] classify_category()     KoELECTRA: 5개 카테고리 분류 + 비용은 정규식
    ↓
[5] calc_importance()       카테고리 + due_date + 키워드 → 점수
    ↓
TodoItem 리스트
─────────────────────────────────────────
"""

import os
import sys
import re
import json
from typing import Optional

import torch
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
)
# ─────────────────────────────────────────
# 0. schemas.py 임포트
# ─────────────────────────────────────────
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "backend/app/models"))

try:
    from schemas import TodoItem, Category   # type: ignore
    SCHEMAS_AVAILABLE = True
except ImportError:
    SCHEMAS_AVAILABLE = False
    TodoItem = None
    Category = None


# ─────────────────────────────────────────
# 1. 모델 로드 (서버 시작 시 1회, lazy)
# ─────────────────────────────────────────
HF_REPO_ID = "yunjeong116/koelectra-extractor"
HF_SUBFOLDER = "koelectra-extractor"
LOCAL_CHECKPOINT_DIR = os.path.join(
    os.path.dirname(__file__), "checkpoints/koelectra-extractor"
)

_tokenizer = None
_model = None
_id2label = None
_device = "cuda" if torch.cuda.is_available() else "cpu"


def _load_model():
    """첫 호출 때만 모델 로드. 로컬 가중치 있으면 로컬, 없으면 HF Hub."""
    global _tokenizer, _model, _id2label
    if _model is not None:
        return

    if os.path.exists(os.path.join(LOCAL_CHECKPOINT_DIR, "pytorch_model.bin")):
        load_kwargs = {"pretrained_model_name_or_path": LOCAL_CHECKPOINT_DIR}
        labels_path = os.path.join(LOCAL_CHECKPOINT_DIR, "labels.json")
    else:
        load_kwargs = {
            "pretrained_model_name_or_path": HF_REPO_ID,
            "subfolder": HF_SUBFOLDER,
        }
        from huggingface_hub import hf_hub_download
        labels_path = hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=f"{HF_SUBFOLDER}/labels.json",
        )

    _tokenizer = AutoTokenizer.from_pretrained(**load_kwargs)
    _model = AutoModelForSequenceClassification.from_pretrained(**load_kwargs)
    _model.to(_device)
    _model.eval()

    with open(labels_path, encoding="utf-8") as f:
        meta = json.load(f)
    _id2label = {int(k): v for k, v in meta["id2label"].items()}


# ─────────────────────────────────────────
# 2. 문장 분리
#
# 가정통신문은 문장 끝이 다양해서 단순 . split 안 됨.
# 한국어 종결어미 + 줄바꿈 + 번호 항목 시작점 모두 고려.
# ─────────────────────────────────────────
def split_sentences(text: str) -> list[str]:
    """가정통신문 전체 텍스트를 문장 리스트로 분리"""
    # 먼저 줄바꿈 단위로 자르고, 각 줄을 다시 문장 단위로 자른다
    # (가정통신문은 한 줄 = 한 항목인 경우가 많음)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    sentences = []
    for line in lines:
        # 마침표/물음표/느낌표 + 공백 → 문장 끝
        # 한국어 종결 어미(다./요./니다./까?) + 공백 → 문장 끝
        # 번호 항목(1., 2)) 시작 직전 → 문장 끝
        parts = re.split(
            r"(?<=[.!?])\s+|"
            r"(?<=다\.)\s+|(?<=요\.)\s+|(?<=니다\.)\s+|"
            r"(?<=까\?)\s+|(?<=요\?)\s+|"
            r"\s+(?=\d+[.)]\s)|\s+(?=[가-힣]\.\s)",
            line,
        )
        sentences.extend(parts)

    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]


# ─────────────────────────────────────────
# 3. 1차 필터 (안부인사·서명 등 빠르게 제외)
# ─────────────────────────────────────────
NON_TODO_PATTERNS = [
    r"^학부모님\s*안녕하십니까",
    r"^안녕하십니까",
    r"서울갈산초등학교장$",
    r"교장$",
    r"^\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*$",
    r"담당\s*[:：]",
    r"^\(.\s*\d{4}-\d{4}",
    r"^08\d{3}\s*서울특별시",
    r"공익제보센터",
    r"자살예방상담",
    r"청소년상담",
]


def is_likely_todo(sentence: str) -> bool:
    """할 일 후보인지 빠르게 판정"""
    for pat in NON_TODO_PATTERNS:
        if re.search(pat, sentence):
            return False
    if len(sentence) < 10:
        return False
    return True


# ─────────────────────────────────────────
# 4. 정규식 기반 구조 추출
#
# KoELECTRA 가 못 하는 일:
#   - "4월 22일" → "2026-04-22"
#   - "5,000원" → 비용 가중치
#   - "다음 주 월요일" 같은 상대 날짜
# ─────────────────────────────────────────
CURRENT_YEAR = 2026

# 절대 날짜
# - "4월 22일" 형태
# - "4. 22.", "4/22" 형태 (단, 앞에 다른 숫자나 단위가 없을 때만)
# 단위(mm, cm, kg, 원, 시, 차시 등) 뒤에 오는 숫자는 날짜가 아님
DATE_PATTERN_ABS = re.compile(
    r"(?:(\d{1,2})\s*월\s*(\d{1,2})\s*일)|"
    r"(?<![\d.])(?<!mm)(?<!cm)(?<!원)(?<!시)"   # 앞에 숫자/단위 없을 때
    r"(\d{1,2})[./](\d{1,2})"
    r"(?!\d)(?![mc]m)(?!kg)",                    # 뒤에도 숫자/단위 없을 때
)

DATE_PATTERN_REL = re.compile(
    r"(다음\s*주\s*[월화수목금토일]요일|"
    r"이번\s*주\s*[월화수목금토일]요일|"
    r"매주\s*[월화수목금토일]요일|"
    r"오늘|내일|모레)"
)

DEADLINE_PATTERN = re.compile(r"([\w가-힣\s]+?)\s*까지")
MONEY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")


def extract_due_date(sentence: str) -> Optional[str]:
    """문장에서 마감일/일정 날짜 추출"""
    # 1) 절대 날짜
    m = DATE_PATTERN_ABS.search(sentence)
    if m:
        month = m.group(1) or m.group(3)
        day = m.group(2) or m.group(4)
        if month and day:
            try:
                return f"{CURRENT_YEAR}-{int(month):02d}-{int(day):02d}"
            except ValueError:
                pass

    # 2) 상대 날짜 (번역 모델이 처리하도록 원문 유지)
    m = DATE_PATTERN_REL.search(sentence)
    if m:
        return m.group(1).strip()

    # 3) "X까지" 표현
    m = DEADLINE_PATTERN.search(sentence)
    if m:
        deadline_text = m.group(1).strip()
        if deadline_text and len(deadline_text) < 20:
            return deadline_text

    return None


def has_money(sentence: str) -> bool:
    return bool(MONEY_PATTERN.search(sentence))


# ─────────────────────────────────────────
# 5. KoELECTRA 카테고리 분류
# ─────────────────────────────────────────
def classify_category(sentence: str) -> tuple[str, float]:
    """문장 → (category, confidence)"""
    _load_model()

    inputs = _tokenizer(
        sentence,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=128,
    ).to(_device)

    with torch.no_grad():
        logits = _model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        pred_id = int(torch.argmax(probs).item())
        confidence = float(probs[pred_id].item())

    return _id2label[pred_id], confidence


# ─────────────────────────────────────────
# 6. importance 계산
# ─────────────────────────────────────────
CATEGORY_BASE_IMPORTANCE = {
    "제출":      1.0,
    "준비물":    0.85,
    "건강·안전": 0.80,
    "비용":      0.75,
    "일정":      0.70,
    "기타":      0.50,
}

URGENT_KEYWORDS = [
    "반드시", "꼭", "필수", "엄수", "마감", "당일", "즉시",
    "응급", "위급", "112", "신고",
]


def calc_importance(
    sentence: str,
    category: str,
    due_date: Optional[str],
) -> float:
    score = CATEGORY_BASE_IMPORTANCE.get(category, 0.5)

    for kw in URGENT_KEYWORDS:
        if kw in sentence:
            score = min(1.0, score + 0.05)
            break

    if due_date:
        score = min(1.0, score + 0.05)

    if len(sentence) > 80:
        score = max(0.0, score - 0.05)

    return round(score, 2)


# ─────────────────────────────────────────
# 7. 메인 함수
# ─────────────────────────────────────────
def extract_todos(notice_text: str) -> list:
    """가정통신문 → TodoItem 리스트"""
    if not notice_text or not notice_text.strip():
        return []

    todos = []
    sentences = split_sentences(notice_text)
    candidates = [s for s in sentences if is_likely_todo(s)]

    for sent in candidates:
        due_date = extract_due_date(sent)
        is_money = has_money(sent)

        # 비용 패턴이면 모델 호출 없이 바로 비용 카테고리
        # (학습 데이터가 2개라 모델에서 제외했음)
        if is_money:
            category = "비용"
            confidence = 1.0
        else:
            category, confidence = classify_category(sent)

        # 신뢰도 너무 낮으면 노이즈
        if confidence < 0.4 and not is_money:
            continue

        importance = calc_importance(sent, category, due_date)
        if importance < 0.3:
            continue

        text_ko = sent
        if len(text_ko) > 100:
            text_ko = text_ko[:97] + "..."

        if SCHEMAS_AVAILABLE:
            try:
                todos.append(TodoItem(
                    category=Category(category),
                    text_ko=text_ko,
                    text_vi="",
                    importance=importance,
                    due_date=due_date,
                ))
            except Exception as e:
                print(f"[WARN] TodoItem 생성 실패: {e}", file=sys.stderr)
                continue
        else:
            todos.append({
                "category":   category,
                "text_ko":    text_ko,
                "text_vi":    "",
                "importance": importance,
                "due_date":   due_date,
            })

    return todos


def extract_todos_dict(notice_text: str) -> list[dict]:
    """schemas 미사용 환경용"""
    items = extract_todos(notice_text)
    if SCHEMAS_AVAILABLE and items and isinstance(items[0], TodoItem):
        return [item.model_dump() for item in items]
    return items


# ─────────────────────────────────────────
# 8. 직접 실행 테스트
# ─────────────────────────────────────────
if __name__ == "__main__":
    sample = """주간학습계획 8주(4.20~4.24) 서울갈산초등학교 3학년 6반

학부모님 안녕하십니까?

1. 등교시간: 8시 30분 ~ 8시 45분까지 등교
2. 3학년 합동 체육: 3월 24일(금) 5교시 체육관에서 실시. 학급티 및 간편한 복장 착용.
3. 나눔장터 안내
   1) 일시: 4월 30일(목) 8:50~10:30
   2) 준비물: 학급티, 1인용 돗자리, 판매할 물건
   3) 구입비는 5,000원 이내의 잔돈으로 준비합니다.
4. 디벗 사용을 위해 개인용 이어폰(3.5mm, C타입)을 4월 20일(월)까지 준비해주세요.

준비물
체육: 운동화 착용, 물 넉넉하게 준비
음악: 리코더(독일식)
마스크 1장씩 가방에 넣고 다니기

과제
독서생활 매주 1편 이상 작성해서 월요일에 제출하기

2026. 4. 17. 서울갈산초등학교장"""

    print("=" * 70)
    print("📝 추출 결과")
    print("=" * 70)
    todos = extract_todos_dict(sample)
    for i, t in enumerate(todos, 1):
        print(f"\n{i}. [{t['category']}] importance={t['importance']}")
        print(f"   text_ko : {t['text_ko']}")
        print(f"   due_date: {t['due_date']}")

    print(f"\n총 {len(todos)}개 TodoItem 추출")