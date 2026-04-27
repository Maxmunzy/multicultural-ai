# -*- coding: utf-8 -*-
"""
train_koelectra (1).ipynb 패치 스크립트
수정 내역:
  - cell 11: 마크다운 업데이트 (클래스 가중치 설명)
  - cell 12: WeightedTrainer + compute_class_weight 추가
  - cell 13: 마크다운 업데이트 (epoch 15, cosine, warmup)
  - cell 14: 개선된 TrainingArguments + WeightedTrainer 사용
  - cell 18 뒤: predict.py 재정의(Bug 1,2,3) + 추론 테스트 셀 4개 삽입
  - zip 셀: predict.py 함께 포함
  - 마지막 셀: 수정 내역 정리
"""
import json, pathlib

NB_PATH = pathlib.Path("c:/AI-human4/P1/multicultural-ai/model/extraction/train_koelectra (1).ipynb")

with open(NB_PATH, encoding="utf-8") as f:
    nb = json.load(f)


def code_cell(source: str) -> dict:
    return {"cell_type": "code", "execution_count": None,
            "metadata": {}, "outputs": [], "source": source}


def md_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source}


# ──────────────────────────────────────────────────────────────────────────────
# cell 11 (index 11): 마크다운 — 클래스 가중치 설명 추가
# ──────────────────────────────────────────────────────────────────────────────
nb["cells"][11]["source"] = (
    "## 6. 모델 + 평가 지표 + 클래스 가중치 정의\n\n"
    "분류 문제라서 정확도 + Macro F1 두 가지를 본다.  \n"
    "Macro F1 은 카테고리별 F1 의 평균 — 데이터 적은 카테고리도 동등하게 평가됨.\n\n"
    "**클래스 불균형 문제**: 기타(7개) vs 건강·안전(35개) — 단순 학습 시 기타 F1=0.00 발생.  \n"
    "`compute_class_weight('balanced')` 로 희귀 클래스에 높은 가중치를 부여하고,  \n"
    "`WeightedTrainer` 에서 가중치를 적용한 CrossEntropyLoss 를 사용한다."
)

# ──────────────────────────────────────────────────────────────────────────────
# cell 12 (index 12): WeightedTrainer + class weights + metrics
# ──────────────────────────────────────────────────────────────────────────────
nb["cells"][12]["source"] = """\
from transformers import AutoModelForSequenceClassification, Trainer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.utils.class_weight import compute_class_weight
import numpy as np
import torch

model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_NAME,
    num_labels=len(LABEL_LIST),
    id2label=id2label,
    label2id=label2id,
)

# 클래스 불균형 보정 — 기타(7개)·준비물(22개) 편차가 커서 필수
_w = compute_class_weight("balanced", classes=np.arange(len(LABEL_LIST)), y=train_labels)
_class_weights = torch.tensor(_w, dtype=torch.float)


class WeightedTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.get("labels")
        outputs = model(**inputs)
        logits = outputs.get("logits")
        loss_fn = torch.nn.CrossEntropyLoss(weight=_class_weights.to(logits.device))
        loss = loss_fn(logits, labels)
        return (loss, outputs) if return_outputs else loss


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        "accuracy": accuracy_score(labels, preds),
        "f1_macro": f1_score(labels, preds, average="macro"),
    }


print("클래스 가중치:", {l: round(w, 3) for l, w in zip(LABEL_LIST, _w)})\
"""

# ──────────────────────────────────────────────────────────────────────────────
# cell 13 (index 13): 마크다운 업데이트
# ──────────────────────────────────────────────────────────────────────────────
nb["cells"][13]["source"] = (
    "## 7. 학습 실행\n\n"
    "에폭 15회, 배치 16. 데이터 100개 기준 T4 GPU 약 20~30분.  \n"
    "이전 대비 변경 사항:\n"
    "- `num_train_epochs` 10→15 (기타 클래스 충분히 학습)\n"
    "- `learning_rate` 3e-5→2e-5 (더 안정적 수렴)\n"
    "- `warmup_ratio=0.1` + `lr_scheduler_type='cosine'` 추가\n"
    "- `WeightedTrainer` 사용 (클래스 불균형 보정)\n\n"
    "`load_best_model_at_end=True` 로 검증 F1 가장 높은 체크포인트를 자동 보존."
)

