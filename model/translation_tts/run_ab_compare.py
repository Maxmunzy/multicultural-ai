"""
A/B 번역 비교 스크립트
A: 공지 전체 문장 → NLLB 직통 번역
B: is_todo=true 문장만 → NLLB 번역 (파이프라인 방식)

사용법:
    python run_ab_compare.py --notice-id N02
    python run_ab_compare.py --notice-id N06 --lang en
    python run_ab_compare.py  # 전체 N01~N19 일괄 비교
"""
import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

# Windows CP949 터미널에서 다국어 출력 깨짐 방지
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from languages import DEFAULT_LANGUAGE, LANGUAGES

TRANSLATION_MODEL = "facebook/nllb-200-distilled-600M"
SOURCE_LANG = "kor_Hang"
DEFAULT_DATA = Path(__file__).parent.parent.parent / (
    "model/extraction/data/notices_labeled_v2.jsonl"
)


# ── 데이터 로딩 ─────────────────────────────────────────────

def load_notices(path: Path) -> dict[str, list[dict]]:
    """notice_id별로 문장 목록 묶기. 중복(original_id 있는 행) 제거."""
    grouped: dict[str, list[dict]] = {}
    seen: set[tuple] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["notice_id"], row["sentence"])
        if key in seen:
            continue
        seen.add(key)
        grouped.setdefault(row["notice_id"], []).append(row)
    return grouped


# ── NLLB 모델 (한 번만 로드) ────────────────────────────────

def load_model(device: str):
    print(f"[모델 로딩] {TRANSLATION_MODEL} ({device}) ...")
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(TRANSLATION_MODEL, src_lang=SOURCE_LANG)
    model = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATION_MODEL).to(device)
    model.eval()
    print(f"[모델 로딩 완료] {time.time() - t0:.1f}초")
    return tokenizer, model


