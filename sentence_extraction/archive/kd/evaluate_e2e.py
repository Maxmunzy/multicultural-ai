"""Phase 3: End-to-end 평가 — Claude vs KoBERT 비교.

흐름:
1. PoC PDF 각각에 대해:
   A. Claude → sentence_list → KoELECTRA → todo 목록 (정답)
   B. pdfplumber → KoBERT → sentence_list → KoELECTRA → todo 목록 (자체화)
2. A vs B의 todo recall·precision 측정
3. 누락된 todo 정성 분석

실행 환경: NCP backend Docker 컨테이너 (모든 의존성 + 모델 있음)

사용법 (NCP 서버에서):
    docker exec schoolbridge python /app/evaluate_e2e.py \\
        --kobert-dir /app/kobert_kd_pair_classifier \\
        --pdf-dir /app/backend/data \\
        --out /app/evaluation_result.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pdfplumber
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# backend 모듈 활용 (KoELECTRA·layout_normalizer 호출)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def extract_rows(pdf_path: Path) -> list[dict[str, Any]]:
    """SaT PoC·KD 라벨링과 동일 — bbox y±2pt 행 묶기. bbox도 같이 반환."""
    rows: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words(use_text_flow=True, x_tolerance=3, y_tolerance=3)
            words.sort(key=lambda w: (w["top"], w["x0"]))
            cur_y: float | None = None
            cur_row: list[dict] = []
            for w in words:
                if cur_y is None or abs(w["top"] - cur_y) > 2:
                    if cur_row:
                        rows.append(_make_row(page_idx, cur_row))
                    cur_row = [w]
                    cur_y = w["top"]
                else:
                    cur_row.append(w)
            if cur_row:
                rows.append(_make_row(page_idx, cur_row))
    return rows


def _make_row(page_idx: int, words: list[dict]) -> dict[str, Any]:
    text = " ".join(w["text"] for w in words)
    x0 = min(w["x0"] for w in words)
    x1 = max(w["x1"] for w in words)
    y0 = min(w["top"] for w in words)
    y1 = max(w["bottom"] for w in words)
    return {"text": text, "page": page_idx, "bbox": (x0, y0, x1, y1)}


class KoBERTPairClassifier:
    """KD로 학습된 KoBERT 페어 분류기."""

    def __init__(self, model_dir: str):
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = self.model.to(self.device)

    def predict_pair(self, cur: str, nxt: str) -> int:
        enc = self.tokenizer(
            cur, nxt,
            truncation=True, padding="max_length", max_length=128,
            return_tensors="pt",
        ).to(self.device)
        with torch.no_grad():
            logits = self.model(**enc).logits
        return int(torch.argmax(logits, dim=-1).item())

    def predict_pairs(self, rows: list[str]) -> list[int]:
        labels = []
        for i in range(len(rows) - 1):
            labels.append(self.predict_pair(rows[i], rows[i + 1]))
        return labels


def group_into_sentences(rows: list[dict[str, Any]], merge_labels: list[int]) -> list[str]:
    """KoBERT 라벨로 연속 merge 행을 sentence로 묶기 (transitive)."""
    if not rows:
        return []
    sentences = []
    current = [rows[0]["text"]]
    for i, label in enumerate(merge_labels):
        if label == 1:
            current.append(rows[i + 1]["text"])
        else:
            sentences.append(" ".join(current))
            current = [rows[i + 1]["text"]]
    if current:
        sentences.append(" ".join(current))
    return sentences


def get_claude_result(pdf_path: Path) -> tuple[list[str], str]:
    """backend extract_sentences(PDF inline) → (sentence_list, cleaned_text)."""
    from app.services.layout_normalizer import extract_sentences
    with open(pdf_path, "rb") as f:
        raw = f.read()
    structured, status, _ = extract_sentences(text="", inline_data=(raw, "application/pdf"))
    sentences = [s.get("text", "") for s in structured.get("sentence_list", [])]
    cleaned = structured.get("cleaned_text", "")
    return sentences, cleaned


def extract_todos_from_cleaned(cleaned_text: str) -> list[str]:
    """backend extract_todos(cleaned_text) → KoELECTRA로 todo만 추출."""
    from app.services.extractor import extract_todos
    todos = extract_todos(cleaned_text)
    return [t.text for t in todos]


def evaluate_pdf(pdf_path: Path, kobert: KoBERTPairClassifier) -> dict[str, Any]:
    """한 PDF에 대해 두 흐름 비교."""
    # --- 흐름 A: Claude (정답 기준) ---
    t0 = time.time()
    claude_sentences, claude_cleaned = get_claude_result(pdf_path)
    claude_todos = extract_todos_from_cleaned(claude_cleaned)
    t_claude = time.time() - t0

    # --- 흐름 B: KoBERT (자체화) ---
    t0 = time.time()
    rows = extract_rows(pdf_path)
    row_texts = [r["text"] for r in rows]
    merge_labels = kobert.predict_pairs(row_texts)
    kobert_sentences = group_into_sentences(rows, merge_labels)
    # sentence_list를 paragraph 흐름(cleaned_text 형태)으로 join
    kobert_cleaned = "\n".join(kobert_sentences)
    kobert_todos = extract_todos_from_cleaned(kobert_cleaned)
    t_kobert = time.time() - t0

    # --- 비교 (normalize 후 set 매칭) ---
    def norm(s: str) -> str:
        return "".join(s.split())

    claude_norm = {norm(t): t for t in claude_todos}
    kobert_norm = {norm(t): t for t in kobert_todos}

    # 추가: 한쪽이 다른 쪽의 substring으로 포함되는 케이스 (단어 끊김 등)도 매칭 시도
    matched = set()
    for ck, cv in claude_norm.items():
        for kk in kobert_norm:
            if ck == kk or ck in kk or kk in ck:
                matched.add(ck)
                break

    recall = len(matched) / max(len(claude_todos), 1)
    precision = len(matched) / max(len(kobert_todos), 1)

    return {
        "pdf": pdf_path.name,
        "claude_sentences": len(claude_sentences),
        "kobert_sentences": len(kobert_sentences),
        "claude_todos": claude_todos,
        "kobert_todos": kobert_todos,
        "matched_count": len(matched),
        "recall": recall,
        "precision": precision,
        "time_claude": t_claude,
        "time_kobert": t_kobert,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kobert-dir", required=True, type=Path, help="KoBERT 학습 모델 디렉토리")
    parser.add_argument("--pdf-dir", required=True, type=Path, help="평가용 PDF 폴더")
    parser.add_argument("--out", required=True, type=Path, help="결과 JSON 출력 경로")
    parser.add_argument("--api-key", default="", help="ANTHROPIC_API_KEY (없으면 환경변수 사용)")
    args = parser.parse_args()

    import os
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 필요", file=sys.stderr)
        sys.exit(1)

    kobert = KoBERTPairClassifier(str(args.kobert_dir))
    print(f"KoBERT loaded on {kobert.device}")

    # PoC 6장 가정통신문만 (논문·매뉴얼 제외)
    EXCLUDE = ["용역", "결혼이민자", "어휘 교육", "양상 비교"]
    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    pdfs = [p for p in pdfs if not any(k in p.name for k in EXCLUDE)]
    print(f"평가 대상: {len(pdfs)} PDFs")

    results = []
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        try:
            r = evaluate_pdf(pdf, kobert)
            results.append(r)
            print(f"  Claude todos: {len(r['claude_todos'])}, KoBERT todos: {len(r['kobert_todos'])}")
            print(f"  matched: {r['matched_count']}, recall: {r['recall']:.3f}, precision: {r['precision']:.3f}")
            print(f"  time: claude {r['time_claude']:.1f}s, kobert {r['time_kobert']:.1f}s")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)

    # 전체 평균
    if results:
        avg_recall = sum(r["recall"] for r in results) / len(results)
        avg_prec = sum(r["precision"] for r in results) / len(results)
        avg_t_claude = sum(r["time_claude"] for r in results) / len(results)
        avg_t_kobert = sum(r["time_kobert"] for r in results) / len(results)
        print("\n" + "=" * 80)
        print("전체 평균")
        print(f"  recall   : {avg_recall:.3f}")
        print(f"  precision: {avg_prec:.3f}")
        print(f"  claude time: {avg_t_claude:.1f}s")
        print(f"  kobert time: {avg_t_kobert:.1f}s")
        print(f"  속도 비율: {avg_t_claude/max(avg_t_kobert, 0.01):.1f}x faster")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