# ──────────────────────────────────────────────────────────────────────────────
# cell 14 (index 14): 개선된 TrainingArguments + WeightedTrainer
# ──────────────────────────────────────────────────────────────────────────────
nb["cells"][14]["source"] = """\
from transformers import TrainingArguments, DataCollatorWithPadding

args = TrainingArguments(
    output_dir="./koelectra-output",
    save_safetensors=False,
    num_train_epochs=15,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    learning_rate=2e-5,
    weight_decay=0.01,
    warmup_ratio=0.1,
    lr_scheduler_type="cosine",
    eval_strategy="epoch",
    save_strategy="epoch",
    logging_steps=10,
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="f1_macro",
    greater_is_better=True,
    report_to="none",
)

trainer = WeightedTrainer(
    model=model,
    args=args,
    train_dataset=train_ds,
    eval_dataset=val_ds,
    tokenizer=tokenizer,
    data_collator=DataCollatorWithPadding(tokenizer),
    compute_metrics=compute_metrics,
)

trainer.train()\
"""

# ──────────────────────────────────────────────────────────────────────────────
# 새 셀 4개: cell 18 뒤에 삽입
# ──────────────────────────────────────────────────────────────────────────────

new_md_predict = md_cell(
    "## 11. predict.py 재정의 — 버그 수정 3종\n\n"
    "> `model/extraction/predict.py` 가 삭제 상태(`git: D`)라 여기서 다시 생성.\n\n"
    "| # | 버그 | 원인 | 수정 위치 |\n"
    "|---|------|------|----------|\n"
    "| 1 | `학부모님 안녕하세요.` 가 TODO로 잡힘 | `NON_TODO_PATTERNS` 에 `안녕하십니까`만 있고 `안녕하세요` 미포함 | **predict.py** |\n"
    "| 2 | 첫 베트남어 문장 어색 | 헤더·인사말이 NLLB에 합쳐진 채로 전달됨 | **predict.py** `split_sentences()` |\n"
    "| 3 | 검수 상세 `원→won` 오탐 | 글로사리 매칭이 `'원'` substring | **translation_tts/run_mvp_pipeline.py** |\n\n"
    "아래 셀을 실행하면 수정된 `predict.py` 가 현재 폴더에 생성됩니다."
)

