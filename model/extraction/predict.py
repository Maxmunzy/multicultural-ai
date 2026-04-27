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
[1] split_sentences()       문장 단위로 나눔 (제목성 줄 조기 차단 — Bug 2 수정)
    ↓
[2] is_likely_todo()        안부인사·서명 등 1차 제외 (Bug 1 수정)
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
# Bug 2 수정: 제목성 줄(헤더)을 split 단계에서 조기 차단하여
#            NLLB 에 "헤더+인사말" 이 혼합된 채 전달되는 것을 방지.
# ─────────────────────────────────────────
_HEADER_ONLY = re.compile(
    r"^[^.,!?~]{2,40}(안내|공지|알림|공개수업|상담|학습|행사|일정)\s*$"
)


def split_sentences(text: str) -> list[str]:
    """가정통신문 전체 텍스트를 문장 리스트로 분리"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    sentences = []
    for line in lines:
        if _HEADER_ONLY.match(line):
            continue  # 제목성 줄은 번역 대상에서 제외
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
#
# Bug 1 수정: "안녕하세요" 계열 패턴 3개 추가.
#            기존에는 "안녕하십니까"만 있어 "학부모님 안녕하세요."가
#            TODO로 잘못 분류됨.
# ─────────────────────────────────────────
NON_TODO_PATTERNS = [
    r"^학부모님\s*안녕하십니까",
    r"^안녕하십니까",
    r"^학부모님\s*안녕하세요",        # Bug 1 추가
    r"^안녕하세요",                    # Bug 1 추가
    r"^.*님\s*안녕하(세요|십니까)",   # Bug 1 추가 (일반화)
    r"^학부모님께\s*안내드립니다",
    r"^학부모님께\s*드립니다",
    r"안내드립니다\s*\.?\s*$",
    r"드립니다\s*\.?\s*$",
    # 제목성 문장 (구두점 없이 "안내"로 끝남)
    r"^[^.,!?]{1,30}\s*안내\s*$",
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
    if len(sentence) < 7:
        return False
    return True


# ─────────────────────────────────────────
# 4. 정규식 기반 구조 추출
# ─────────────────────────────────────────
CURRENT_YEAR = 2026

DATE_PATTERN_ABS = re.compile(
    r"(?:(\d{1,2})\s*월\s*(\d{1,2})\s*일)|"
    r"(?<![\d.])(?<!mm)(?<!cm)(?<!원)(?<!시)"
    r"(\d{1,2})[./](\d{1,2})"
    r"(?!\d)(?![mc]m)(?!kg)",
)

DATE_PATTERN_REL = re.compile(
    r"(다음\s*주\s*[월화수목금토일]요일|"
    r"이번\s*주\s*[월화수목금토일]요일|"
    r"매주\s*[월화수목금토일]요일|"
    r"오늘|내일|모레)"
)

DEADLINE_PATTERN = re.compile(r"([\w가-힣\s]+?)\s*까지")

# Bug 3 메모:
#   MONEY_PATTERN 은 이미 \d+\s*원 형태 → "원하시는"·"원인" 오탐 없음 (extraction 레벨 정상).
#   검수 상세 "원→won" 오탐은 translation_tts/run_mvp_pipeline.py 글로사리 로직 문제.
#   해당 파일에서 str.contains('원') → re.search(r'\d[\d,]*\s*원', text) 로 교체 필요.
MONEY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")


def extract_due_date(sentence: str) -> Optional[str]:
    """문장에서 마감일/일정 날짜 추출"""
    m = DATE_PATTERN_ABS.search(sentence)
    if m:
        month = m.group(1) or m.group(3)
        day = m.group(2) or m.group(4)
        if month and day:
            try:
                return f"{CURRENT_YEAR}-{int(month):02d}-{int(day):02d}"
            except ValueError:
                pass

    m = DATE_PATTERN_REL.search(sentence)
    if m:
        return m.group(1).strip()

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

        if is_money:
            category = "비용"
            confidence = 1.0
        else:
            category, confidence = classify_category(sent)

        if confidence < 0.25 and not is_money:
            continue

        importance = calc_importance(sent, category, due_date)
        if importance < 0.25:
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
    sample = """학부모 공개수업 및 상담 안내
학부모님 안녕하세요.

1. 공개수업 일시: 6월 12일(목) 3~4교시
2. 상담 신청: 6월 5일(금)까지 가정통신문 회신
3. 준비물: 실내화, 출입증 지참
수업료 50,000원은 6월 10일까지 납부해 주세요.

서울갈산초등학교장"""

    print("=" * 70)
    print("📝 추출 결과")
    print("=" * 70)
    todos = extract_todos_dict(sample)
    for i, t in enumerate(todos, 1):
        print(f"\n{i}. [{t['category']}] importance={t['importance']}")
        print(f"   text_ko : {t['text_ko']}")
        print(f"   due_date: {t['due_date']}")

    print(f"\n총 {len(todos)}개 TodoItem 추출")
