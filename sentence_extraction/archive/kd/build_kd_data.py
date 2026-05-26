"""Phase 1: Claude Teacher 자동 라벨링 → KD 학습 데이터 생성.

backend/data 안 가정통신문 PDF에 대해:
1. pdfplumber로 bbox 행 추출 (SaT PoC와 동일 방식)
2. backend layout_normalizer와 동일한 프롬프트로 Claude Haiku 호출
3. sentence_list 정답 받음
4. 행 페어 (i, i+1)이 같은 sentence에 속하면 label=1 (merge), 아니면 0 (split)
5. JSONL로 저장 → 코랩에 업로드해서 Phase 2 학습 입력으로 사용

실행:
    $env:ANTHROPIC_API_KEY = "sk-ant-..."   # PowerShell
    python sentence_extraction/build_kd_data.py `
        --pdf-dir backend/data `
        --out sentence_extraction/data/kd_train.jsonl

의존성: pdfplumber (backend에 이미 있음), 표준 라이브러리만.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Windows PowerShell stdout(cp949)이 한글·일본어 punctuation을 못 다루는 문제 회피
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import pdfplumber

CLAUDE_MODEL = "claude-haiku-4-5"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_TIMEOUT_SECONDS = 120

# backend/app/services/layout_normalizer.py의 _SYSTEM_INSTRUCTION과 동기화.
# 원문 보존 절대 원칙이 들어가 있어야 매칭 알고리즘이 정확하게 작동.
SYSTEM_INSTRUCTION = """**최우선 원칙: 원문 텍스트에 등장하는 어구만 사용한다. 한 단어라도 원문에 없으면 출력하지 마라.**

당신은 paraphraser가 아니다. **복사기 + 띄어쓰기/기호 정상화기**.
한국 학교 가정통신문을 자체 PDF 파서가 만들 raw 텍스트 형태로 정제.

**규칙**:
1. 원문 보존 절대 원칙 — cleaned_text와 sentence_list[].text의 모든 어구는 원문에 그대로 등장.
   동의어/유의어/의역/요약/축약/재구성/부연 추가 금지. 어색해도 원문 그대로.
2. 허용 변환:
   (a) 띄어쓰기 정상화 — "학 년 도" → "학년도", 자간 공백만 합치기
   (b) 특수기호 → ASCII: ○ → O, ✕ → X, □ → [], ✓ → V, ☑ → [V] (■, ※, ▶는 보존)
   (c) 단독 기호 줄(■■■, 가로줄) 제거
3. 한 줄 = 한 sentence. 한 문장을 두 줄에 걸치지 말 것.
4. 헤더-값은 원문 형식 그대로 (콜론 강제 추가/제거 X).
5. 표 행은 한 줄 sentence — 분류·구분 정보 괄호로 보존.
6. 종결어미·날짜·시간·금액·URL·전화번호·고유명사·학교명·지명 원문 그대로.

**출력 JSON**: {"document_title": "...", "cleaned_text": "...", "sentence_list": [...]}

**sentence_list** 각 항목:
- sentence_id: "s001", "s002", ...
- text: 한 sentence (cleaned_text 안의 줄 단위)
- role_hint: target/content/application_period/event_datetime/application_url/contact/result_announcement/location/fee/supplies/submit/program_title/etc 중 정확히 하나
- source_order: 1부터 시작하는 정수
- is_action_candidate: 학부모 직접 행동 필요하면 true

**규칙**:
- sentence_list[].text 합치면 cleaned_text와 의미상 동일 (정보 누락 X)
- 인사말/서명/결어도 sentence_list 포함 (role_hint="etc")

**출력 직전 self-check**: 모든 어구가 원문에 있는지 단어 단위로 확인. 없는 어구는 제거하고 원문 어구로 교체.
"""

USER_PROMPT_TEXT = """다음 가정통신문 텍스트를 systemInstruction의 형식·규칙대로 정제해서 JSON 세 필드(document_title, cleaned_text, sentence_list)로 출력하세요.