PREDICT_PY_CONTENT = r'''"""
model/extraction/predict.py
============================
가정통신문 -> TodoItem 리스트 추출 (경로 B 하이브리드)

파이프라인
  [1] split_sentences()   문장 분리 (헤더/제목 줄 조기 차단)  <- Bug 2 수정
  [2] is_likely_todo()    인사말·서명 등 1차 제외              <- Bug 1 수정
  [3] extract_due_date()  정규식: 날짜·마감
  [4] classify_category() KoELECTRA: 5개 카테고리 + 비용 정규식
  [5] calc_importance()   카테고리 + due_date + 키워드 -> 점수
"""

import os, sys, re, json
from typing import Optional

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "backend/app/models"))

try:
    from schemas import TodoItem, Category  # type: ignore
    SCHEMAS_AVAILABLE = True
except ImportError:
    SCHEMAS_AVAILABLE = False
    TodoItem = None
    Category = None

# ── 1. 모델 로드 ─────────────────────────────────────────────────────────────
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
            repo_id=HF_REPO_ID, filename=f"{HF_SUBFOLDER}/labels.json"
        )
    _tokenizer = AutoTokenizer.from_pretrained(**load_kwargs)
    _model = AutoModelForSequenceClassification.from_pretrained(**load_kwargs)
    _model.to(_device)
    _model.eval()
    with open(labels_path, encoding="utf-8") as f:
        meta = json.load(f)
    _id2label = {int(k): v for k, v in meta["id2label"].items()}


# ── 2. 문장 분리 ─────────────────────────────────────────────────────────────
# Bug 2 수정: 제목성 줄(헤더)을 split 단계에서 조기 차단해
#            NLLB 에 "헤더+인사말" 이 혼합된 채 전달되는 것을 방지.
_HEADER_ONLY = re.compile(
    r"^[^.,!?~]{2,40}(안내|공지|알림|공개수업|상담|학습|행사|일정)\s*$"
)


def split_sentences(text: str) -> list:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sentences = []
    for line in lines:
        if _HEADER_ONLY.match(line):   # 제목성 줄은 번역 대상에서 제외
            continue
        parts = re.split(
            r"(?<=[.!?])\s+|"
            r"(?<=다\.)\s+|(?<=요\.)\s+|(?<=니다\.)\s+|"
            r"(?<=까\?)\s+|(?<=요\?)\s+|"
            r"\s+(?=\d+[.)]\s)|\s+(?=[가-힣]\.\s)",
            line,
        )
        sentences.extend(parts)
    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]


# ── 3. 1차 필터 ──────────────────────────────────────────────────────────────
# Bug 1 수정: "안녕하세요" 계열 패턴 추가
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
    return not any(re.search(p, sentence) for p in NON_TODO_PATTERNS) and len(sentence) >= 7


# ── 4. 정규식 기반 구조 추출 ─────────────────────────────────────────────────
CURRENT_YEAR = 2026

DATE_PATTERN_ABS = re.compile(
    r"(?:(\d{1,2})\s*월\s*(\d{1,2})\s*일)|"
    r"(?<![\d.])(?<!mm)(?<!cm)(?<!원)(?<!시)"
    r"(\d{1,2})[./](\d{1,2})"
    r"(?!\d)(?![mc]m)(?!kg)"
)
DATE_PATTERN_REL = re.compile(
    r"(다음\s*주\s*[월화수목금토일]요일|"
    r"이번\s*주\s*[월화수목금토일]요일|"
    r"매주\s*[월화수목금토일]요일|"
    r"오늘|내일|모레)"
)
DEADLINE_PATTERN = re.compile(r"([\w가-힣\s]+?)\s*까지")

# Bug 3 메모:
#   MONEY_PATTERN 은 이미 \d+\s*원 형태 → "원하시는" 오탐 없음 (extraction 레벨 정상).
#   검수 상세 "원→won" 오탐은 translation_tts/run_mvp_pipeline.py 글로사리 로직 문제.
#   해당 파일에서 단순 str.contains("원") 대신
#   re.search(r"\d[\d,]*\s*원", text) 로 교체하면 해결.
MONEY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")


def extract_due_date(sentence: str) -> Optional[str]:
    m = DATE_PATTERN_ABS.search(sentence)
    if m:
        month = m.group(1) or m.group(3)
        day   = m.group(2) or m.group(4)
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
        t = m.group(1).strip()
        if t and len(t) < 20:
            return t
    return None


def has_money(sentence: str) -> bool:
    return bool(MONEY_PATTERN.search(sentence))


# ── 5. KoELECTRA 카테고리 분류 ───────────────────────────────────────────────
def classify_category(sentence: str) -> tuple:
    _load_model()
    inputs = _tokenizer(
        sentence, return_tensors="pt",
        truncation=True, padding=True, max_length=128,
    ).to(_device)
    with torch.no_grad():
        logits = _model(**inputs).logits
        probs  = torch.softmax(logits, dim=-1)[0]
        pred_id = int(torch.argmax(probs).item())
    return _id2label[pred_id], float(probs[pred_id].item())


# ── 6. importance 계산 ────────────────────────────────────────────────────────
CATEGORY_BASE_IMPORTANCE = {
    "제출": 1.0, "준비물": 0.85, "건강·안전": 0.80,
    "비용": 0.75, "일정": 0.70, "기타": 0.50,
}
URGENT_KEYWORDS = [
    "반드시", "꼭", "필수", "엄수", "마감", "당일", "즉시",
    "응급", "위급", "112", "신고",
]


def calc_importance(sentence: str, category: str, due_date: Optional[str]) -> float:
    score = CATEGORY_BASE_IMPORTANCE.get(category, 0.5)
    if any(kw in sentence for kw in URGENT_KEYWORDS):
        score = min(1.0, score + 0.05)
    if due_date:
        score = min(1.0, score + 0.05)
    if len(sentence) > 80:
        score = max(0.0, score - 0.05)
    return round(score, 2)


# ── 7. 메인 함수 ──────────────────────────────────────────────────────────────
def extract_todos(notice_text: str) -> list:
    if not notice_text or not notice_text.strip():
        return []
    todos = []
    for sent in [s for s in split_sentences(notice_text) if is_likely_todo(s)]:
        due_date = extract_due_date(sent)
        is_money = has_money(sent)
        if is_money:
            category, confidence = "비용", 1.0
        else:
            category, confidence = classify_category(sent)
        if confidence < 0.25 and not is_money:
            continue
        importance = calc_importance(sent, category, due_date)
        if importance < 0.25:
            continue
        text_ko = sent[:97] + "..." if len(sent) > 100 else sent
        if SCHEMAS_AVAILABLE:
            try:
                todos.append(TodoItem(
                    category=Category(category),
                    text_ko=text_ko, text_vi="",
                    importance=importance, due_date=due_date,
                ))
            except Exception as e:
                print(f"[WARN] TodoItem 생성 실패: {e}", file=sys.stderr)
                continue
        else:
            todos.append({
                "category": category, "text_ko": text_ko,
                "text_vi": "", "importance": importance, "due_date": due_date,
            })
    return todos


def extract_todos_dict(notice_text: str) -> list:
    items = extract_todos(notice_text)
    if SCHEMAS_AVAILABLE and items and isinstance(items[0], TodoItem):
        return [item.model_dump() for item in items]
    return items


if __name__ == "__main__":
    sample = """학부모 공개수업 및 상담 안내
학부모님 안녕하세요.
1. 공개수업 일시: 6월 12일(목) 3~4교시
2. 상담 신청: 6월 5일(금)까지 가정통신문 회신
3. 준비물: 실내화, 출입증 지참
수업료 50,000원은 6월 10일까지 납부해 주세요.
서울갈산초등학교장"""
    print("=" * 60)
    for i, t in enumerate(extract_todos_dict(sample), 1):
        print(f"{i}. [{t['category']}] importance={t['importance']} due={t['due_date']}")
        print(f"   {t['text_ko']}")
    print("=" * 60)
'''

