"""v5 pilot — 5장 PDF를 새 prompt로 Claude에 재라벨링.

목적: Claude의 "이상적 sentence_list"를 받아 우리 코드 (룰)을 정교화하는 reference 만들기.
전체 데이터 재라벨링 X — 5장만으로 패턴 분석.

사용:
    docker exec -e ANTHROPIC_API_KEY=$KEY project-backend-1 \\
        python /app/sentence_extraction/relabel_v5_pilot.py
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import fitz

PROMPT = """당신은 한국 가정통신문 분석 전문가입니다. PDF 텍스트를 학부모가 읽기 자연스러운 sentence_list로 분해하세요. PDF 원본 단어만 사용 (변형 X).

# 규칙

1. 자간 큰 글자 (디자인용 띄어쓰기)는 한 단어로 합치기
   - "가 정 통 신 문" → "가정통신문"
   - "안  전  업  무" → "안전업무"

2. bullet/marker (▷, ※, ①②③)는 단독 sentence 금지 — 다음 본문과 묶기
   - "▷ 자녀가 단말기를 책가방에 휴대하고..."
   - "※ 사용 중 전학 시 ..."

3. 한 문장이 줄 끝 / cell 경계로 잘려있으면 합치기
   - "사용 중 전학 시 → 자녀정보 → ... (서비스 미제공 학교일 경우 ...)"

4. 단계 번호 (1./2./3.)는 본문과 묶기
   - "1. 아이알리미 App 실행: 구글 플레이 스토어 또는 ..."

5. 표는 entity 단위로 블록 정렬, 각 cell마다 별도 sentence (entity prefix 안 붙임)

   col-major 표 (entity가 column header에) — entity별로 묶고 그 attr들 연속 출력:
   예 어린이날:
   - "오늘은 내가 과학왕!"
   - "내용: 미션 도장깨기 (전시물 체험, 포토인증, 과학체험활동)"
   - "운영시간: 상시"
   - "참여방법: 현장 참여"
   - "사이언스 매직쇼"
   - "내용: 신기한 마술 속 숨겨진 과학원리"
   - "운영시간: 14:00~15:00"
   - "참여방법: 사전 신청"
   ...

   row-major 표 (entity가 row header에) — 그대로 row별 cell마다:
   - "가만히 들어주었어"
   - "날짜: 1.2(금) 09:30~11:30"
   - "대상: 1-2학년 신청자"
   ...

   주의: PDF 원본 단어만 사용 (변형 0). entity prefix ("사이언스 매직쇼 - ") 추가 X.
   한 cell 안 bullet (▪/▸/•)이 있으면 별도 sentence로 split.

6. 의미 없는 단편 (혼자 떨어진 한 글자, 마커만)은 sentence에서 제외

# 출력 형식

엄격히 JSON만 출력:
{"sentences": ["문장 1", "문장 2", ...]}

# 입력

PDF 추출 텍스트 (페이지 구분 포함):
"""


PDFS = [
    "안심알리미 서비스 이용 안내문.pdf",
    "2026 북부과학교육관 어린이날 행사 안내 가정통신문.pdf",
    "2026학년도+1학기+4학년+평가+예고안.pdf",
    "2023년 1학기 생명존중(자살예방) 학부모 대상 연수.pdf",
    "044_마음건강의 도움이 필요한 신호.pdf",
    # 추가 5장 (edge case 다양화)
    "2025. 겨울방학 도서관 이용 및 독서캠프 신청 안내.pdf",
    "2026 2,3,5,6학년 구강검진 실시안내.pdf",
    "(부평초)+인공지능+맞춤형+교수학습+플랫폼(AIEP)+개인정보동의서.pdf",
    "2025학년도 4기(12, 1, 2월) 학습형늘봄(유상, 무상) 프로그램 안내_탑재용.pdf",
    "인플루엔자예방접종접종안내(2019).pdf",
]


def extract_pdf_text(pdf_path: Path) -> str:
    """PDF → 페이지별 text 추출 (pymupdf)."""
    parts: list[str] = []
    with fitz.open(pdf_path) as doc:
        for pi, page in enumerate(doc):
            parts.append(f"\n--- Page {pi+1} ---\n")
            parts.append(page.get_text())
    return "".join(parts)


def call_claude(pdf_text: str, pdf_name: str) -> dict:
    """Claude API 호출 — 새 prompt + PDF text (urllib.request 직접 사용)."""
    import urllib.request
    import urllib.error

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env not set")

    payload = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 16384,
        "messages": [{"role": "user", "content": PROMPT + "\n\n" + pdf_text}],
        "temperature": 0.0,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")[:300]
        raise RuntimeError(f"HTTP {e.code}: {err}") from e

    text = body["content"][0]["text"]

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [warning] JSON parse failed for {pdf_name}: {e}", file=sys.stderr)
        print(f"  Raw response (first 500 chars): {text[:500]}", file=sys.stderr)
        return {"sentences": [], "raw_response": text}


def main() -> None:
    pdf_dirs = [
        Path("/app/data"),
        Path("/app/sentence_extraction/data/heldout_20"),
    ]

    out_dir = Path("/app/sentence_extraction/data/v5_pilot")
    out_dir.mkdir(parents=True, exist_ok=True)

    for pdf_name in PDFS:
        # PDF 찾기 (여러 디렉토리 시도)
        pdf_path = None
        for d in pdf_dirs:
            cand = d / pdf_name
            if cand.exists():
                pdf_path = cand
                break

        if pdf_path is None:
            print(f"  [skip] {pdf_name} not found in {pdf_dirs}", file=sys.stderr)
            continue

        out_path = out_dir / (pdf_name.replace(".pdf", "") + ".json")
        if out_path.exists():
            print(f"  [skip] {pdf_name} already done", file=sys.stderr)
            continue

        print(f"Processing: {pdf_name}", file=sys.stderr)
        pdf_text = extract_pdf_text(pdf_path)
        print(f"  PDF text length: {len(pdf_text)} chars", file=sys.stderr)

        result = call_claude(pdf_text, pdf_name)
        n_sents = len(result.get("sentences", []))
        print(f"  → {n_sents} sentences from Claude", file=sys.stderr)

        out_path = out_dir / (pdf_name.replace(".pdf", "") + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"pdf": pdf_name, "sentences": result.get("sentences", []),
                       "raw_response": result.get("raw_response", "")}, f, ensure_ascii=False, indent=2)
        print(f"  Saved: {out_path}", file=sys.stderr)

    print(f"\nDone. Outputs in {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
