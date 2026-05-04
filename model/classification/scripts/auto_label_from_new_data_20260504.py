"""
auto_label_from_new_data_20260504.py
=====================================
담당: 경이 (kyeongyi)
작성일: 2026-05-04
브랜치: feature/kyeongyi-classification

목적:
    윤정님이 새로 추가한 대용량 데이터(5,560행)에는 'is_todo' 정보만 있고
    '일정/준비물/제출/비용/건강·안전/기타' 라벨이 없다.
    이 스크립트는 키워드 규칙과 슬롯(amount, due_date, action_hint)을 이용해
    자동으로 카테고리를 부여하고, 기존 v3.csv와 합쳐 v4 학습 데이터를 생성한다.

왜 '자동 라벨링'을 썼나?
    1. 새 데이터 5,560행을 사람이 수작업으로 라벨링하면 수십 시간 걸림.
    2. 기존 라벨 데이터(v3.csv, 142행)만으로는 KcELECTRA 파인튜닝이 부족
       (BERT 계열은 최소 클래스당 50~100개, 전체 300~1000개 이상 필요).
    3. 키워드 기반 자동 라벨링 → 대량 데이터 확보 → KcELECTRA 재학습 → 성능 역전.

검증 방법:
    - 기존 라벨이 있는 v3.csv를 이 규칙으로 다시 분류 → 규칙 정확도 확인.
    - 규칙 정확도가 75% 이상이면 자동 라벨 데이터를 신뢰할 수 있다고 판단.

실행:
    cd model/classification
    python scripts/auto_label_from_new_data_20260504.py
"""

import json
import re
import csv
import random
from pathlib import Path
from collections import Counter

random.seed(42)   # 재현성 보장 — 누가 실행해도 동일한 분할·샘플 순서


# ──────────────────────────────────────────────────────────────────
# 1. 경로 설정
# ──────────────────────────────────────────────────────────────────
# 이 파일의 위치: model/classification/scripts/
# _BASE → model/classification/
_BASE = Path(__file__).parent.parent

DATA_DIR     = _BASE / "data"
EXTRACT_BASE = _BASE.parent.parent / "model" / "extraction"  # 윤정님 모델 폴더

# 입력 파일 (윤정님이 추가한 새 데이터)
SRC_TEST_DATA   = EXTRACT_BASE / "data" / "train" / "test_data.jsonl"
SRC_PREDICT_OUT = EXTRACT_BASE / "data" / "processed" / "predict_output_testset.jsonl"

# 기존 경이님 라벨 데이터
SRC_V3_CSV = DATA_DIR / "notice_sample_v3.csv"

# 출력 파일
OUT_CSV = DATA_DIR / "notice_sample_v4_20260504.csv"

# 6가지 분류 카테고리
LABELS = ["일정", "준비물", "제출", "비용", "건강·안전", "기타"]


# ──────────────────────────────────────────────────────────────────
# 2. 카테고리별 키워드 규칙
# ──────────────────────────────────────────────────────────────────
# 설계 원칙:
#   (a) 우선순위 순서로 검사 — 먼저 매칭된 카테고리를 반환하고 중단.
#   (b) 각 카테고리에서 가장 '강한' 신호(오탐 없는 단어)를 선택.
#   (c) 한국어는 조사·어미 변형이 많으므로 어근만 사용 (예: "납부" → "납부해", "납부하여" 모두 포함).
#   (d) 숫자 패턴은 정규표현식 사용 (예: "20,000원", "3만원" 등 다양한 금액 표현).
#
# 왜 이 순서인가?
#   비용 > 준비물 > 제출 > 건강·안전 > 일정 > 기타
#   → "3만 원을 5월 15일까지 납부" 같은 문장은 '비용'이 더 강한 신호.
#   → '일정'은 날짜 표현이 많아 오탐 위험이 있어 후순위.
#   → '기타'는 규칙 없이 나머지를 다 받는 쓰레기통 역할.

