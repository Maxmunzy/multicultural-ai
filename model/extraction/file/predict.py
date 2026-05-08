"""
model/extraction/file/predict.py
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
layout_normalizer(Claude API)가 정제한 텍스트 (str, \n 줄 단위)
    ↓
[0] extract_title()         원본 줄에서 제목 감지 (heuristic)
                            → split_sentences() 이전에 실행해야 함
    ↓
[1] split_sentences()       줄글 → 문장 리스트
                            (OCR 아티팩트 줄 조기 차단 포함)
    ↓
[2] is_likely_todo()        KoELECTRA 이진 분류
                               0: 노이즈  1: 할 일·중요 일정
    ↓
[3] extract_due_date()      정규식: 날짜·마감 추출
    has_money()             정규식: 금액 여부 추출
    ↓
predict() → list[dict]
    {"text": str, "source": str|None, "due_date": str|None,
     "amount": int|None, "confidence": float, "action_hint": str|None}

제목 추출: extract_title(notice_text) → str | None  (predict()와 별도 호출)
─────────────────────────────────────────
"""

import datetime
import os
import re
import warnings
from typing import Optional

import torch

warnings.filterwarnings("ignore", category=UserWarning, module="torch")
from transformers import AutoTokenizer, AutoModelForSequenceClassification


# ─────────────────────────────────────────
# 0. 제목 감지 heuristic
# ─────────────────────────────────────────
_TITLE_ENDING_RE = re.compile(r"(안내|공지|알림|통보|조사|신청|수납|모집)\s*(제\s*\d{4,}-\d+호)?$")
_TITLE_MAX_LEN = 80
_TITLE_SENT_END_RE = re.compile(r"[.!?。？！]")
_TITLE_SECTION_RE = re.compile(r"^[\d가나다라마바사아자차카타파하][.)]\s")

# koelectra-title 체크포인트 경로 — 없으면 heuristic fallback
_TITLE_CHECKPOINT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "checkpoints", "koelectra-title"
)
TITLE_THRESHOLD = 0.4  # 임계값: train_koelectra_title.ipynb 임계값 분석 결과로 조정

_title_tokenizer: Optional[AutoTokenizer] = None
_title_model: Optional[AutoModelForSequenceClassification] = None


def _load_title_model() -> bool:
    """koelectra-title 체크포인트가 있으면 로드하고 True 반환. 없으면 False."""
    global _title_tokenizer, _title_model
    if _title_model is not None:
        return True
    local_ready = (
        any(
            os.path.exists(os.path.join(_TITLE_CHECKPOINT_DIR, f))
            for f in ("pytorch_model.bin", "model.safetensors")
        )
        and os.path.exists(os.path.join(_TITLE_CHECKPOINT_DIR, "config.json"))
    )
    if not local_ready:
        return False
    _title_tokenizer = AutoTokenizer.from_pretrained(_TITLE_CHECKPOINT_DIR)
    _title_model = AutoModelForSequenceClassification.from_pretrained(
        _TITLE_CHECKPOINT_DIR, num_labels=2
    )
    _title_model.to(_device)
    _title_model.eval()
    return True


def is_title_heuristic(text: str) -> bool:
    """rule 기반 제목 감지.

    조건 (모두 만족해야 True):
      - 10자 이상, 80자 이하
      - 문장 부호(. ! ?) 없음
      - 항목 번호(1. 가. 등)로 시작하지 않음
      - '안내/공지/알림/통보/조사/신청/수납/모집'으로 끝남
    """
    if not (10 <= len(text) <= _TITLE_MAX_LEN):
        return False
    if _TITLE_SENT_END_RE.search(text):
        return False
    if _TITLE_SECTION_RE.match(text):
        return False
    return bool(_TITLE_ENDING_RE.search(text))


def extract_title(notice_text: str) -> Optional[str]:
    """가정통신문에서 제목 문장을 추출. 없으면 None.

    - koelectra-title 체크포인트가 있으면 ML 모델로 전체 줄 스코어링 → 최고점 반환
    - 없으면 heuristic(is_title_heuristic) fallback → 첫 번째 통과 줄 반환

    반드시 predict() 와 별도로, 원문에 대해 호출할 것.

    사용 예:
        title = extract_title(notice_text)
        items = predict(notice_text, source=filename)
    """
    lines = [line.strip() for line in notice_text.splitlines() if line.strip()]

    if _load_title_model():
        best_line: Optional[str] = None
        best_prob = TITLE_THRESHOLD
        for line in lines:
            if len(line) < 10:
                continue
            inputs = _title_tokenizer(
                line, return_tensors="pt", truncation=True, max_length=128
            ).to(_device)
            with torch.no_grad():
                prob = float(torch.softmax(_title_model(**inputs).logits, dim=-1)[0][1].item())
            if prob > best_prob:
                best_prob = prob
                best_line = line
        return best_line

    # heuristic fallback
    for line in lines:
        if is_title_heuristic(line):
            return line
    return None


