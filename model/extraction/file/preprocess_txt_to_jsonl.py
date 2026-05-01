"""
preprocess_schema_matched.py
============================
PDF 추출 텍스트(.txt) -> notices_original2.jsonl 스키마 변환

[처리 흐름]
  1. 텍스트 전체 로드
  2. join_broken_lines(): PDF 줄 중간 끊김 복원
       - 단어 중간 끊김: "다문화가정 학\n생" -> "다문화가정 학생"  (공백 없이)
       - 문장 이어짐    : "지원하기\n위해"   -> "지원하기 위해"     (공백으로)
       - 문장 종결 후   : "제공합니다.\n..." -> 줄바꿈 유지
  3. kss.split_sentences() 로 문장 분리
       - kss 미설치 시 predict.py 의 split_sentences() 로 자동 대체
  4. 문장별 JSONL 레코드 생성 (notices_original2.jsonl 스키마)
  5. 저장

[출력 스키마 - 문장 단위]
  {"id":1, "source_type":"초등학교", "original_text":"<문장>",
   "category":"", "keywords":"", ...}

  ※ keywords 필드를 채워야 학습 라벨이 생성됩니다.
    - 해당 문장이 할 일이면: keywords = 문장 그대로 복사
    - 노이즈면            : keywords = "" (비워두기)

[사용법]
  # 기본 (data/ 폴더 안의 파일 사용)
  python file/preprocess_schema_matched.py

  # 경로 직접 지정
  python file/preprocess_schema_matched.py \\
      --input  data/sample_pdfplumber.txt \\
      --output data/notices_original2.jsonl \\
      --source_type 초등학교
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Windows 터미널 UTF-8 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── 기본 경로 (스크립트 위치 기준) ──────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent          # .../file/
_DATA = _HERE.parent / "data"                    # .../data/

DEFAULT_INPUT     = _DATA / "sample_pdfplumber.txt"
DEFAULT_INPUT_DIR = _DATA / "galsan_txt"
DEFAULT_OUTPUT    = _DATA / "notices_original2.jsonl"

# ─────────────────────────────────────────────────────────────────────────────
# 0. 급식 파일 감지 — 파일명 또는 내용 기반
# ─────────────────────────────────────────────────────────────────────────────
# 파일명 기반 스킵 없음 — 내용 기반 패턴만 사용
# (파일명에 '급식'이 있어도 정보 전달 목적 파일은 처리해야 하므로)
_MEAL_NAME_KEYWORDS: list[str] = []

# 내용에 이 패턴 중 하나라도 있으면 급식표로 판단 → 스킵
# 모두 실제 식단표에만 등장하는 패턴 (공사 안내·의견조사·알레르기 조사 등에는 없음)
_MEAL_CONTENT_PATTERNS: list[re.Pattern] = [
    re.compile(r"에너지/단백질"),       # 급식 영양표 헤더
    re.compile(r"①난류\s*②우유"),      # 알레르기 번호 리스트
    re.compile(r"무상급식비\s*:"),      # 급식비 안내
    re.compile(r"\d+회\s*무상급식"),    # "20회 무상급식비"
]


def is_meal_schedule(path: Path, content: str) -> bool:
    """파일명 또는 내용 기반으로 급식 파일 여부 판별"""
    # 1차: 파일명 확인 (빠름)
    name = path.stem  # 확장자 제외 파일명
    if any(kw in name for kw in _MEAL_NAME_KEYWORDS):
        return True
    # 2차: 내용 확인 (파일명에 '급식'이 없어도 내용에 급식 표가 있는 경우)
    return any(pat.search(content) for pat in _MEAL_CONTENT_PATTERNS)


# ─────────────────────────────────────────────────────────────────────────────
# 1. PDF 줄 중간 끊김 복원
# ─────────────────────────────────────────────────────────────────────────────
def join_broken_lines(text: str) -> str:
    """
    PDF 추출 시 발생하는 두 종류의 줄 끊김을 복원합니다.

    규칙 1 - 단어 중간 끊김 (공백 없이 연결):
      공백 뒤에 오는 한글 + 줄바꿈 + 한글
      예: "다문화가정 학\\n생" -> "다문화가정 학생"
      이유: 마지막 한글 앞에 공백이 있으면 그 한글이 단어의 첫 글자
            -> 줄바꿈이 단어를 끊은 것이므로 공백 없이 붙임

    규칙 2 - 문장 이어짐 (공백으로 연결):
      종결 부호(.!?) 없이 끝나는 줄 + 줄바꿈 + 다음 줄
      예: "지원하기\\n위해" -> "지원하기 위해"

    규칙 3 - 문장 종결 후 (줄바꿈 유지):
      종결 부호(.!?)로 끝나는 줄 -> 줄바꿈 그대로
      예: "제공합니다.\\n모국어를" -> 변경 없음

    규칙 0 (선행) - 날짜/숫자 분절 복원:
      숫자마침표로 끝나는 줄 -> 줄바꿈을 공백으로 이어줌
      예: "2026.\\n~ 11." -> "2026. ~ 11."
      이유: 한국식 날짜(2026.~11.30.)는 마침표가 구분자이므로
            규칙 3이 적용되면 날짜가 조각남
    """
    # 규칙 0: 숫자마침표로 끝나는 줄 → 공백으로 이어줌 (날짜 분절 복원)
    text = re.sub(r"(\d+\.)\n", r"\1 ", text)

    # 규칙 1: 공백 + 한글 + 줄바꿈 + 한글  ->  공백 + (두 한글 합침)
    text = re.sub(r" ([가-힣])\n([가-힣])", r" \1\2", text)

    # 규칙 2: 종결 부호 없이 끝나는 줄  ->  공백으로 이어줌
    #   ([^.!?\n] = 줄바꿈도 종결 부호도 아닌 임의의 글자)
    text = re.sub(r"([^.!?\n])\n([^\n])", r"\1 \2", text)

    # 연속 공백 정리
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2. 기본 텍스트 정리
# ─────────────────────────────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    """null byte / 캐리지 리턴 / 연속 공백 정리 (기호 정제는 split 이후 clean_sentence 에서)"""
    text = re.sub(r"\x00", "", text)       # pdfplumber null byte 잔여물
    text = text.replace("\r", "")          # Windows CR
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# 특정 기호 → ASCII 대응 문자로 변환
_NORMALIZE_TABLE = str.maketrans({
    '‘': "'",  '’': "'",   # ' '  →  '
    '“': '"',  '”': '"',   # " "  →  "
    '「': '"',  '」': '"',   # 「」 →  "
    '『': '"',  '』': '"',   # 『』 →  "
    '【': '(',  '】': ')',   # 【】 →  ()
    '〔': '(',  '〕': ')',   # 〔〕 →  ()
    '｢': '"',  '｣': '"',   # ｢｣  →  "
    '–': '-',  '—': '-',   # –—  →  -
    '～': '~',  '∼': '~',   # ～∼ →  ~
    '，': ',',                   # ，  →  ,
    '×': 'x',                   # ×   →  x
    '·': ' ',  '･': ' ',   # ·･  →  공백
    '・': ' ',  '〃': ' ',   # ・〃 →  공백
    '…': '...',                  # …   →  ...
    '­': '',                     # soft hyphen → 제거
    '￦': '',                    # ￦  →  제거
})

# 한글/영숫자/허용 구두점 이외의 모든 기호를 공백으로 대체
_SYMBOL_REMOVE_RE = re.compile(
    "[^가-힣"   # 한글 완성형
    "㄰-㆏"     # 한글 자모
    "a-zA-Z0-9"         # 영숫자
    " \\t.,!?():/%@~&_\\-'\"]"  # 허용 구두점 + 공백
)


def clean_sentence(sentence: str) -> str:
    """문장 단위 기호 정제: 정규화 후 허용 문자 외 기호 공백으로 대체"""
    sentence = sentence.translate(_NORMALIZE_TABLE)
    sentence = _SYMBOL_REMOVE_RE.sub(' ', sentence)
    return re.sub(r"\s+", " ", sentence).strip()


# ─────────────────────────────────────────────────────────────────────────────
# 3. 문장 분리 (predict.py 의 split_sentences 사용, 최초 1회만 로드)
# ─────────────────────────────────────────────────────────────────────────────
_predict_mod = None   # 모듈 캐시 — exec_module 은 최초 1회만 실행


def _get_split_fn():
    """predict.split_sentences 를 반환. 실패 시 정규식 fallback 반환."""
    global _predict_mod
    if _predict_mod is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("predict", _HERE / "predict.py")
        if spec is not None:
            _predict_mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(_predict_mod)
                print("  predict.split_sentences 로드 완료 (이후 재사용)")
            except Exception as e:
                print(f"  [경고] predict.py 로드 실패: {e}")
                _predict_mod = None

    if _predict_mod is not None:
        return _predict_mod.split_sentences

    # 최후 fallback: 마침표/물음표/느낌표 기준 단순 분리
    def _simple_split(text: str) -> list[str]:
        parts = re.split(
            r"(?<!\d\.)(?<=[.!?])\s+"      # 숫자마침표(날짜) 뒤는 분리 안 함
            r"|\s+(?=[1-9]\.\s+[가-힣])",  # "4. 한글" 앞 공백 → 1~9번 목록 항목 시작
            text,
        )
        return [p.strip() for p in parts if p.strip() and len(p.strip()) > 3]
    return _simple_split


def split_into_sentences(text: str) -> list[str]:
    return _get_split_fn()(text)


# ─────────────────────────────────────────────────────────────────────────────
# 4. JSONL 레코드 생성
# ─────────────────────────────────────────────────────────────────────────────
def build_record(sentence: str) -> dict:
    """
    train_koelectra.ipynb 의 문장 단위 포맷 (text + is_todo) 으로 반환.
    is_todo 기본값은 false — 라벨링 시 할 일 문장만 true 로 바꾸면 됩니다.
    """
    return {
        "text":    sentence,
        "is_todo": False,   # 할 일 문장이면 True 로 수정
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. 메인 변환 함수
# ─────────────────────────────────────────────────────────────────────────────
def preprocess_to_custom_schema(
    input_path: Path,
    output_path: Path,
    append: bool = False,
) -> int:
    """
    단일 txt 파일을 처리해 JSONL 에 추가.

    Returns:
        추가된 문장 수. 급식 파일이면 -1 반환.
    """
    raw = input_path.read_text(encoding="utf-8")

    if is_meal_schedule(input_path, raw):
        print(f"  [스킵] 급식 파일 감지: {input_path.name}")
        return -1

    joined  = join_broken_lines(raw)
    pre_cleaned = clean_text(joined)              # null byte / CR / 공백만

    raw_sents = split_into_sentences(pre_cleaned) # 마커 기준 분리 먼저
    sentences = [
        clean_sentence(s) for s in raw_sents      # 분리 후 기호 정제
        if len(clean_sentence(s)) > 3
    ]

    mode = "a" if append else "w"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open(mode, encoding="utf-8") as f:
        for sent in sentences:
            f.write(json.dumps(build_record(sent), ensure_ascii=False) + "\n")

    return len(sentences)


# ─────────────────────────────────────────────────────────────────────────────
# 6. CLI
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="PDF 추출 텍스트 -> JSONL 변환 (급식 파일 자동 스킵)"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="단일 txt 파일 처리",
    )
    parser.add_argument(
        "--input_dir",
        type=Path,
        default=None,
        help=f"폴더 내 모든 txt 파일 일괄 처리 (기본: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"출력 JSONL 파일 (기본: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="기존 JSONL 파일에 이어쓰기",
    )
    args = parser.parse_args()

    # ── 입력 파일 목록 결정 ────────────────────────────────────────────────────
    if args.input:
        if not args.input.exists():
            print(f"[오류] 파일 없음: {args.input}", file=sys.stderr)
            sys.exit(1)
        txt_files = [args.input]
    else:
        target_dir = args.input_dir or DEFAULT_INPUT_DIR
        if not target_dir.exists():
            print(f"[오류] 폴더 없음: {target_dir}", file=sys.stderr)
            sys.exit(1)
        txt_files = sorted(target_dir.glob("*.txt"))
        print(f"폴더: {target_dir}  ({len(txt_files)}개 txt 파일 발견)\n")

    # ── 일괄 처리 ──────────────────────────────────────────────────────────────
    total_sentences = 0
    skipped         = []

    for i, txt_path in enumerate(txt_files):
        # 첫 파일은 append 여부를 그대로 사용, 이후는 항상 이어쓰기
        use_append = args.append if i == 0 else True

        result = preprocess_to_custom_schema(
            input_path=txt_path,
            output_path=args.output,
            append=use_append,
        )

        if result == -1:
            skipped.append(txt_path.name)
        else:
            print(f"  [완료] {txt_path.name}  ({result}개 문장)")
            total_sentences += result

    # ── 최종 요약 ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print(f"처리 완료: {len(txt_files) - len(skipped)}개 파일  |  {total_sentences}개 문장")
    print(f"스킵 (급식): {len(skipped)}개 파일")
    if skipped:
        for name in skipped:
            print(f"  - {name}")
    print(f"저장 위치: {args.output}")
    print("=" * 55)
    print("TIP: is_todo 필드를 채워야 학습 라벨이 생성됩니다.")
    print("     할 일 문장 -> is_todo = true")


if __name__ == "__main__":
    main()