new_code_predict = code_cell(
    'import pathlib\n\n'
    'PREDICT_PY = ' + repr(PREDICT_PY_CONTENT) + '\n\n'
    'out = pathlib.Path("./predict.py")\n'
    'out.write_text(PREDICT_PY, encoding="utf-8")\n'
    'print(f"predict.py 생성 완료 → {out.resolve()}")\n'
    'print(f"  크기: {out.stat().st_size:,} bytes")'
)

new_md_test = md_cell(
    "## 12. 추론 테스트 — 버그 수정 확인\n\n"
    "KoELECTRA 모델 없이도 돌아가는 **단위 테스트**. 수정된 패턴을 바로 검증.\n\n"
    "1. **Bug 1**: `학부모님 안녕하세요.` → TODO 제외 확인\n"
    "2. **Bug 2**: `학부모 공개수업 및 상담 안내` 헤더 줄 → split 단계에서 제거 확인\n"
    "3. **Bug 3**: `원하시는`, `원인` → `has_money()` = False 확인 (MONEY_PATTERN 정상)"
)

new_code_test = code_cell(
    r"""import re

# ── Bug 1 ─────────────────────────────────────────────────────────────────────
NON_TODO_PATTERNS_FIXED = [
    r"^학부모님\s*안녕하십니까",
    r"^안녕하십니까",
    r"^학부모님\s*안녕하세요",
    r"^안녕하세요",
    r"^.*님\s*안녕하(세요|십니까)",
    r"^학부모님께\s*안내드립니다",
    r"^학부모님께\s*드립니다",
    r"안내드립니다\s*\.?\s*$",
    r"드립니다\s*\.?\s*$",
    r"^[^.,!?]{1,30}\s*안내\s*$",
    r"서울갈산초등학교장$",
    r"교장$",
    r"^\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*$",
    r"담당\s*[:：]",
]


def is_likely_todo_fixed(s):
    return not any(re.search(p, s) for p in NON_TODO_PATTERNS_FIXED) and len(s) >= 7


bug1_cases = [
    ("학부모님 안녕하세요.",                False, "Bug1: 인사말"),
    ("안녕하세요.",                          False, "Bug1: 짧은 인사말"),
    ("학부모님 안녕하십니까.",               False, "기존 패턴 유지"),
    ("6월 5일까지 가정통신문 회신해주세요.", True,  "정상 TODO"),
    ("준비물: 실내화, 출입증 지참",           True,  "준비물 TODO"),
    ("2026. 4. 17.",                         False, "날짜 서명"),
]

print("[ Bug 1 — NON_TODO_PATTERNS 수정 확인 ]")
all_ok = True
for sentence, expected, label in bug1_cases:
    got = is_likely_todo_fixed(sentence)
    ok = got == expected
    all_ok = all_ok and ok
    print(f"  {'✅' if ok else '❌'} {label}: is_todo={got} (expected {expected})")
print("  →", "전체 PASS ✅" if all_ok else "일부 FAIL ❌")

# ── Bug 2 ─────────────────────────────────────────────────────────────────────
_HEADER_ONLY = re.compile(
    r"^[^.,!?~]{2,40}(안내|공지|알림|공개수업|상담|학습|행사|일정)\s*$"
)

bug2_cases = [
    ("학부모 공개수업 및 상담 안내",         True,  "공개수업 헤더"),
    ("현장학습 안내",                         True,  "현장학습 헤더"),
    ("방과후 영어 수업 일정",                True,  "일정 헤더"),
    ("6월 12일 공개수업 참석 부탁드립니다.", False, "일반 문장 (통과)"),
]

print("\n[ Bug 2 — 헤더 줄 필터 확인 ]")
all_ok2 = True
for line, expected_filter, label in bug2_cases:
    got = bool(_HEADER_ONLY.match(line))
    ok = got == expected_filter
    all_ok2 = all_ok2 and ok
    print(f"  {'✅' if ok else '❌'} {label}: filtered={got} (expected {expected_filter})")
print("  →", "전체 PASS ✅" if all_ok2 else "일부 FAIL ❌")

# ── Bug 3 ─────────────────────────────────────────────────────────────────────
MONEY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")

bug3_cases = [
    ("원하시는 날짜에 오세요.",        False, "Bug3: '원하시는' 오탐 없음"),
    ("원인 파악이 필요합니다.",         False, "Bug3: '원인' 오탐 없음"),
    ("수업료 50,000원을 납부하세요.",  True,  "정상 금액 매칭"),
    ("500원 잔돈 준비",                True,  "소액 금액 매칭"),
]

print("\n[ Bug 3 — MONEY_PATTERN 확인 (extraction 레벨) ]")
all_ok3 = True
for text, expected, label in bug3_cases:
    got = bool(MONEY_PATTERN.search(text))
    ok = got == expected
    all_ok3 = all_ok3 and ok
    print(f"  {'✅' if ok else '❌'} {label}: has_money={got} (expected {expected})")
print("  →", "전체 PASS ✅" if all_ok3 else "일부 FAIL ❌")

print()
print("※ Bug 3 검수 상세 '원→won' 오탐 본체:")
print("  translation_tts/run_mvp_pipeline.py 에서")
print(r"  str.contains('원') → re.search(r'\d[\d,]*\s*원', text) 로 교체 필요.")
"""
)