# ─────────────────────────────────────────
# 1. 모델 로드 (lazy, 최초 1회)
# ─────────────────────────────────────────
# CPU 시연 환경을 위해 small 변형 사용
_BASE_MODEL_ID = "yunjeong116/koelectra-extractor"   # HF Hub 파인튜닝 모델
# HF Hub repo 내 모델 파일이 koelectra-extractor/ 서브폴더에 위치
_HF_SUBFOLDER = "koelectra-extractor"
_LOCAL_CHECKPOINT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "checkpoints", "koelectra-binary-base"
)  # base 재학습 체크포인트 (2026-05-08). 학습 데이터: v3.1.3 + v4_clean 병합 (47,148개, 소프트 라벨)
# label-1 (할 일) 확률 임계값 — v4_merged 재학습 임계값 탐색 결과 0.55 최적 (F1=0.9003)
BINARY_THRESHOLD = 0.55

_tokenizer: Optional[AutoTokenizer] = None
_model: Optional[AutoModelForSequenceClassification] = None
_device = "cuda" if torch.cuda.is_available() else "cpu"


def _load_model() -> None:
    global _tokenizer, _model
    if _model is not None:
        return

    # HF Hub 우선 로드 — 누구나 동일한 모델을 받도록 canonical 소스로 고정
    # 오프라인 환경에서만 로컬 체크포인트로 fallback
    try:
        _tokenizer = AutoTokenizer.from_pretrained(
            _BASE_MODEL_ID, subfolder=_HF_SUBFOLDER
        )
        _model = AutoModelForSequenceClassification.from_pretrained(
            _BASE_MODEL_ID, num_labels=2, subfolder=_HF_SUBFOLDER
        )
    except Exception:
        # 오프라인 fallback: checkpoints/koelectra-binary-v3.1/
        _local_ready = (
            any(
                os.path.exists(os.path.join(_LOCAL_CHECKPOINT_DIR, fname))
                for fname in ("pytorch_model.bin", "model.safetensors")
            )
            and os.path.exists(os.path.join(_LOCAL_CHECKPOINT_DIR, "config.json"))
        )
        if not _local_ready:
            raise
        _tokenizer = AutoTokenizer.from_pretrained(_LOCAL_CHECKPOINT_DIR)
        _model = AutoModelForSequenceClassification.from_pretrained(
            _LOCAL_CHECKPOINT_DIR, num_labels=2
        )
    _model.to(_device)
    _model.eval()


# ─────────────────────────────────────────
# 2. PDF 줄 끊김 복원
# ─────────────────────────────────────────
def _join_broken_lines(text: str) -> str:
    """PDF 추출 시 발생하는 단어 중간 줄 끊김 복원.
    "다문화가정 학\\n생" → "다문화가정 학생"
    "지원하기\\n위해"   → "지원하기 위해"
    """
    text = re.sub(r" ([가-힣])\n([가-힣])", r" \1\2", text)   # 단어 중간 끊김
    text = re.sub(r"([^.!?\n])\n([^\n])", r"\1 \2", text)     # 문장 이어짐
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ─────────────────────────────────────────
# 2-1. 특수기호 정제 (문장 단위)
# ─────────────────────────────────────────
# split_sentences()가 ◆●▪○ 등을 분리 기준으로 사용하므로
# 마커 제거는 split 이후 문장 단위로 수행.
# preprocess_txt_to_jsonl.py 의 clean_sentence()와 동일 로직 — 반드시 동기화 유지.