RULES: list[tuple[str, list[str]]] = [
    # ── 비용 ──
    # 금액·납부 관련 표현이 명확하게 있는 경우.
    # r"\d[\d,]*\s*원" : "65,000원", "3만원"은 이 정규식으로 포착.
    ("비용", [
        "납부",            # "납부해 주세요", "납부하여"
        "입금",            # "계좌로 입금"
        "계좌이체",        # "계좌이체해 주세요"
        "급식비",
        "참가비",
        "수강료",
        "교재비",
        "버스비",
        "이용료",
        "수업료",
        "구입비",
        "지원금",
        "면제",            # "급식비 면제 신청"
        "선납",            # "선납해 주세요"
        r"\d[\d,]*\s*원",  # 숫자+원 (20,000원, 3만원 등)
    ]),

    # ── 준비물 ──
    # 챙겨야 할 물건·복장 관련.
    # "마스크를" 처럼 뒤에 조사가 붙는 경우도 어근으로 포착.
    ("준비물", [
        "지참",            # "지참하시기 바랍니다"
        "챙겨",            # "챙겨주시기 바랍니다"
        "챙기",            # "챙기시기 바랍니다"
        "준비해",          # "준비해 주세요"
        "준비물",          # "학습 준비물"
        "가져오",          # "가져오세요"
        "착용",            # "착용하여 등교"
        "신고 오",         # "운동화를 신고 오세요"
        "복장",
        "도시락",
        "우산",
        "수영복",
        "실내화",
        "방한",            # "방한용품"
        "앞치마",
        "고무장갑",
        "배낭",
        "여벌",            # "여벌 옷"
        "스케치북",
        "색연필",
    ]),

    # ── 제출 ──
    # 서류·동의서·설문 등 무언가를 학교에 내야 하는 경우.
    ("제출", [
        "제출",            # "제출해 주세요", "제출하여"
        "동의서",          # "현장체험학습 동의서"
        "신청서",          # "급식 신청서"
        "설문",            # "온라인 설문에 응답"
        "서류를",
        "작성하여",        # "작성하여 제출"
        "응답해",          # "설문에 응답해 주세요"
        "기재",            # "기재해 주세요"
        "접수",
        "첨부",
        "등록",            # "회원 등록"
        "신청해",          # "신청해 주세요"
        "기한 내 신청",
        "아이 편에",       # "아이 편에 보내주시기"
        "담임선생님께 보내",
    ]),

    # ── 건강·안전 ──
    # 신체 관련, 안전사고 예방, 감염병 관련.
    ("건강·안전", [
        "발열",
        "기침",
        "증상",
        "예방접종",
        "백신",
        "감염",
        "방역",
        "소독",
        "위생",
        "자가진단",
        "결석",
        "질병",
        "코로나",
        "독감",
        "알레르기",
        "안전사고",
        "교통안전",
        "헬멧",
        "안전벨트",
        "온열",            # "온열 질환"
        "응급",
        "선별진료",
        "PCR",
        "진단키트",
        "확진",
        "수분 보충",
    ]),

    # ── 일정 ──
    # 날짜·시간·행사 관련. 비용/준비물/제출 보다 후순위인 이유:
    #   "3만 원을 5월 15일까지 납부" → 날짜가 있어도 '비용'이 정답.
    #   날짜 패턴은 오탐이 많아 '강한' 단어와 함께 쓸 때만 신뢰.
    ("일정", [
        r"\d+월\s*\d+일",      # "5월 20일", "3 월 7 일"
        r"\d{4}\.\s*\d+\.\s*\d+",  # "2025.05.20"
        r"\d+\.\s*\d+\.\s*\([월화수목금토일]\)",  # "5.20.(화)"
        "오전",                # "오전 9시"
        "오후",
        "~까지",               # "3월 20일~까지"
        "부터 ",               # "3월부터 "
        "기간",
        "주간",
        "방학",
        "개학",
        "졸업식",
        "입학식",
        "운동회",
        "수학여행",
        "체험학습",
        "현장학습",
        "학부모 총회",
        "공개수업",
        "학예발표",
        "체육대회",
        "생태체험",
        "시작합니다",
        "출발합니다",
        "진행됩니다",
        "실시됩니다",
        "열립니다",
        "개최됩니다",
    ]),
]
# RULES에 없는 문장 → "기타"로 분류


# ──────────────────────────────────────────────────────────────────
# 3. 정규표현식 여부 판별 헬퍼
# ──────────────────────────────────────────────────────────────────
def _is_regex(pattern: str) -> bool:
    """문자열 안에 정규표현식 특수문자가 있으면 True."""
    # \d, ^, $, |, ?, *, +, (, ), [, ], {, } 중 하나라도 있으면 regex
    regex_chars = r"\d^$.|?*+()[]{}".replace(".", r"\.")
    return bool(re.search(r"[\\^$.|?*+()\[\]{}]|\\d", pattern))


