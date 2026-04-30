"""
txt_to_jsonl.py
===============
PDF 추출 텍스트 파일(.txt) → notices_original2.jsonl 스키마 변환

[전처리 파이프라인]
  1. join_broken_lines()   PDF 추출 시 생기는 줄 중간 끊김 복원
       - 단어 중간 끊김: "다문화가정 학\n생" → "다문화가정 학생" (공백 없이)
       - 문장 이어짐    : "지원하기\n위해"   → "지원하기 위해"  (공백으로)
       - 문장 종결 후   : "제공합니다.\n..."  → 줄바꿈 유지
  2. clean_text()          연속 공백·줄바꿈 정규화
  3. JSONL 저장            notices_original2.jsonl 스키마와 1:1 대응

[출력 스키마]
  문서 단위 포맷 (train_koelectra.ipynb이 자동 인식):
  {"id":..., "source_type":..., "original_text":...,
   "category":"", "keywords":"", "importance":"",
   "action_required":"", "easy_korean":"", "vietnamese":"", "tts_target":""}

  ※ category / keywords 는 사후 수동 라벨링 필요

[사용법]
  # 단일 파일
  python txt_to_jsonl.py --input data/sample_pdfplumber.txt \\
                         --output data/notices_original2.jsonl \\
                         --source_type 초등학교

  # 여러 파일 → 기존 JSONL 에 이어쓰기
  python txt_to_jsonl.py --input data/*.txt \\
                         --output data/notices_original2.jsonl \\
                         --source_type 유치원 --append

  # 전처리 결과 미리보기 (저장 없음)
  python txt_to_jsonl.py --input data/sample_pdfplumber.txt --preview
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Windows 터미널 UTF-8 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. 줄 중간 끊김 복원
# ─────────────────────────────────────────────────────────────────────────────
def join_broken_lines(text: str) -> str:
    """
    PDF 추출 텍스트에서 줄 중간에 끊긴 문장을 복원합니다.

    규칙:
      ① 공백 + [한글] + 줄바꿈 + [한글]
         → 공백 + [두 한글 합침] (단어 중간 끊김 복원)
         예: "다문화가정 학\\n생" → "다문화가정 학생"

      ② [.!? 아닌 글자] + 줄바꿈 + [다음 줄 내용]
         → 공백으로 연결 (문장 이어짐)
         예: "지원하기\\n위해" → "지원하기 위해"

      ③ [.!?] + 줄바꿈
         → 줄바꿈 유지 (문장 종결, 분리 보존)
         예: "제공합니다.\\n모국어를" → 변경 없음
    """
    # ① 단어 중간 끊김: 공백 뒤에 오는 한글이 줄바꿈 후 한글로 이어짐
    #    (앞에 공백이 있다는 것 = 그 한글이 단어의 첫 글자 = 단어가 잘림)
    text = re.sub(r' ([가-힣])\n([가-힣])', r' \1\2', text)

    # ② 문장 이어짐: 종결 부호 없이 끝나는 줄 → 다음 줄과 공백으로 연결
    #    ([^.!?\n] = 줄바꿈도 종결 부호도 아닌 모든 글자)
    text = re.sub(r'([^.!?\n])\n([^\n])', r'\1 \2', text)

    # 연속 공백 정리
    text = re.sub(r'[ \t]+', ' ', text)

    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2. 기본 텍스트 정리
# ─────────────────────────────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    """
    연속 공백 / 줄바꿈 / PDF 추출 잔여 바이트 정규화.
    - null byte(), 캐리지 리턴(
) 제거
    - 연속 공백 -> 단일 공백
    - 3개 이상 줄바꿈 -> 두 줄바꿈
    """
    text = re.sub(r'', '', text)          # null byte 제거 (pdfplumber 잔여물)
    text = text.replace('', '')             # Windows CR 제거
    text = re.sub(r'[ 	]+', ' ', text)
    text = re.sub(r'{3,}', '', text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 3. JSONL 레코드 생성
# ─────────────────────────────────────────────────────────────────────────────
def build_record(
    record_id: int,
    source_type: str,
    original_text: str,
) -> dict:
    """notices_original2.jsonl 스키마와 1:1 대응하는 레코드 반환"""
    return {
        "id":             record_id,
        "source_type":    source_type,
        "original_text":  original_text,
        "category":       "",   # 수동 라벨링 필요
        "keywords":       "",   # 수동 라벨링 필요 (학습 품질에 직결)
        "importance":     "",
        "action_required": "",
        "easy_korean":    "",
        "vietnamese":     "",
        "tts_target":     "",
    }


def process_file(txt_path: Path, source_type: str) -> tuple[str, str]:
    """
    텍스트 파일 1개를 전처리하여 (raw_text, clean_original_text) 반환.
    preview 모드에서 두 값을 비교할 수 있도록 raw 도 함께 반환.
    """
    raw = txt_path.read_text(encoding="utf-8")
    cleaned = clean_text(join_broken_lines(raw))
    return raw, cleaned


# ─────────────────────────────────────────────────────────────────────────────
# 4. 기존 JSONL 마지막 id 파악 (이어쓰기용)
# ─────────────────────────────────────────────────────────────────────────────
def last_id_in_jsonl(path: Path) -> int:
    """기존 JSONL 파일의 마지막 id 반환. 파일 없으면 0."""
    if not path.exists():
        return 0
    last_id = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                last_id = json.loads(line).get("id", last_id)
            except json.JSONDecodeError:
                continue
    return last_id


# ─────────────────────────────────────────────────────────────────────────────
# 5. 미리보기 (--preview)
# ─────────────────────────────────────────────────────────────────────────────
def preview(txt_path: Path) -> None:
    """전처리 전후 비교 출력 (저장 없음)"""
    raw, cleaned = process_file(txt_path, source_type="")

    print("=" * 70)
    print(f"파일: {txt_path.name}")
    print("=" * 70)

    print("\n[원본 텍스트 - 처음 10줄]")
    for i, line in enumerate(raw.splitlines()[:10], 1):
        print(f"  {i:02d} │ {line}")

    print("\n[전처리 후 original_text - 처음 500자]")
    print(f"  {cleaned[:500]}")
    if len(cleaned) > 500:
        print(f"  ... (총 {len(cleaned)}자)")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# 6. 변환 실행
# ─────────────────────────────────────────────────────────────────────────────
def convert(
    input_paths: list[Path],
    output_path: Path,
    source_type: str,
    append: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start_id = (last_id_in_jsonl(output_path) + 1) if append else 1
    mode = "a" if append else "w"

    written = 0
    with output_path.open(mode, encoding="utf-8") as f:
        for txt_path in input_paths:
            record_id = start_id + written
            _, cleaned = process_file(txt_path, source_type)
            record = build_record(record_id, source_type, cleaned)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  [{record_id}] {txt_path.name}  ({len(cleaned):,}자)")
            written += 1

    print(f"\n완료: {written}개 파일 → {output_path}")
    print("⚠️  keywords 필드를 직접 채워야 학습 라벨이 정상 생성됩니다.")


# ─────────────────────────────────────────────────────────────────────────────
# 7. CLI
# ─────────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="PDF 추출 텍스트(.txt) → notices_original2.jsonl 변환",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input", nargs="+", required=True,
        help="입력 텍스트 파일 경로 (여러 개 가능, glob 사용 가능)",
    )
    p.add_argument(
        "--output", default=None,
        help="출력 JSONL 파일 경로 (--preview 시 불필요)",
    )
    p.add_argument(
        "--source_type", default="초등학교",
        help="문서 출처 (예: 유치원, 초등학교, 중학교). 기본값: 초등학교",
    )
    p.add_argument(
        "--append", action="store_true",
        help="기존 JSONL 파일에 이어쓰기 (id 자동 증가)",
    )
    p.add_argument(
        "--preview", action="store_true",
        help="전처리 결과 미리보기만 출력, 저장 안 함",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    # 입력 파일 수집
    input_paths: list[Path] = []
    for pattern in args.input:
        matched = sorted(Path(".").glob(pattern)) if "*" in pattern else [Path(pattern)]
        input_paths.extend(matched)

    missing = [p for p in input_paths if not p.exists()]
    if missing:
        print(f"[오류] 파일을 찾을 수 없습니다: {missing}", file=sys.stderr)
        sys.exit(1)

    if not input_paths:
        print("[오류] 입력 파일이 없습니다.", file=sys.stderr)
        sys.exit(1)

    # 미리보기 모드
    if args.preview:
        for p in input_paths:
            preview(p)
        return

    # 저장 모드
    if not args.output:
        print("[오류] --output 경로를 지정해주세요.", file=sys.stderr)
        sys.exit(1)

    convert(
        input_paths=input_paths,
        output_path=Path(args.output),
        source_type=args.source_type,
        append=args.append,
    )


if __name__ == "__main__":
    main()
