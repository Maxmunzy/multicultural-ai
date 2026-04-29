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

DEFAULT_INPUT  = _DATA / "sample_pdfplumber.txt"
DEFAULT_OUTPUT = _DATA / "notices_original2.jsonl"


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
    """
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
    """null byte / 캐리지 리턴 / 연속 공백 정리"""
    text = re.sub(r"\x00", "", text)       # pdfplumber null byte 잔여물
    text = text.replace("\r", "")          # Windows CR
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 3. 문장 분리 (kss 우선, 없으면 predict.py 의 split_sentences 사용)
# ─────────────────────────────────────────────────────────────────────────────
def _split_with_predict(text: str) -> list[str]:
    """predict.py 의 split_sentences 를 가져와서 사용"""
    predict_path = _HERE.parent / "predict.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("predict", predict_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod.split_sentences(text)
    except Exception as e:
        print(f"[경고] predict.split_sentences 로드 실패: {e}")
        # 최후 fallback: 마침표/물음표/느낌표 기준 단순 분리
        parts = re.split(r"(?<=[.!?])\s+", text)
        return [p.strip() for p in parts if p.strip() and len(p.strip()) > 3]


def split_into_sentences(text: str) -> list[str]:
    """kss 사용 시도 -> 실패하면 predict.split_sentences 사용"""
    try:
        import kss
        print("  kss 로 문장 분리 중...")
        return kss.split_sentences(text)
    except ImportError:
        print("  [kss 미설치] predict.split_sentences 로 대체합니다.")
        return _split_with_predict(text)


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
) -> None:
    print(f"입력: {input_path}")
    raw = input_path.read_text(encoding="utf-8")

    print("  줄 끊김 복원 중...")
    joined = join_broken_lines(raw)
    cleaned = clean_text(joined)

    sentences = split_into_sentences(cleaned)
    sentences = [s for s in sentences if len(s.strip()) > 3]

    mode = "a" if append else "w"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open(mode, encoding="utf-8") as f:
        for sent in sentences:
            record = build_record(sent)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\n완료: {len(sentences)}개 문장 -> {output_path}")
    print("  TIP: is_todo 필드를 채워야 학습 라벨이 생성됩니다.")
    print("       할 일 문장: is_todo = true")
    print("       노이즈 문장: is_todo = false (기본값, 수정 불필요)")


# ─────────────────────────────────────────────────────────────────────────────
# 6. CLI
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="PDF 추출 텍스트 -> notices_original2.jsonl 스키마 변환"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"입력 텍스트 파일 (기본: {DEFAULT_INPUT})",
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

    if not args.input.exists():
        print(f"[오류] 입력 파일이 없습니다: {args.input}", file=sys.stderr)
        sys.exit(1)

    preprocess_to_custom_schema(
        input_path=args.input,
        output_path=args.output,
        append=args.append,
    )


if __name__ == "__main__":
    main()