# ──────────────────────────────────────────────────────────────────
# 4. 핵심 분류 함수 (규칙 기반)
# ──────────────────────────────────────────────────────────────────
def label_by_keywords(text: str) -> str | None:
    """
    텍스트에 키워드·패턴이 포함되면 해당 카테고리를 반환.
    RULES 리스트 순서대로 검사 — 첫 매칭에서 즉시 반환.
    없으면 None 반환 (→ 슬롯 기반 분류로 넘어감).
    """
    for category, patterns in RULES:
        for pat in patterns:
            if _is_regex(pat):
                if re.search(pat, text):
                    return category
            else:
                if pat in text:
                    return category
    return None


def label_by_slots(
    action_hint: str | None,
    amount: str | None,
    due_date: str | None,
) -> str | None:
    """
    윤정님 추출 모델이 뽑은 슬롯 정보를 이용한 보조 분류.
    키워드 규칙이 None을 반환했을 때만 호출.

    논리:
      - amount 있음  → 비용 관련 문장일 가능성이 높다
      - action_hint = "제출"/"신청" → 제출 카테고리
      - action_hint = "준비"/"지참" → 준비물 카테고리
      - due_date 있음 + 비용/제출 키워드 없음 → 일정 관련
    """
    if amount:
        return "비용"
    if action_hint in ("제출", "신청", "작성"):
        return "제출"
    if action_hint in ("준비", "지참", "착용"):
        return "준비물"
    if due_date:
        # 날짜가 있으나 다른 강한 신호가 없으면 일정
        return "일정"
    return None


def classify(
    text: str,
    action_hint: str | None = None,
    amount: str | None = None,
    due_date: str | None = None,
) -> str | None:
    """
    최종 분류 함수.
    1단계: 키워드 규칙 (빠르고 명확)
    2단계: 슬롯 기반 (윤정님 추출 정보 활용)
    모두 실패하면 None → 이 문장은 학습 데이터에서 제외 (노이즈 방지).

    '기타'를 일부러 규칙에 넣지 않은 이유:
      규칙으로 잡히지 않는 문장이 전부 기타가 되면 기타 데이터가
      너무 많아지고, 오탐(실제론 일정인데 기타로 잡힌 것)도 섞임.
      → 기타는 별도 limit을 두지 않고 "나머지"로만 수집.
    """
    label = label_by_keywords(text)
    if label:
        return label
    label = label_by_slots(action_hint, amount, due_date)
    if label:
        return label
    return None   # 애매한 문장은 버린다