def split_for_translation(text: str, tokenizer, max_input_tokens: int) -> list[str]:
    """Split long notices so NLLB does not silently truncate at tokenizer max_length."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", text) if s.strip()]
    if not sentences:
        sentences = [text.strip()] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        candidate = " ".join(current + [sentence]).strip()
        token_count = len(tokenizer(candidate, add_special_tokens=True).input_ids)
        if current and token_count > max_input_tokens:
            chunks.append(" ".join(current))
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        chunks.append(" ".join(current))
    return chunks


def translate_chunk(text: str, tokenizer, model, device: str, nllb_code: str,
                    max_input_tokens: int, max_output_tokens: int) -> tuple[str, float]:
    target_id = tokenizer.convert_tokens_to_ids(nllb_code)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_input_tokens).to(device)
    t0 = time.time()
    with torch.no_grad():
        tokens = model.generate(
            **inputs,
            forced_bos_token_id=target_id,
            max_new_tokens=max_output_tokens,
            num_beams=4,
        )
    elapsed = time.time() - t0
    return tokenizer.batch_decode(tokens, skip_special_tokens=True)[0], elapsed


def translate(text: str, tokenizer, model, device: str, nllb_code: str,
              max_input_tokens: int = 384, max_output_tokens: int = 512) -> tuple[str, float, int]:
    chunks = split_for_translation(text, tokenizer, max_input_tokens)
    outputs: list[str] = []
    total_elapsed = 0.0
    for chunk in chunks:
        translated, elapsed = translate_chunk(
            chunk, tokenizer, model, device, nllb_code, max_input_tokens, max_output_tokens
        )
        outputs.append(translated)
        total_elapsed += elapsed
    return "\n".join(outputs), total_elapsed, len(chunks)


# ── A/B 비교 ────────────────────────────────────────────────

def safe_print(text: str, prefix: str = ""):
    encoded = (prefix + text).encode(errors="replace").decode(errors="replace")
    print(encoded)


def compare_notice(notice_id: str, rows: list[dict], tokenizer, model, device: str,
                   nllb_code: str, lang: str, max_input_tokens: int, max_output_tokens: int) -> dict:
    title = rows[0]["notice_title"]

    # A: 전체 문장
    text_a = " ".join(r["sentence"] for r in rows)
    # B: is_todo=true만
    todo_rows = [r for r in rows if r.get("is_todo")]
    text_b = " ".join(r["sentence"] for r in todo_rows)

    print(f"\n{'='*60}")
    print(f"[{notice_id}] {title}")
    print(f"  A 전체: {len(text_a)}자 ({len(rows)}문장)")
    print(f"  B TODO: {len(text_b)}자 ({len(todo_rows)}문장)")

    if nllb_code is None:
        print("  [skip] 쉬운 한국어는 NLLB 번역 없음")
        return {}

    if not text_b:
        print("  [skip] is_todo=true 문장 없음")
        return {}

    print("\n  [A 번역 중...]")
    result_a, time_a, chunks_a = translate(
        text_a, tokenizer, model, device, nllb_code, max_input_tokens, max_output_tokens
    )
    print(f"  → {time_a:.2f}초 | {len(result_a)}자 | {chunks_a}청크")
    safe_print(result_a[:120] + ("..." if len(result_a) > 120 else ""), prefix="  ")

    print("\n  [B 번역 중...]")
    result_b, time_b, chunks_b = translate(
        text_b, tokenizer, model, device, nllb_code, max_input_tokens, max_output_tokens
    )
    print(f"  → {time_b:.2f}초 | {len(result_b)}자 | {chunks_b}청크")
    safe_print(result_b[:120] + ("..." if len(result_b) > 120 else ""), prefix="  ")

    reduction_chars = round((1 - len(text_b) / len(text_a)) * 100, 1)
    speedup = round(time_a / time_b, 2) if time_b > 0 else 0

    print(f"\n  입력 단축: -{reduction_chars}% | 속도: {time_b:.2f}s vs {time_a:.2f}s (x{speedup})")

    return {
        "notice_id": notice_id,
        "title": title,
        "lang": lang,
        "a_chars": len(text_a),
        "b_chars": len(text_b),
        "input_reduction_pct": reduction_chars,
        "a_time_sec": round(time_a, 2),
        "b_time_sec": round(time_b, 2),
        "a_chunks": chunks_a,
        "b_chunks": chunks_b,
        "speedup_x": speedup,
        "a_translation": result_a,
        "b_translation": result_b,
        "a_input": text_a,
        "b_input": text_b,
    }


# ── 결과 저장 ────────────────────────────────────────────────

def save_results(results: list[dict], lang: str):
    import json as _json
    out_dir = Path(__file__).parent / "outputs" / "ab_compare" / lang
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_lines = [
        "# A/B 번역 비교 결과",
        "",
        f"언어: {lang}  |  모델: {TRANSLATION_MODEL}",
        "",
        "| 공지 | 제목 | A입력(자) | B입력(자) | 입력단축 | A시간(s) | B시간(s) | 속도향상 |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        if not r:
            continue
        summary_lines.append(
            f"| {r['notice_id']} | {r['title'][:20]} | {r['a_chars']} | {r['b_chars']} "
            f"| -{r['input_reduction_pct']}% | {r['a_time_sec']} | {r['b_time_sec']} | x{r['speedup_x']} |"
        )
        detail_path = out_dir / f"{r['notice_id']}.md"
        detail_path.write_text(
            f"# {r['notice_id']} — {r['title']}\n\n"
            f"| 항목 | A (원문 전체) | B (TODO만) |\n"
            f"|---|---|---|\n"
            f"| 입력 글자수 | {r['a_chars']}자 | {r['b_chars']}자 |\n"
            f"| 번역 시간 | {r['a_time_sec']}초 | {r['b_time_sec']}초 |\n"
            f"| 입력 단축 | — | -{r['input_reduction_pct']}% |\n"
            f"| 번역 청크 | {r['a_chunks']} | {r['b_chunks']} |\n"
            f"| 속도향상 | — | x{r['speedup_x']} |\n\n"
            f"## A: 원문 전체\n\n"
            f"**입력:**\n```\n{r['a_input']}\n```\n\n"
            f"**번역:**\n```\n{r['a_translation']}\n```\n\n"
            f"## B: TODO만\n\n"
            f"**입력:**\n```\n{r['b_input']}\n```\n\n"
            f"**번역:**\n```\n{r['b_translation']}\n```\n",
            encoding="utf-8",
        )

    summary_path = out_dir / "summary.md"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    # JSON 저장 — 품질 평가 등 후속 분석용
    json_path = out_dir / "results.json"
    json_path.write_text(
        _json.dumps([r for r in results if r], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n[저장 완료] {out_dir}")
    print(f"  요약: {summary_path}")
    print(f"  JSON: {json_path}")


# ── 메인 ─────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--notice-id", default="", help="특정 공지 ID (예: N02). 비우면 전체 실행")
    p.add_argument("--data", default=str(DEFAULT_DATA), help="notices_labeled_v2.jsonl 경로")
    p.add_argument("--lang", default=DEFAULT_LANGUAGE, choices=list(LANGUAGES.keys()))
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    p.add_argument("--max-input-tokens", type=int, default=384)
    p.add_argument("--max-output-tokens", type=int, default=512)
    return p.parse_args()


def main():
    args = parse_args()
    data_path = Path(args.data)
    if not data_path.exists():
        raise FileNotFoundError(f"데이터 파일 없음: {data_path}")

    lang_config = LANGUAGES[args.lang]
    nllb_code = lang_config["nllb_code"]

    if nllb_code is None:
        print(f"[{args.lang}] NLLB 번역 없는 언어 (쉬운 한국어). 종료.")
        return

    device = args.device
    if device == "cuda" and not torch.cuda.is_available():
        print("CUDA 없음. CPU로 전환.")
        device = "cpu"

    all_notices = load_notices(data_path)

    if args.notice_id:
        nids = [args.notice_id]
    else:
        nids = sorted(all_notices.keys())

    tokenizer, model = load_model(device)

    results = []
    for nid in nids:
        if nid not in all_notices:
            print(f"[{nid}] 데이터 없음 — 스킵")
            continue
        r = compare_notice(
            nid,
            all_notices[nid],
            tokenizer,
            model,
            device,
            nllb_code,
            args.lang,
            args.max_input_tokens,
            args.max_output_tokens,
        )
        results.append(r)

    save_results([r for r in results if r], args.lang)

    # 최종 요약 출력
    valid = [r for r in results if r]
    if valid:
        avg_reduction = round(sum(r["input_reduction_pct"] for r in valid) / len(valid), 1)
        avg_speedup = round(sum(r["speedup_x"] for r in valid) / len(valid), 2)
        print(f"\n{'='*60}")
        print(f"[전체 평균] 입력 단축: -{avg_reduction}% | 속도향상: x{avg_speedup}")


if __name__ == "__main__":
    main()
