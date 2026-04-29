"""
model/extraction/predict.py
============================
A단계: 가정통신문 → 할 일 및 중요 일정 후보 문장 추출기

담당:   윤정
역할:   원문 텍스트에서 학부모가 인지·행동해야 할 문장만 이진 분류로 추출.
        카테고리 분류·중요도 계산은 B단계(경이 모델)로 위임.
출력:   list[dict] — B단계 입력 스키마와 1:1 대응

─────────────────────────────────────────
입력
─────────────────────────────────────────
OCR 모듈(pdfplumber / pymupdf 등)이 추출한 가정통신문 텍스트 (str).
OCR은 A단계 이전에 처리되므로 이 스크립트는 항상 순수 str 을 입력받습니다.

─────────────────────────────────────────
파이프라인
─────────────────────────────────────────
OCR 추출 텍스트 (str)
    ↓
[1] split_sentences()       줄글 → 문장 리스트
                            (OCR 아티팩트 줄 조기 차단 포함)
    ↓
[2] is_likely_todo()        ① 정규식 빠른 제외
                            ② KoELECTRA 이진 분류
                               0: 노이즈  1: 할 일·중요 일정
    ↓
[3] extract_due_date()      정규식: 날짜·마감 추출
    has_money()             정규식: 금액 여부 추출
    ↓
predict() → list[dict]
    {"text": str, "due_date": str | None, "has_money": bool}
─────────────────────────────────────────
"""

import datetime
import os
import re
from typing import Optional

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification


# ─────────────────────────────────────────
# 1. 모델 로드 (lazy, 최초 1회)
# ─────────────────────────────────────────
# CPU 시연 환경을 위해 small 변형 사용
_BASE_MODEL_ID = "monologg/koelectra-small-v3-discriminator"
_LOCAL_CHECKPOINT_DIR = os.path.join(
    os.path.dirname(__file__), "checkpoints/koelectra-binary"
)
# label-1 (할 일) 확률 임계값 — 파인튜닝 후 조정 가능
BINARY_THRESHOLD = 0.5

_tokenizer: Optional[AutoTokenizer] = None
_model: Optional[AutoModelForSequenceClassification] = None
_device = "cuda" if torch.cuda.is_available() else "cpu"


def _load_model() -> None:
    global _tokenizer, _model
    if _model is not None:
        return

    # 로컬 파인튜닝 체크포인트 우선, 없으면 HF Hub 베이스 모델
    _local_ready = any(
        os.path.exists(os.path.join(_LOCAL_CHECKPOINT_DIR, fname))
        for fname in ("pytorch_model.bin", "model.safetensors")
    )
    src = _LOCAL_CHECKPOINT_DIR if _local_ready else _BASE_MODEL_ID

    _tokenizer = AutoTokenizer.from_pretrained(src)
    _model = AutoModelForSequenceClassification.from_pretrained(
        src, num_labels=2
    )
    _model.to(_device)
    _model.eval()


# ─────────────────────────────────────────
# 2. 문장 분리
# ─────────────────────────────────────────
_HEADER_ONLY = re.compile(
    r"^[^.,!?~]{2,40}(안내|공지|알림|공개수업|상담|학습|행사|일정)\s*$"
)

# OCR 출력에서 줄 단위로 나타나는 노이즈 패턴 (문장이 될 수 없는 줄)
_OCR_LINE_NOISE = re.compile(
    r"https?://"                                    # HTTP/HTTPS URL
    r"|^www\."                                      # 도메인 주소
    r"|☎\s*\d"                                      # 전화번호 (☎ + 숫자)
    r"|^\d{1,2}:\d{2}\s*[~\-–]\s*\d{1,2}:\d{2}"   # 시간 범위 전용 줄 (19:00~20:00)
    r"|^[→←↑↓]+\s*$"                               # 화살표 전용 줄
)