[입력]
{text}"""


# --mode direct 용 — Claude에게 행 페어 직접 라벨링 시킴
DIRECT_LABEL_PROMPT = """다음은 가정통신문 PDF에서 pdfplumber bbox로 추출한 인접한 행 목록입니다.

각 인접 행 페어 (행 i, 행 i+1)에 대해 두 행이 **같은 의미 단위(한 문장)인지** 판단하세요.

**판단 기준**:
- 단어 중간에 줄바꿈으로 끊긴 경우 → 1 (merge)
- 한 문장이 여러 행에 걸쳐 이어지는 경우 → 1 (merge)
- 별도 문장/항목/번호 매김/제목으로 분리되는 경우 → 0 (split)
- 표 헤더와 셀, 시간표 행 반복, 시·도 분리 등은 → 0 (split)
- 빈 행, 마크업·기호만 있는 행은 → 0 (split)

**행 목록** (총 N행):
{rows_text}

**출력**: JSON 객체 한 개. labels 배열 길이는 N-1.
예시 (N=5): {{"labels": [0, 1, 0, 0]}}

설명·코드펜스 없이 JSON만 출력.
"""


def extract_rows(pdf_path: Path) -> list[str]:
    """SaT PoC와 동일 — bbox y좌표(±2pt) 기반 행 묶기."""
    rows: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True, x_tolerance=3, y_tolerance=3)
            words.sort(key=lambda w: (w["top"], w["x0"]))
            cur_y: float | None = None
            cur_row: list[dict] = []
            for w in words:
                if cur_y is None or abs(w["top"] - cur_y) > 2:
                    if cur_row:
                        rows.append(" ".join(t["text"] for t in cur_row))
                    cur_row = [w]
                    cur_y = w["top"]
                else:
                    cur_row.append(w)
            if cur_row:
                rows.append(" ".join(t["text"] for t in cur_row))
    return rows


def extract_rows_with_bbox(pdf_path: Path) -> list[dict[str, Any]]:
    """PointerDoc 학습용 — 행 텍스트 + bbox + page index 같이 반환.

    bbox = (x0, y0, x1, y1) in pdfplumber 좌표계 (origin top-left).
    """
    rows: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_w, page_h = float(page.width), float(page.height)
            words = page.extract_words(use_text_flow=True, x_tolerance=3, y_tolerance=3)
            words.sort(key=lambda w: (w["top"], w["x0"]))
            cur_y: float | None = None
            cur_row: list[dict] = []

            def _flush(buf: list[dict]) -> None:
                if not buf:
                    return
                text = " ".join(t["text"] for t in buf)
                x0 = min(t["x0"] for t in buf)
                x1 = max(t["x1"] for t in buf)
                y0 = min(t["top"] for t in buf)
                y1 = max(t["bottom"] for t in buf)
                rows.append({
                    "text": text,
                    "page": page_idx,
                    "page_width": page_w,
                    "page_height": page_h,
                    "bbox": [float(x0), float(y0), float(x1), float(y1)],
                })

            for w in words:
                if cur_y is None or abs(w["top"] - cur_y) > 2:
                    _flush(cur_row)
                    cur_row = [w]
                    cur_y = w["top"]
                else:
                    cur_row.append(w)
            _flush(cur_row)
    return rows


def extract_full_text(pdf_path: Path) -> str:
    """Claude 입력용 — pdfplumber 텍스트(backend와 동일)."""
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text(use_text_flow=True, x_tolerance=3, y_tolerance=3) or ""
            parts.append(txt)
    return "\n".join(parts)


def _claude_request(payload_dict: dict[str, Any], api_key: str) -> str:
    """공통 HTTP 호출 + retry. JSON 응답 body 문자열 반환."""
    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        CLAUDE_API_URL,
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    last_err: Exception | None = None
    for delay in (0, 2, 5):
        if delay > 0:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=CLAUDE_TIMEOUT_SECONDS) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last_err = e
            err_body = e.read().decode("utf-8")[:200] if hasattr(e, "read") else ""
            print(f"  HTTP {e.code}: {err_body} - retry in {delay}s", file=sys.stderr)
        except Exception as e:
            last_err = e
            print(f"  Error: {e} - retry in {delay}s", file=sys.stderr)
    raise RuntimeError(f"Claude API failed: {last_err}")


def call_claude(text: str, api_key: str) -> dict[str, Any]:
    """Claude Haiku 호출 (sentence_list 정답 모드)."""
    body = _claude_request({
        "model": CLAUDE_MODEL,
        "max_tokens": 32768,
        "system": SYSTEM_INSTRUCTION + "\n\n출력은 JSON만 (다른 설명·머리말·코드펜스 X).",
        "messages": [{"role": "user", "content": [{"type": "text", "text": USER_PROMPT_TEXT.format(text=text)}]}],
        "temperature": 0.0,
    }, api_key)
    resp_json = json.loads(body)
    text_content = resp_json["content"][0]["text"].strip()
    text_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_content)
    return json.loads(text_content)


def call_claude_for_pair_labels(rows: list[str], api_key: str) -> list[int]:
    """Claude에게 행 페어를 직접 보여주고 N-1개 0/1 라벨 받음 (--mode direct).

    매칭 알고리즘 우회 — Claude가 의미·물리 배치 둘 다 보고 직접 판단.
    """
    rows_text = "\n".join(f"[{i:02d}] {r}" for i, r in enumerate(rows))
    body = _claude_request({
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": [{"type": "text", "text": DIRECT_LABEL_PROMPT.format(rows_text=rows_text)}]}],
        "temperature": 0.0,
    }, api_key)
    resp_json = json.loads(body)
    text_content = resp_json["content"][0]["text"].strip()
    text_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_content)
    data = json.loads(text_content)
    labels = data.get("labels", [])

    # 길이 맞추기 (Claude가 가끔 틀린 길이 출력)
    expected = len(rows) - 1
    if len(labels) < expected:
        labels = list(labels) + [0] * (expected - len(labels))
    elif len(labels) > expected:
        labels = list(labels)[:expected]
    return [int(x) for x in labels]


_MARKUP_CHARS = re.compile(r"[※☎▸▪❑■▶◇◆□●○•∙⚈①②③④⑤⑥⑦⑧⑨⑩❑✀♠♣♥♦◀▲▼◉]")
_SMART_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "·": "", "・": ""})
_ZERO_WIDTH = re.compile(r"[​   ﻿]")


def normalize(s: str) -> str:
    """매칭용 정규화 — Claude 변형 패턴(마크업·smart quote·부연) 흡수."""
    s = _MARKUP_CHARS.sub("", s)
    s = s.translate(_SMART_QUOTES)
    s = _ZERO_WIDTH.sub("", s)
    return "".join(s.split())


def normalize_sentence(s: str) -> str:
    """sentence 전용 정규화 — 끝 부연 괄호도 제거 (Claude가 (프로그램명) 같은 라벨 자주 추가)."""
    # 끝의 ` (...)` 한글 부연 제거 — 원문에 없는 메타정보 라벨
    s = re.sub(r"\s*\(\s*[가-힣\s/]+\s*\)\s*$", "", s)
    return normalize(s)


def label_pairs(rows: list[str], sentences: list[str]) -> tuple[list[int], int, int]:
    """행 페어 (i, i+1)이 같은 sentence에 속하면 1 (merge), 아니면 0 (split).

    Returns (labels, sentences_matched, sentences_total).
    """
    rows_norm = [normalize(r) for r in rows]
    # sentence는 끝 부연 괄호도 제거한 버전과 일반 버전 둘 다 시도
    sents_norm_strict = [normalize(s) for s in sentences]
    sents_norm_loose = [normalize_sentence(s) for s in sentences]

    full_text = "".join(rows_norm)

    # 각 행의 char offset (정규화된 full_text 안에서)
    row_offsets: list[tuple[int, int]] = []
    cursor = 0
    for r in rows_norm:
        row_offsets.append((cursor, cursor + len(r)))
        cursor += len(r)

    # 각 sentence의 char offset (strict → loose 순으로 시도, fail 시 cursor 무시 재시도)
    sent_offsets: list[tuple[int, int] | None] = []
    cursor = 0
    matched = 0
    for strict, loose in zip(sents_norm_strict, sents_norm_loose):
        idx = -1
        target_len = 0
        for candidate in (strict, loose):
            if not candidate:
                continue
            i = full_text.find(candidate, cursor)
            if i < 0:
                i = full_text.find(candidate)
            if i >= 0:
                idx = i
                target_len = len(candidate)
                break
        if idx >= 0:
            sent_offsets.append((idx, idx + target_len))
            cursor = max(cursor, idx + target_len)
            matched += 1
        else:
            sent_offsets.append(None)

    def find_sentence_id_at(pos: int) -> int | None:
        for si, span in enumerate(sent_offsets):
            if span and span[0] <= pos < span[1]:
                return si
        return None

    labels: list[int] = []
    for i in range(len(rows) - 1):
        # row 끝 직전 + 다음 row 시작이 같은 sentence에 속하면 merge
        # (한 row가 여러 sentence에 걸쳐있을 수 있어서 양 끝을 봄)
        cur_start, cur_end = row_offsets[i]
        nxt_start, _ = row_offsets[i + 1]
        cur_last_pos = cur_end - 1 if cur_end > cur_start else cur_start
        cur_s = find_sentence_id_at(cur_last_pos)
        nxt_s = find_sentence_id_at(nxt_start)
        labels.append(1 if (cur_s is not None and cur_s == nxt_s) else 0)
    return labels, matched, len(sentences)


def sentence_to_row_ids(
    rows_text: list[str], sentences: list[str]
) -> tuple[list[list[int]], int, int]:
    """각 sentence가 어느 행들로 구성되는지 매핑 (PointerDoc 라벨).

    한 row가 두 sentence에 걸칠 경우 — char overlap이 가장 큰 sentence에 할당
    (exclusive assignment, BIO와 동일한 효과).

    Returns (sent_to_rows, matched_sentences, total_sentences).
    """
    rows_norm = [normalize(r) for r in rows_text]
    sents_norm_strict = [normalize(s) for s in sentences]
    sents_norm_loose = [normalize_sentence(s) for s in sentences]

    full_text = "".join(rows_norm)

    # 각 행의 char range
    row_offsets: list[tuple[int, int]] = []
    cursor = 0
    for r in rows_norm:
        row_offsets.append((cursor, cursor + len(r)))
        cursor += len(r)

    # 각 sentence의 char range (label_pairs와 동일 알고리즘)
    sent_offsets: list[tuple[int, int] | None] = []
    cursor = 0
    matched = 0
    for strict, loose in zip(sents_norm_strict, sents_norm_loose):
        idx = -1
        target_len = 0
        for candidate in (strict, loose):
            if not candidate:
                continue
            i = full_text.find(candidate, cursor)
            if i < 0:
                i = full_text.find(candidate)
            if i >= 0:
                idx = i
                target_len = len(candidate)
                break
        if idx >= 0:
            sent_offsets.append((idx, idx + target_len))
            cursor = max(cursor, idx + target_len)
            matched += 1
        else:
            sent_offsets.append(None)

    # 각 row를 가장 많이 겹치는 sentence에 exclusively 할당
    sent_to_rows: list[list[int]] = [[] for _ in sentences]
    for ri, (r_start, r_end) in enumerate(row_offsets):
        if r_end <= r_start:
            continue
        best_si = -1
        best_overlap = 0
        for si, span in enumerate(sent_offsets):
            if span is None:
                continue
            s_start, s_end = span
            overlap = max(0, min(r_end, s_end) - max(r_start, s_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_si = si
        if best_si >= 0:
            sent_to_rows[best_si].append(ri)

    return sent_to_rows, matched, len(sentences)


def process_pdf_pointerdoc(pdf_path: Path, api_key: str) -> dict[str, Any] | None:
    """PointerDoc 학습용 — 1 PDF = 1 record (rows + sentences with row_ids)."""
    rows_data = extract_rows_with_bbox(pdf_path)
    if not rows_data:
        print(f"  {pdf_path.name}: no rows, skip")
        return None
    if len(rows_data) > MAX_ROWS_PER_PDF:
        print(f"  {pdf_path.name}: too many rows ({len(rows_data)} > {MAX_ROWS_PER_PDF}), skip")
        return None

    full_text = extract_full_text(pdf_path)
    if not full_text.strip():
        print(f"  {pdf_path.name}: no text, skip")
        return None

    t0 = time.time()
    claude_result = call_claude(full_text, api_key)
    elapsed = time.time() - t0

    raw_sents = claude_result.get("sentence_list", [])
    sent_texts = [s.get("text", "") for s in raw_sents]
    rows_text = [r["text"] for r in rows_data]
    sent_to_rows, matched, total = sentence_to_row_ids(rows_text, sent_texts)

    sentences_out = []
    for i, s in enumerate(raw_sents):
        sentences_out.append({
            "text": s.get("text", ""),
            "role_hint": s.get("role_hint", "etc"),
            "source_order": s.get("source_order", i + 1),
            "is_action_candidate": s.get("is_action_candidate", False),
            "row_ids": sent_to_rows[i],
        })

    print(
        f"  {pdf_path.name}: rows={len(rows_data)} "
        f"sentences={total} (matched={matched}/{total}, {100*matched/max(total,1):.0f}%) "
        f"claude={elapsed:.1f}s [pointerdoc]"
    )

    return {
        "pdf": pdf_path.name,
        "document_title": claude_result.get("document_title", ""),
        "cleaned_text": claude_result.get("cleaned_text", ""),
        "rows": rows_data,
        "sentences": sentences_out,
        "n_rows": len(rows_data),
        "n_sentences": total,
        "n_matched": matched,
        "claude_time_sec": elapsed,
    }


def process_pdf(pdf_path: Path, api_key: str, mode: str = "sentence") -> list[dict[str, Any]]:
    rows = extract_rows(pdf_path)
    if not rows:
        print(f"  {pdf_path.name}: no rows, skip")
        return []
    if len(rows) > MAX_ROWS_PER_PDF:
        print(f"  {pdf_path.name}: too many rows ({len(rows)} > {MAX_ROWS_PER_PDF}), not a 통신문 — skip")
        return []

    if mode == "direct":
        # Claude에게 행 페어 직접 라벨링 (매칭 알고리즘 우회)
        t0 = time.time()
        labels = call_claude_for_pair_labels(rows, api_key)
        elapsed = time.time() - t0
        n_merge = sum(labels)
        n_split = len(labels) - n_merge
        print(
            f"  {pdf_path.name}: rows={len(rows)} "
            f"pairs={len(labels)} (merge={n_merge}, split={n_split}) "
            f"claude={elapsed:.1f}s [direct]"
        )
    else:
        # sentence_list 매칭 모드 (기존 동작)
        full_text = extract_full_text(pdf_path)
        if not full_text.strip():
            print(f"  {pdf_path.name}: no text, skip")
            return []
        t0 = time.time()
        claude_result = call_claude(full_text, api_key)
        elapsed = time.time() - t0
        sentences = [s.get("text", "") for s in claude_result.get("sentence_list", [])]
        labels, matched, total = label_pairs(rows, sentences)
        n_merge = sum(labels)
        n_split = len(labels) - n_merge
        print(
            f"  {pdf_path.name}: rows={len(rows)} "
            f"sentences={total} (matched={matched}/{total}, {100*matched/max(total,1):.0f}%) "
            f"pairs={len(labels)} (merge={n_merge}, split={n_split}) "
            f"claude={elapsed:.1f}s [sentence]"
        )

    pairs = []
    for i, label in enumerate(labels):
        pairs.append({
            "cur_row": rows[i],
            "next_row": rows[i + 1],
            "label": label,
            "source": pdf_path.name,
        })
    return pairs


# 기본 제외 키워드 (논문·연구자료 — 가정통신문 아님)
DEFAULT_EXCLUDE = ["용역", "결혼이민자", "어휘 교육", "양상 비교"]
# 행 수 임계값 — 이보다 큰 PDF는 가정통신문이 아닌 큰 문서로 간주
# --max-rows 인자로 override 가능
MAX_ROWS_PER_PDF = 200


def main() -> None:
    global MAX_ROWS_PER_PDF
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY", ""))
    parser.add_argument("--limit", type=int, default=None, help="PDF 개수 제한 (테스트용)")
    parser.add_argument("--exclude", nargs="+", default=DEFAULT_EXCLUDE, help="파일명 제외 키워드")
    parser.add_argument("--mode", choices=["sentence", "direct", "pointerdoc"], default="direct",
                        help="sentence: sentence_list 매칭 / direct: Claude에게 페어 직접 라벨링 / "
                             "pointerdoc: PointerDoc 라벨링 (rows+bbox + sentence→row_ids 매핑)")
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 worker 수 (pointerdoc mode만 지원, 기본 1=sequential)")
    parser.add_argument("--resume", action="store_true",
                        help="기존 out 파일 이어서 — 이미 처리된 PDF 스킵 (pointerdoc mode만)")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS_PER_PDF,
                        help=f"행 수 임계값 — 이보다 큰 PDF는 스킵 (default {MAX_ROWS_PER_PDF})")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: ANTHROPIC_API_KEY 환경변수 또는 --api-key 필요", file=sys.stderr)
        sys.exit(1)

    # max-rows override (process_pdf, process_pdf_pointerdoc 모두 global을 사용)
    if args.max_rows != MAX_ROWS_PER_PDF:
        print(f"max-rows override: {MAX_ROWS_PER_PDF} → {args.max_rows}")
        MAX_ROWS_PER_PDF = args.max_rows

    pdf_files = sorted(args.pdf_dir.glob("*.pdf"))
    pdf_files = [p for p in pdf_files if not any(k in p.name for k in args.exclude)]
    if args.limit:
        pdf_files = pdf_files[: args.limit]

    print(f"Found {len(pdf_files)} PDFs (excluded keywords: {args.exclude})")
    if len(pdf_files) <= 20:
        for p in pdf_files:
            print(f"  - {p.name}")
    else:
        print(f"  (first 3) {pdf_files[0].name}")
        print(f"  (first 3) {pdf_files[1].name}")
        print(f"  (first 3) {pdf_files[2].name}")
        print(f"  ... and {len(pdf_files)-3} more")
    print()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []

    if args.mode == "pointerdoc":
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # resume — 이미 처리된 PDF는 다시 호출하지 않음 (Claude API 비용 절약)
        already_done: set[str] = set()
        if args.resume and args.out.exists():
            with open(args.out, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        already_done.add(rec["pdf"])
                    except Exception:
                        pass
            print(f"Resume: {len(already_done)} PDFs already processed, skipping")
            pdf_files = [p for p in pdf_files if p.name not in already_done]
            print(f"Remaining: {len(pdf_files)} PDFs to process")

        # streaming write (병렬 결과를 도착 순서대로 즉시 저장 → 중단 시 손실 최소)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_lock = threading.Lock()
        write_mode = "a" if (args.resume and args.out.exists()) else "w"
        out_fp = open(args.out, write_mode, encoding="utf-8", buffering=1)

        counter = {"done": 0, "skip": 0, "fail": 0}
        counter_lock = threading.Lock()
        total = len(pdf_files)

        def _work(pdf: Path) -> None:
            try:
                rec = process_pdf_pointerdoc(pdf, args.api_key)
                with counter_lock:
                    if rec is None:
                        counter["skip"] += 1
                    else:
                        counter["done"] += 1
                if rec is not None:
                    with write_lock:
                        out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as e:
                with counter_lock:
                    counter["fail"] += 1
                failed.append(pdf.name)
                print(f"  FAILED {pdf.name}: {e}", file=sys.stderr)

        if args.workers <= 1:
            for i, pdf in enumerate(pdf_files, 1):
                _work(pdf)
                if i % 25 == 0:
                    print(f"  [progress] {i}/{total}  done={counter['done']} skip={counter['skip']} fail={counter['fail']}", flush=True)
        else:
            print(f"Parallel: {args.workers} workers")
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures = [ex.submit(_work, pdf) for pdf in pdf_files]
                for i, _ in enumerate(as_completed(futures), 1):
                    if i % 25 == 0:
                        print(f"  [progress] {i}/{total}  done={counter['done']} skip={counter['skip']} fail={counter['fail']}", flush=True)

        out_fp.close()

        # 최종 통계 (전체 파일 다시 읽어서 집계)
        records: list[dict[str, Any]] = []
        with open(args.out, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass

        if not records:
            print("\nNo records generated. Exiting.")
            sys.exit(1)

        total_rows = sum(r["n_rows"] for r in records)
        total_sents = sum(r["n_sentences"] for r in records)
        total_matched = sum(r["n_matched"] for r in records)
        print(f"\nDone. {len(records)} PDFs total in {args.out}")
        print(f"  this run: done={counter['done']} skip={counter['skip']} fail={counter['fail']}")
        print(f"  total rows     : {total_rows}")
        print(f"  total sentences: {total_sents}")
        print(f"  matched        : {total_matched}/{total_sents} ({100*total_matched/max(total_sents,1):.1f}%)")
        if failed:
            print(f"\nFailed: {len(failed)} PDFs")
            for f_name in failed:
                print(f"  - {f_name}")
        return

    # 기존 sentence / direct mode (페어 라벨)
    all_pairs: list[dict[str, Any]] = []
    for pdf in pdf_files:
        try:
            pairs = process_pdf(pdf, args.api_key, mode=args.mode)
            all_pairs.extend(pairs)
        except Exception as e:
            print(f"  FAILED {pdf.name}: {e}", file=sys.stderr)
            failed.append(pdf.name)

    with open(args.out, "w", encoding="utf-8") as f:
        for p in all_pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    if not all_pairs:
        print("\nNo pairs generated. Exiting.")
        sys.exit(1)

    n_merge = sum(p["label"] for p in all_pairs)
    n_split = len(all_pairs) - n_merge
    by_source: dict[str, int] = {}
    for p in all_pairs:
        by_source[p["source"]] = by_source.get(p["source"], 0) + 1
    print(f"\nDone. {len(all_pairs)} pairs saved to {args.out}")
    print(f"  merge: {n_merge:>5} ({100*n_merge/len(all_pairs):.1f}%)")
    print(f"  split: {n_split:>5} ({100*n_split/len(all_pairs):.1f}%)")
    print(f"  per-source:")
    for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {count:>4}  {src}")
    if failed:
        print(f"\nFailed: {len(failed)} PDFs")
        for f_name in failed:
            print(f"  - {f_name}")


if __name__ == "__main__":
    main()