# 1단계: 특정 기호 → ASCII 대응 문자로 변환
_NORMALIZE_TABLE = str.maketrans({
    '‘': "'", '’': "'",  # ' '  →  '
    '“': '"', '”': '"',  # " "  →  "
    '「': '"', '」': '"',  # 「」 →  "
    '『': '"', '』': '"',  # 『』 →  "
    '【': '(', '】': ')',  # 【】 →  ()
    '〔': '(', '〕': ')',  # 〔〕 →  ()
    '｢': '"', '｣': '"',  # ｢｣  →  "
    '–': '-', '—': '-',  # –—  →  -
    '～': '~', '∼': '~',  # ～∼ →  ~
    '，': ',',                 # ，  →  ,
    '\xd7':   'x',                 # ×   →  x
    '\xb7':   ' ', '･': ' ',  # ·･  →  공백
    '・': ' ', '〃': ' ',  # ・〃 →  공백
    '…': '...',               # …   →  ...
    '\xad':   '',                  # soft hyphen → 제거
    '￦': '',                  # ￦  →  제거
})

# 2단계: whitelist — 한글/영숫자/허용 구두점 외 모든 기호 공백으로 대체
# 코드포인트 불문하고 제거하므로 PUA·체크박스(□○) 변종까지 처리
_SYMBOL_REMOVE_RE = re.compile(
    "[^가-힣"
    "㄰-㆏"  # 한글 자모
    "a-zA-Z0-9"
    " \\t.,!?():/%@~&_\\-'\"]"
)


def _clean_symbols(sentence: str) -> str:
    sentence = sentence.translate(_NORMALIZE_TABLE)
    sentence = _SYMBOL_REMOVE_RE.sub(' ', sentence)
    return re.sub(r"\s+", " ", sentence).strip()


# ─────────────────────────────────────────
# 3. 문장 분리
# ─────────────────────────────────────────
# OCR 출력에서 줄 단위로 나타나는 노이즈 패턴 (문장이 될 수 없는 줄)
# 모든 패턴은 줄 시작(^) anchor — URL·전화·시간이 본문 안에 섞인 줄은 통과시킴
_OCR_LINE_NOISE = re.compile(
    r"^https?://"                                       # URL 전용 줄
    r"|^www\."                                          # 도메인 전용 줄
    r"|^☎\s*\d"                                        # 전화번호 전용 줄
    r"|^\d{1,2}:\d{2}\s*[~\-–]\s*\d{1,2}:\d{2}\s*$"  # 시간 범위만 있는 줄
    r"|^[→←↑↓]+\s*$"                                   # 화살표 전용 줄
)


def split_sentences(text: str) -> list[str]:
    """OCR 추출 텍스트를 문장 리스트로 분리. 줄 단위 노이즈는 이 단계에서 차단."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    sentences: list[str] = []
    for line in lines:
        if _OCR_LINE_NOISE.search(line):
            continue  # OCR 아티팩트 줄 조기 차단
        parts = re.split(
            r"(?<=[.!?])\s+|"
            r"(?<=다\.)\s+|(?<=요\.)\s+|(?<=니다\.)\s+|"
            r"(?<=까\?)\s+|(?<=요\?)\s+|"
            r"\s+(?=\d+[.)]\s)|\s+(?=[가-힣]\.\s)|"
            r"\s+(?=[❏○◆●▪◎□■])",                          # 리스트 마커 앞 분리
            line,
        )
        sentences.extend(parts)

    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]


# ─────────────────────────────────────────
# 3. 이진 분류 필터 (KoELECTRA)
# ─────────────────────────────────────────
def _classify(sentence: str) -> Optional[float]:
    """KoELECTRA label-1(할 일) 확률 반환 (0.0~1.0). 너무 짧으면 None."""
    if len(sentence) < 7:
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

    notice_text = _join_broken_lines(notice_text)
    results: list[dict] = []
    for sentence in split_sentences(notice_text):
        sentence = _clean_symbols(sentence)
        if not sentence:
            continue
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

    # print("=" * 60)
    # print("A단계 추출 결과 — OCR 텍스트 입력 (B단계 입력용)")
    # print("=" * 60)
    # candidates = predict(sample, source="sample_pdfplumber.txt")
    # for i, item in enumerate(candidates, 1):
    #     print(f"\n{i}. {item['text']}")
    #     print(f"   source     : {item['source']}")
    #     print(f"   due_date   : {item['due_date']}")
    #     print(f"   amount     : {item['amount']}")
    #     print(f"   confidence : {item['confidence']}")
    #     print(f"   action_hint: {item['action_hint']}")
    # print(f"\n총 {len(candidates)}개 후보 문장 추출")