def split_sentences(text: str) -> list[str]:
    """OCR 추출 텍스트를 문장 리스트로 분리. 줄 단위 노이즈는 이 단계에서 차단."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    sentences: list[str] = []
    for line in lines:
        if _HEADER_ONLY.match(line) or _OCR_LINE_NOISE.search(line):
            continue  # 제목성 줄·OCR 아티팩트 줄 조기 차단
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
# 3. 이진 분류 필터 (정규식 1차 → KoELECTRA 2차)
# ─────────────────────────────────────────
_NON_TODO_PATTERNS: list[str] = [
    r"^학부모님\s*안녕하십니까",
    r"^안녕하십니까",
    r"^학부모님\s*안녕하세요",        # Bug 1 수정
    r"^안녕하세요",                    # Bug 1 수정
    r"^.*님\s*안녕하(세요|십니까)",   # Bug 1 수정 (일반화)
    r"^학부모님께\s*안내드립니다",
    r"^학부모님께\s*드립니다",
    r"안내드립니다\s*\.?\s*$",
    r"드립니다\s*\.?\s*$",
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


def _classify(sentence: str) -> Optional[float]:
    """
    ① 정규식으로 명백한 노이즈 제외 → None 반환.
    ② 통과 시 KoELECTRA label-1(할 일) 확률 반환 (0.0~1.0).
    """
    if len(sentence) < 7:
        return None
    for pat in _NON_TODO_PATTERNS:
        if re.search(pat, sentence):
            return None

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
        return float(torch.softmax(logits, dim=-1)[0][1].item())


def is_likely_todo(sentence: str) -> bool:
    """외부 호환용 래퍼. 임계값 이상이면 True."""
    prob = _classify(sentence)
    return prob is not None and prob >= BINARY_THRESHOLD


# ─────────────────────────────────────────
# 4. 정규식 기반 구조 추출
# ─────────────────────────────────────────
_DATE_ABS = re.compile(
    r"(?:(\d{1,2})\s*월\s*(\d{1,2})\s*일)|"
    r"(?<![\d.])(?<!mm)(?<!cm)(?<!원)(?<!시)"
    r"(\d{1,2})[./](\d{1,2})"
    r"(?!\d)(?![mc]m)(?!kg)",
)

_DATE_REL = re.compile(
    r"(다음\s*주\s*[월화수목금토일]요일|"
    r"이번\s*주\s*[월화수목금토일]요일|"
    r"매주\s*[월화수목금토일]요일|"
    r"오늘|내일|모레)"
)

_DEADLINE = re.compile(r"([\w가-힣\s]+?)\s*까지")

# \d+\s*원 형태 → "원하시는"·"원인" 오탐 없음
_MONEY = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")

_ACTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"납부|입금"),        "납부"),
    (re.compile(r"제출"),             "제출"),
    (re.compile(r"신청"),             "신청"),
    (re.compile(r"참여|참가|출석"),   "참여"),
    (re.compile(r"준비|지참|챙겨"),   "준비"),
    (re.compile(r"확인|숙지|참고"),   "확인"),
]


def extract_due_date(sentence: str) -> Optional[str]:
    """문장에서 마감일/일정 날짜 추출. 없으면 None."""
    m = _DATE_ABS.search(sentence)
    if m:
        month = m.group(1) or m.group(3)
        day = m.group(2) or m.group(4)
        if month and day:
            try:
                return f"{datetime.date.today().year}-{int(month):02d}-{int(day):02d}"
            except ValueError:
                pass

    m = _DATE_REL.search(sentence)
    if m:
        return m.group(1).strip()

    m = _DEADLINE.search(sentence)
    if m:
        deadline_text = m.group(1).strip()
        if deadline_text and len(deadline_text) < 20:
            return deadline_text

    return None


def extract_amount(sentence: str) -> Optional[int]:
    """문장에서 첫 번째 금액(원) 추출. 없으면 None."""
    m = _MONEY.search(sentence)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def extract_action_hint(sentence: str) -> Optional[str]:
    """납부·제출·신청 등 행동 키워드 힌트 추출. 없으면 None."""
    for pattern, hint in _ACTION_PATTERNS:
        if pattern.search(sentence):
            return hint
    return None


# ─────────────────────────────────────────
# 5. 메인 함수
# ─────────────────────────────────────────
def predict(notice_text: str, source: Optional[str] = None) -> list[dict]:
    """
    가정통신문 원문 → 할 일 및 중요 일정 후보 문장 리스트.

    Args:
        notice_text: OCR 모듈이 추출한 가정통신문 텍스트 str.
        source:      원본 파일명 등 출처 식별자 (선택).

    Returns:
        B단계(경이 모델) 입력 스키마:
        [{"text", "source", "due_date", "amount", "confidence", "action_hint"}, ...]
    """
    if not notice_text or not notice_text.strip():
        return []

    results: list[dict] = []
    for sentence in split_sentences(notice_text):
        confidence = _classify(sentence)
        if confidence is None or confidence < BINARY_THRESHOLD:
            continue
        results.append({
            "text":        sentence,
            "source":      source,
            "due_date":    extract_due_date(sentence),
            "amount":      extract_amount(sentence),
            "confidence":  round(confidence, 4),
            "action_hint": extract_action_hint(sentence),
        })

    return results


# ─────────────────────────────────────────
# 6. 직접 실행 테스트
# ─────────────────────────────────────────
if __name__ == "__main__":
    # 실제 pdfplumber OCR 출력 형식 (sample_pdfplumber.txt 발췌)
    sample = """다문화 학부모님
2023.3.6.(월) 다문화가정 학생(학부모)을 위한
온라인 한국어학습 신청 안내
안녕하세요? 사랑합니다.
의정부교육지원청에서 다문화가정 학생의 학습 격차 해소와 학부모님의 한국 생활 조기 정착을 지원하기
위해 온라인에서 한국어를 학습할 수 있는 프로그램을 무료로 제공합니다.
모국어를 사용하는 강사가 단계별로 친절히 가르치는 동영상 강의(VOD)를 PC나 모바일 기기로 접속하여
언제든지 원하는 장소에서 편리하게 학습할 수 있는 좋은 기회이오니, 한국어 학습이 필요한 다문화가정 학
생 및 학부모(보호자) 모두 기한 내 신청하여 주시기 바랍니다.
2. 신청 기간: 2023. 3. 6. (월) ~ 3. 17. (금) 정기 모집 기간 신청 시 3.20.(월)까지 승인
5. 신청 관련 문의: ☎031-627-7916 (한컴지니케이/살랑코리아)
* 자세한 사항은 3월 20일에 학습자들에게 E-mail로 개별 공지 예정입니다.
http://bit.ly/sarlang www.sarlang.com
의정부신곡초등학교장"""

    print("=" * 60)
    print("A단계 추출 결과 — OCR 텍스트 입력 (B단계 입력용)")
    print("=" * 60)
    candidates = predict(sample, source="sample_pdfplumber.txt")
    for i, item in enumerate(candidates, 1):
        print(f"\n{i}. {item['text']}")
        print(f"   source     : {item['source']}")
        print(f"   due_date   : {item['due_date']}")
        print(f"   amount     : {item['amount']}")
        print(f"   confidence : {item['confidence']}")
        print(f"   action_hint: {item['action_hint']}")
    print(f"\n총 {len(candidates)}개 후보 문장 추출")