# 삽입: cell 18 다음 (index 19부터)
insert_at = 19
nb["cells"] = (
    nb["cells"][:insert_at]
    + [new_md_predict, new_code_predict, new_md_test, new_code_test]
    + nb["cells"][insert_at:]
)

# zip 셀: 기존 index 20 → 새 index 23 (4개 삽입됨)
zip_idx = 23
nb["cells"][zip_idx]["source"] = (
    "!zip -r koelectra-extractor.zip koelectra-extractor predict.py\n\n"
    "from google.colab import files\n"
    "files.download(\"koelectra-extractor.zip\")"
)

# 마지막 마크다운: 기존 index 21 → 새 index 24
nb["cells"][24]["source"] = (
    "## 끝\n\n"
    "다운받은 `koelectra-extractor.zip` 을 로컬에 풀고,\n"
    "`predict.py` 를 `model/extraction/` 에 두면 백엔드가 자동 로드해요.\n\n"
    "### 이번 수정 내역\n\n"
    "| 항목 | 변경 전 | 변경 후 |\n"
    "|------|---------|--------|\n"
    "| 학습 에폭 | 10 | 15 |\n"
    "| 학습률 | 3e-5 | 2e-5 |\n"
    "| 스케줄러 | linear | cosine + warmup 10% |\n"
    "| 손실 함수 | CrossEntropy (uniform) | **WeightedCrossEntropy** (balanced) |\n"
    "| NON_TODO_PATTERNS | `안녕하십니까`만 | `안녕하세요` 계열 3개 추가 |\n"
    "| 헤더 필터 | 없음 | `split_sentences()` 에서 제목성 줄 조기 차단 |\n"
    "| Bug 3 | — | `translation_tts/run_mvp_pipeline.py` 수정 필요 (주석 안내) |"
)

with open(NB_PATH, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

print(f"저장 완료. 총 셀 수: {len(nb['cells'])}")
for i, cell in enumerate(nb["cells"]):
    src = "".join(cell["source"])[:55].replace("\n", " ")
    print(f"  {i:2d}: {cell['cell_type'][:4]} | {src}")