# ──────────────────────────────────────────────────────────────────
# 5. 데이터 로드 함수
# ──────────────────────────────────────────────────────────────────
def load_test_data() -> list[dict]:
    """
    test_data.jsonl : {text, is_todo}
    is_todo = True인 행만 사용.
    이유: False인 행은 학교 공지 중 '할 일이 없는' 순수 안내 문장.
    분류 모델의 목적(학부모가 해야 할 행동 분류)에 맞지 않아 제외.
    """
    rows = []
    with open(SRC_TEST_DATA, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("is_todo") is True:
                rows.append({
                    "text":        d["text"],
                    "action_hint": None,   # 이 파일엔 슬롯 정보 없음
                    "amount":      None,
                    "due_date":    None,
                })
    return rows


def load_predict_output() -> list[dict]:
    """
    predict_output_testset.jsonl : {text, source, due_date, amount,
                                     confidence, action_hint, true_is_todo}

    필터 기준:
      - true_is_todo = True  : 명확하게 할 일인 문장
      - confidence >= 0.7    : 윤정님 모델이 확신하는 문장
    이 두 조건 중 하나라도 만족하면 사용.
    슬롯(amount, due_date, action_hint)은 자동 라벨링 2단계(label_by_slots)에 활용.
    """
    rows = []
    with open(SRC_PREDICT_OUT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            is_todo   = d.get("true_is_todo") is True
            high_conf = d.get("confidence", 0) >= 0.7
            if is_todo or high_conf:
                rows.append({
                    "text":        d["text"],
                    "action_hint": d.get("action_hint"),
                    "amount":      d.get("amount"),
                    "due_date":    d.get("due_date"),
                })
    return rows


def load_v3_csv() -> list[tuple[str, str]]:
    """
    기존에 경이님이 직접 라벨링한 notice_sample_v3.csv 로드.
    컬럼: text, category
    """
    rows = []
    with open(SRC_V3_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = row.get("text", "").strip()
            cat  = row.get("category", "").strip()
            if text and cat in LABELS:
                rows.append((text, cat))
    return rows


# ──────────────────────────────────────────────────────────────────
# 6. 규칙 검증 함수 — 기존 라벨 데이터로 규칙 정확도 측정
# ──────────────────────────────────────────────────────────────────
def validate_rules(v3_rows: list[tuple[str, str]]) -> float:
    """
    v3.csv는 경이님이 직접 라벨링한 '정답 데이터'다.
    이 정답 데이터에 자동 라벨링 규칙을 적용해 몇 %나 맞히는지 확인.

    목표: 75% 이상 → 자동 라벨 데이터를 신뢰할 수 있다고 판단.
    낮으면 규칙을 수정해야 함.
    """
    correct = 0
    total   = 0
    errors  = []

    for text, true_cat in v3_rows:
        pred = classify(text)
        if pred is None:
            pred = "기타"   # 규칙 미매칭 → 기타로 간주
        total += 1
        if pred == true_cat:
            correct += 1
        else:
            errors.append((text[:40], true_cat, pred))

    accuracy = correct / total if total > 0 else 0.0

    print("\n[규칙 검증] v3.csv 기준 자동 라벨링 정확도")
    print(f"  정답: {correct}/{total} = {accuracy:.1%}")

    if errors:
        print(f"  오분류 예시 (상위 10개):")
        for txt, true, pred in errors[:10]:
            print(f"    [{true}→{pred}] {txt}")

    if accuracy >= 0.75:
        print("  [OK] 규칙 신뢰도 충분 (75% 이상) -> 자동 라벨 데이터 채택")
    else:
        print("  [경고] 규칙 신뢰도 부족 -- 규칙을 추가/수정할 것을 권장")

    return accuracy


# ──────────────────────────────────────────────────────────────────
# 7. 라벨링 + 필터링
# ──────────────────────────────────────────────────────────────────
MIN_TEXT_LEN = 10   # 10글자 미만 단편 문장은 노이즈 가능성이 높아 제외


def label_all(rows: list[dict]) -> list[tuple[str, str]]:
    """
    rows 각각에 classify()를 적용해 (text, category) 쌍 반환.
    - MIN_TEXT_LEN 미만 → 제외
    - classify() 결과가 None → 제외 (애매한 문장)
    """
    labeled: list[tuple[str, str]] = []
    for r in rows:
        text = r["text"].strip()
        if len(text) < MIN_TEXT_LEN:
            continue
        cat = classify(text, r.get("action_hint"), r.get("amount"), r.get("due_date"))
        if cat:
            labeled.append((text, cat))
        else:
            # 규칙·슬롯 미매칭 문장은 '기타'로 넣되, 별도 카운터로 제한
            labeled.append((text, "기타"))
    return labeled


MAX_NEW_PER_LABEL = 120   # 새 데이터에서 카테고리당 최대 수집 수
# 이유: 너무 많으면 노이즈가 늘어나고, 클래스 불균형도 발생.
# 기존 v3(약 25/카테고리) + 신규(최대 120/카테고리) → 전체 약 900개 목표.


def balance_new_data(
    labeled: list[tuple[str, str]],
    max_per: int,
) -> list[tuple[str, str]]:
    """
    카테고리별로 max_per 개까지만 샘플링.
    random.shuffle(seed=42)로 무작위 선택 → 재현 가능.

    왜 균형이 필요한가?
      KcELECTRA 파인튜닝 시 특정 클래스 데이터가 너무 많으면
      모델이 그 클래스로 편향됨 (기존 문제와 동일한 class collapse 현상).
    """
    buckets: dict[str, list[str]] = {l: [] for l in LABELS}
    for text, cat in labeled:
        if cat in buckets:
            buckets[cat].append(text)

    result: list[tuple[str, str]] = []
    for cat, texts in buckets.items():
        random.shuffle(texts)
        for t in texts[:max_per]:
            result.append((t, cat))
    return result


# ──────────────────────────────────────────────────────────────────
# 8. 중복 제거
# ──────────────────────────────────────────────────────────────────
def remove_duplicates(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    동일 텍스트가 두 번 이상 나타나면 첫 번째만 유지.
    왜 필요한가?
      test_data.jsonl과 predict_output_testset.jsonl이 같은 원본에서
      파생됐기 때문에 중복 문장이 존재할 수 있음.
      중복이 있으면 test 세트에도 같은 문장이 들어가 평가가 부풀려짐.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for text, cat in rows:
        if text not in seen:
            seen.add(text)
            out.append((text, cat))
    return out


# ──────────────────────────────────────────────────────────────────
# 9. 저장
# ──────────────────────────────────────────────────────────────────
def save_csv(rows: list[tuple[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        # quoting=QUOTE_ALL : 쉼표·줄바꿈 포함 텍스트도 안전하게 저장
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["text", "category"])
        for text, cat in rows:
            writer.writerow([text, cat])
    print(f"\n[저장] {path}  ({len(rows)}행)")


# ──────────────────────────────────────────────────────────────────
# 10. 메인 실행
# ──────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  자동 라벨링 파이프라인 시작  (2026-05-04)")
    print("=" * 60)

    # Step A: 기존 라벨 데이터 로드
    v3_rows = load_v3_csv()
    print(f"\n[A] 기존 v3.csv: {len(v3_rows)}개")
    cnt_v3 = Counter(cat for _, cat in v3_rows)
    for l in LABELS:
        print(f"     {l}: {cnt_v3.get(l, 0)}개")

    # Step B: 규칙 검증 (v3.csv 기준)
    rule_acc = validate_rules(v3_rows)

    # Step C: 새 데이터 로드
    print("\n[C] 새 데이터 로드")
    test_rows    = load_test_data()
    predict_rows = load_predict_output()
    print(f"  test_data.jsonl  (is_todo=True): {len(test_rows):,}개")
    print(f"  predict_output   (필터 후):       {len(predict_rows):,}개")

    # Step D: 자동 라벨링
    print("\n[D] 자동 라벨링 중...")
    labeled_test    = label_all(test_rows)
    labeled_predict = label_all(predict_rows)
    all_new = labeled_test + labeled_predict
    print(f"  라벨링 완료: {len(all_new):,}개")
    cnt_new = Counter(cat for _, cat in all_new)
    for l in LABELS:
        print(f"  {l}: {cnt_new.get(l, 0)}개")

    # Step E: 균형 조정 (카테고리당 최대 MAX_NEW_PER_LABEL개)
    balanced = balance_new_data(all_new, MAX_NEW_PER_LABEL)
    print(f"\n[E] 균형 조정 후: {len(balanced)}개")
    cnt_bal = Counter(cat for _, cat in balanced)
    for l in LABELS:
        print(f"  {l}: {cnt_bal.get(l, 0)}개")

    # Step F: 기존 v3 + 새 데이터 병합 → 중복 제거
    combined = v3_rows + balanced
    combined = remove_duplicates(combined)
    random.shuffle(combined)   # 파일 내 순서 무작위화
    print(f"\n[F] 최종 병합 (중복 제거 후): {len(combined)}개")
    cnt_final = Counter(cat for _, cat in combined)
    for l in LABELS:
        print(f"  {l}: {cnt_final.get(l, 0)}개")

    # Step G: 저장
    save_csv(combined, OUT_CSV)

    # 최종 요약
    print("\n" + "=" * 60)
    print("  완료 요약")
    print("=" * 60)
    print(f"  기존 v3.csv:          {len(v3_rows):>4}개")
    print(f"  새 데이터 (균형 후):  {len(balanced):>4}개")
    print(f"  최종 v4 (중복 제거):  {len(combined):>4}개")
    print(f"  규칙 정확도:          {rule_acc:.1%}")
    print(f"  출력: {OUT_CSV}")
    print()
    print("다음 단계:")
    print("  python scripts/split_dataset.py --data v4_20260504 --force")
    print("  python src/classifier_simple.py   (베이스라인 재학습)")
    print("  Colab에서 notebooks/03_train_kcelectra_v2_20260504.ipynb 실행")


if __name__ == "__main__":
    main()
