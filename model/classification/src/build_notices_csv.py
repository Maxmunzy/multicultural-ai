"""notices_labeled_v2.csv / .jsonl, extracted_results.json 세 파일을 통합해
모델 예측으로 category·importance를 채운 6열 CSV를 생성한다.

출력 컬럼: id, source_type, original_text, category, keywords, importance

우선순위:
  1. notices_labeled_v2.csv  — 102행, keywords 있음, 최우선
  2. notices_labeled_v2.jsonl (is_todo=True) — CSV에 없는 문장만 추가
  3. extracted_results.json (text_ko) — 위 두 소스에 없는 단문만 추가

사용법
------
기본 실행:
    python -m src.build_notices_csv

출력 경로 지정:
    python -m src.build_notices_csv --output outputs/predictions/notices_classified.csv

모델 선택:
    python -m src.build_notices_csv --model sbert

기준일 지정:
    python -m src.build_notices_csv --today 2026-04-27
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, PRED_DIR
from .data_loader import clean_text, normalize_label
from .importance_scorer import ImportanceScorer
from .predict import _load_classifier

OUTPUT_COLS = ["id", "source_type", "original_text", "category", "keywords", "importance"]


# --------------------------------------------------------------------------
# 소스별 로더 (원본 라벨 없이 텍스트·메타만 수집)
# --------------------------------------------------------------------------

def _load_csv_rows(path: Path) -> pd.DataFrame:
    """notices_labeled_v2.csv → id, source_type, original_text, keywords 유지."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["original_text"] = df["original_text"].map(clean_text)
    keep = ["id", "source_type", "original_text", "keywords"]
    for col in keep:
        if col not in df.columns:
            df[col] = ""
    return df[keep].copy()


def _load_jsonl_rows(path: Path) -> pd.DataFrame:
    """notices_labeled_v2.jsonl → is_todo=True 문장만 추출."""
    rows = []
    with path.open(encoding="utf-8") as f:
        counter = 0
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not obj.get("is_todo"):
                continue
            rows.append({
                "id": f"jsonl_{counter}",
                "source_type": "초등학교",
                "original_text": clean_text(obj.get("sentence", "")),
                "keywords": "",
            })
            counter += 1
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id", "source_type", "original_text", "keywords"])


def _load_json_rows(path: Path) -> pd.DataFrame:
    """extracted_results.json → todos[].text_ko 단문 추출."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    counter = 0
    for entry in data:
        notice_id = entry.get("notice_id", "")
        for todo in entry.get("todos", []):
            text = clean_text(todo.get("text_ko", ""))
            if not text:
                continue
            rows.append({
                "id": f"json_{notice_id}_{counter}",
                "source_type": "초등학교",
                "original_text": text,
                "keywords": "",
            })
            counter += 1
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id", "source_type", "original_text", "keywords"])


# --------------------------------------------------------------------------
# 통합 + 분류 실행
# --------------------------------------------------------------------------

def build_notices_csv(
    output_path: Path,
    *,
    csv_path: Path | None = None,
    jsonl_path: Path | None = None,
    json_path: Path | None = None,
    model: str = "simple",
    today: date | None = None,
) -> pd.DataFrame:
    """3개 소스를 합쳐 분류 결과 6열 CSV로 저장한다."""
    csv_path   = csv_path   or DATA_DIR / "notices_labeled_v2.csv"
    jsonl_path = jsonl_path or DATA_DIR / "notices_labeled_v2.jsonl"
    json_path  = json_path  or DATA_DIR / "extracted_results.json"

    # 1) 각 소스 로드
    df_csv   = _load_csv_rows(csv_path)
    df_jsonl = _load_jsonl_rows(jsonl_path)
    df_json  = _load_json_rows(json_path)

    # 2) CSV 우선 → JSONL에서 새 문장만 → JSON에서 새 문장만
    seen: set[str] = set(df_csv["original_text"].str.strip())

    jsonl_new = df_jsonl[~df_jsonl["original_text"].str.strip().isin(seen)].copy()
    seen.update(jsonl_new["original_text"].str.strip())

    json_new = df_json[~df_json["original_text"].str.strip().isin(seen)].copy()

    df = pd.concat([df_csv, jsonl_new, json_new], ignore_index=True)
    df = df[df["original_text"].str.len() > 0].reset_index(drop=True)

    print(f"[build] CSV={len(df_csv)}행  JSONL 신규={len(jsonl_new)}행  JSON 신규={len(json_new)}행  합계={len(df)}행")

    # 3) 분류 모델로 category / importance 전체 덮어쓰기
    clf    = _load_classifier(model)
    scorer = ImportanceScorer.load()
    texts  = df["original_text"].astype(str).tolist()

    cats = clf.predict(texts)
    imps = scorer.predict(texts, cats, today=today)

    df["category"]   = cats
    df["importance"] = [round(float(v), 2) for v in imps]

    # 4) 6열만 추출해 저장
    out_df = df[OUTPUT_COLS].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[build] 완료 → {output_path}")
    return out_df


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="3개 소스 통합 6열 CSV 생성")
    ap.add_argument("--output", type=Path,
                    default=PRED_DIR / "notices_classified.csv",
                    help="출력 CSV 경로 (기본: outputs/predictions/notices_classified.csv)")
    ap.add_argument("--csv",   type=Path, default=None, help="notices_labeled_v2.csv 경로")
    ap.add_argument("--jsonl", type=Path, default=None, help="notices_labeled_v2.jsonl 경로")
    ap.add_argument("--json",  type=Path, default=None, help="extracted_results.json 경로")
    ap.add_argument("--model", default="simple",
                    choices=["simple", "sklearn", "sbert", "kobert"])
    ap.add_argument("--today", default=None, help="기준일 YYYY-MM-DD")
    args = ap.parse_args()

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    build_notices_csv(
        args.output,
        csv_path=args.csv,
        jsonl_path=args.jsonl,
        json_path=args.json,
        model=args.model,
        today=today,
    )


if __name__ == "__main__":
    main()
