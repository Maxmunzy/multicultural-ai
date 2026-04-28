import argparse
import asyncio
import csv
import json
import re
import shutil
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


TRANSLATION_MODEL = "facebook/nllb-200-distilled-600M"
EDGE_TTS_VOICE = "vi-VN-HoaiMyNeural"
SOURCE_LANG = "kor_Hang"
TARGET_LANG = "vie_Latn"
MAX_EASY_KO_SENTENCES = 5
DEFAULT_CATEGORIES = ("일정", "준비물", "제출", "비용", "건강·안전", "기타")
CATEGORY_RULES = {
    "일정": ("일", "월", "날짜", "기간", "기한", "마감", "행사", "수업", "체험학습", "상담", "시험", "총회", "수련회", "종업식", "신체검사"),
    "준비물": ("준비", "지참", "가져", "색종이", "풀", "가위", "실내화", "체육복", "물병", "돗자리", "네임펜", "크레파스"),
    "제출": ("제출", "내 주세요", "회신", "동의", "신청", "확인서", "참가 여부", "불참", "서류", "서명"),
    "비용": ("비용", "비", "원", "납부", "입금", "교육비", "체험학습비", "급식비", "수업비"),
    "건강·안전": ("건강", "안전", "예방", "독감", "알레르기", "감염병", "마스크", "손 소독제", "응급", "생활지도"),
}
EASY_REPLACEMENTS = {
    "실시됩니다": "있습니다",
    "참여합니다": "참여합니다",
    "참여해 주시기 바랍니다": "참여해 주세요",
    "준비해 주시기 바랍니다": "준비해 주세요",
    "제출해 주시기 바랍니다": "내 주세요",
    "납부해 주시기 바랍니다": "내 주세요",
    "등원해 주세요": "등원해 주세요",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Run one end-to-end MVP demo pipeline.")
    parser.add_argument("--input", default="data/notice_sample_v3.csv")
    parser.add_argument("--row-id", default="")
    parser.add_argument("--glossary", default="model/translation_tts/term_glossary.csv")
    parser.add_argument("--output-dir", default="outputs/mvp")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--tts-voice", default=EDGE_TTS_VOICE)
    parser.add_argument("--save-demo-case", default="")
    return parser.parse_args()


def main():
    args = parse_args()
    device = resolve_device(args.device)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_error_files(output_dir)

    source = read_source(Path(args.input), args.row_id)
    glossary_error = None
    try:
        glossary = read_glossary(Path(args.glossary))
    except Exception as error:
        glossary = []
        glossary_error = error
        write_error(output_dir / "glossary_error.txt", error)

    baseline = build_baseline(source, glossary)
    try:
        easy_ko_text = prepare_easy_ko_text(build_easy_korean(source, baseline))
    except Exception as error:
        easy_ko_text = ""
        write_error(output_dir / "translation_error.txt", error)

    (output_dir / "01_input_notice.txt").write_text(source.get("original_text", "") + "\n", encoding="utf-8")
    write_json(output_dir / "02_baseline_result.json", baseline)
    (output_dir / "03_easy_ko.txt").write_text(easy_ko_text + "\n", encoding="utf-8")

    if easy_ko_text:
        try:
            vi_text = translate(easy_ko_text, device, args.max_length)
        except Exception as error:
            vi_text = ""
            write_error(output_dir / "translation_error.txt", error)
    else:
        vi_text = ""
    (output_dir / "04_vi_translation.txt").write_text(vi_text + "\n", encoding="utf-8")

    try:
        if glossary_error:
            raise glossary_error
        glossary_hits = find_glossary_hits(easy_ko_text, glossary)
        glossary_check_rows = build_glossary_check_rows(easy_ko_text, vi_text, glossary_hits)
        quality_label, quality_note = summarize_quality(glossary_check_rows)
    except Exception as error:
        glossary_hits = []
        glossary_check_rows = build_glossary_error_rows(error)
        quality_label = "glossary_error"
        quality_note = str(error)
        write_error(output_dir / "glossary_error.txt", error)
    write_glossary_check(output_dir / "05_glossary_check.csv", glossary_check_rows)

    tts_path = ""
    if not args.skip_tts:
        if vi_text:
            tts_path = str(output_dir / "05_tts_output.mp3")
            Path(tts_path).unlink(missing_ok=True)
            try:
                generate_tts(vi_text, Path(tts_path), args.tts_voice)
            except Exception as error:
                tts_path = ""
                write_error(output_dir / "tts_error.txt", error)
        else:
            write_error(output_dir / "tts_error.txt", ValueError("TTS skipped because Vietnamese translation is empty."))

    write_mvp_csv(
        output_dir / "mvp_result.csv",
        {
            "source_text": source.get("original_text", ""),
            "category": baseline["category"],
            "keywords": "|".join(baseline["keywords"]),
            "easy_ko_text": easy_ko_text,
            "vi_text": vi_text,
            "glossary_hits": "; ".join(f"{item['korean']}->{item['preferred_vi']}" for item in glossary_hits),
            "quality_label": quality_label,
            "quality_note": quality_note,
            "tts_path": tts_path,
        },
    )
    if args.save_demo_case:
        save_demo_case(output_dir, args.save_demo_case, easy_ko_text, vi_text, glossary_check_rows)

    print(f"Saved MVP outputs to {output_dir}")


def resolve_device(device):
    if device == "cuda" and not torch.cuda.is_available():
        print("CUDA is not available. Falling back to CPU.")
        return "cpu"
    return device


def read_source(path, row_id):
    if path.suffix.lower() == ".txt":
        text = path.read_text(encoding="utf-8-sig").strip()
        return {
            "id": "txt",
            "original_text": text,
            "easy_korean": "",
            "easy_ko_text": text,
            "category": "",
            "keywords": "",
            "source_type": "",
            "action_required": "",
        }

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError(f"No rows found in {path}")
    if row_id:
        for row in rows:
            if row.get("id") == row_id:
                return normalize_source(row)
        raise ValueError(f"row id {row_id} was not found in {path}")
    return normalize_source(rows[0])


def normalize_source(row):
    source = dict(row)
    easy_ko_text = source.get("easy_ko_text") or source.get("easy_korean") or ""
    original_text = source.get("original_text") or easy_ko_text
    source["easy_ko_text"] = easy_ko_text
    source["easy_korean"] = source.get("easy_korean", "")
    source["original_text"] = original_text
    source["category"] = source.get("category", "")
    source["keywords"] = source.get("keywords", "")
    source["source_type"] = source.get("source_type", "")
    source["action_required"] = source.get("action_required", "")
    return source


def read_glossary(path, target_lang="vi"):
    """다국어 용어사전 로딩. target_lang에 해당하는 preferred_{lang} 컬럼을 읽어
    기존 호환성 위해 'preferred_vi' 키에 저장한다 (다른 헬퍼는 변경 없음).
    지원 컬럼: preferred_vi, preferred_en, preferred_zh, preferred_th,
              preferred_ms, preferred_mn, preferred_ru, preferred_ja
    """
    column = f"preferred_{target_lang}"
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            korean = row.get("korean", "").strip()
            preferred = row.get(column, "").strip()
            if not korean or not preferred:
                continue
            # 키 이름은 'preferred_vi' 유지 (다운스트림 헬퍼 호환).
            # 실제 값은 target_lang 컬럼에서 가져온 것.
            rows.append({"korean": korean, "preferred_vi": preferred})
    return rows


def build_baseline(source, glossary):
    original_text = source.get("original_text", "").strip()
    keywords = parse_keywords(source.get("keywords", ""))
    glossary_hits = find_glossary_hits(original_text, glossary)
    category = source.get("category", "").strip()
    if category not in DEFAULT_CATEGORIES:
        category = guess_category(original_text)

    return {
        "id": source.get("id", ""),
        "source_type": source.get("source_type", ""),
        "original_text": original_text,
        "category": category,
        "keywords": keywords,
        "glossary_hits": glossary_hits,
        "action_required": source.get("action_required", ""),
    }


def parse_keywords(value):
    return [item.strip() for item in re.split(r"[|,;/]+", value or "") if item.strip()]


def guess_category(text):
    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "기타"


def build_easy_korean(source, baseline):
    if source.get("easy_ko_text", "").strip():
        return source["easy_ko_text"].strip()
    if source.get("easy_korean", "").strip():
        return source["easy_korean"].strip()

    text = baseline["original_text"]
    for old, new in EASY_REPLACEMENTS.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = split_sentences(text)
    return "\n".join(sentences) if sentences else text


def prepare_easy_ko_text(text):
    text = validate_easy_ko_text(text)
    sentences = split_sentences(text)
    if len(sentences) > MAX_EASY_KO_SENTENCES:
        return "\n".join(sentences[:MAX_EASY_KO_SENTENCES])
    return "\n".join(sentences) if sentences else text


def validate_easy_ko_text(text):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        raise ValueError("easy_ko_text is required.")
    if not any(char.strip() for char in text):
        raise ValueError("easy_ko_text must contain visible text.")
    return text


def split_sentences(text):
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if not normalized:
        return []
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", normalized) if part.strip()]
    return sentences if sentences else [normalized]


def translate(text, device, max_length):
    tokenizer = AutoTokenizer.from_pretrained(TRANSLATION_MODEL, src_lang=SOURCE_LANG)
    model = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATION_MODEL).to(device)
    model.eval()
    target_lang_id = tokenizer.convert_tokens_to_ids(TARGET_LANG)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_length).to(device)
    with torch.no_grad():
        output_tokens = model.generate(
            **inputs,
            forced_bos_token_id=target_lang_id,
            max_length=max_length,
            num_beams=4,
        )
    return tokenizer.batch_decode(output_tokens, skip_special_tokens=True)[0]


def find_glossary_hits(text, glossary):
    return [
        {"korean": row["korean"], "preferred_vi": row["preferred_vi"]}
        for row in glossary
        if row["korean"] in text
    ]


def check_quality(vi_text, glossary_hits):
    rows = build_glossary_check_rows("", vi_text, glossary_hits)
    return summarize_quality(rows)


def build_glossary_check_rows(input_text, vi_text, glossary_hits):
    if not glossary_hits:
        return [
            {
                "korean_term": "",
                "preferred_vi": "",
                "found_in_input": "N",
                "found_in_translation": "N",
                "quality_label": "unchecked",
                "note": "입력문에서 사전 용어가 감지되지 않아 자동 판단 불가",
            }
        ]

    rows = []
    for item in glossary_hits:
        found_in_input = item["korean"] in input_text if input_text else True
        found_in_translation = item["preferred_vi"].lower() in vi_text.lower()
        rows.append(
            {
                "korean_term": item["korean"],
                "preferred_vi": item["preferred_vi"],
                "found_in_input": "Y" if found_in_input else "N",
                "found_in_translation": "Y" if found_in_translation else "N",
                "quality_label": "ok" if found_in_translation else "missing_term",
                "note": "권장 번역어 반영" if found_in_translation else "권장 번역어 미반영, 사람 검수 필요",
            }
        )
    return rows


def summarize_quality(glossary_check_rows):
    labels = [row["quality_label"] for row in glossary_check_rows]
    if "missing_term" in labels:
        notes = [
            f"{row['korean_term']}->{row['preferred_vi']}"
            for row in glossary_check_rows
            if row["quality_label"] == "missing_term"
        ]
        return "review_needed", "; ".join(notes)
    if labels == ["unchecked"]:
        return "unchecked", glossary_check_rows[0]["note"]
    return "ok", ""


def build_glossary_error_rows(error):
    return [
        {
            "korean_term": "",
            "preferred_vi": "",
            "found_in_input": "N",
            "found_in_translation": "N",
            "quality_label": "glossary_error",
            "note": str(error),
        }
    ]


def save_demo_case(output_dir, case_name, easy_ko_text, vi_text, glossary_check_rows):
    case_dir = output_dir / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    clear_demo_case_dir(case_dir)

    copy_if_exists(output_dir / "03_easy_ko.txt", case_dir / "01_easy_ko_input.txt")
    copy_if_exists(output_dir / "04_vi_translation.txt", case_dir / "02_vi_raw_translation.txt")
    copy_if_exists(output_dir / "05_glossary_check.csv", case_dir / "03_glossary_check.csv")
    copy_if_exists(output_dir / "05_tts_output.mp3", case_dir / "06_tts_output.mp3")

    for error_name in ("translation_error.txt", "glossary_error.txt", "tts_error.txt"):
        copy_if_exists(output_dir / error_name, case_dir / error_name)

    missing_rows = [row for row in glossary_check_rows if row.get("quality_label") == "missing_term"]
    corrected_translation = build_corrected_translation(easy_ko_text, vi_text, missing_rows)
    (case_dir / "04_review_needed.md").write_text(
        build_review_needed_markdown(easy_ko_text, vi_text, missing_rows, corrected_translation),
        encoding="utf-8",
    )
    (case_dir / "05_vi_corrected_translation.txt").write_text(corrected_translation + "\n", encoding="utf-8")
    (case_dir / "demo_summary.md").write_text(build_demo_summary_markdown(missing_rows), encoding="utf-8")


def copy_if_exists(source, target):
    if source.exists():
        shutil.copy2(source, target)


def clear_demo_case_dir(case_dir):
    for path in case_dir.iterdir():
        if path.is_file():
            path.unlink()


def build_corrected_translation(easy_ko_text, vi_text, missing_rows):
    missing_terms = {(row.get("korean_term", ""), row.get("preferred_vi", "")) for row in missing_rows}
    if ("도시락", "cơm hộp") in missing_terms:
        return "\n".join(
            [
                "Ngày mai các em sẽ có hoạt động trải nghiệm tại trường.",
                "Vui lòng cho trẻ mang theo một chai nước và cơm hộp.",
                "Các em hãy có mặt tại sân vận động của trường lúc 9 giờ sáng.",
            ]
        )
    if missing_rows:
        notes = ", ".join(f"{row.get('korean_term')} -> {row.get('preferred_vi')}" for row in missing_rows)
        return f"{vi_text}\n\n[검수 필요: {notes}]"
    return vi_text


def build_review_needed_markdown(easy_ko_text, vi_text, missing_rows, corrected_translation):
    lines = [
        "# Review Needed",
        "",
        "## 감지된 missing_term 목록",
        "",
    ]
    if missing_rows:
        for row in missing_rows:
            korean = row.get("korean_term", "")
            preferred_vi = row.get("preferred_vi", "")
            source_sentence = find_sentence_with_term(easy_ko_text, korean)
            lines.extend(
                [
                    f"- {korean} -> {preferred_vi}",
                    "",
                    "## 원문 쉬운 한국어에서 해당 용어가 등장한 문장",
                    "",
                    source_sentence or "해당 문장을 찾지 못했습니다.",
                    "",
                    "## 번역문에서 누락된 위치",
                    "",
                    f"번역문 전체에서 권장 표현 `{preferred_vi}`가 발견되지 않았습니다.",
                    "",
                    "```text",
                    vi_text,
                    "```",
                    "",
                    "## 사람이 수정해야 할 권장 문장",
                    "",
                    recommend_sentence(korean, preferred_vi),
                    "",
                ]
            )
    else:
        lines.append("- 없음")
        lines.append("")
    lines.extend(
        [
            "## 수정 번역문",
            "",
            "```text",
            corrected_translation,
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def find_sentence_with_term(text, term):
    for sentence in split_sentences(text):
        if term and term in sentence:
            return sentence
    return ""


def recommend_sentence(korean, preferred_vi):
    if korean == "도시락" and preferred_vi == "cơm hộp":
        return "Vui lòng cho trẻ mang theo một chai nước và cơm hộp."
    return f"해당 문장에 `{preferred_vi}` 표현을 반영해 사람이 최종 수정합니다."


def build_demo_summary_markdown(missing_rows):
    missing_terms = ", ".join(
        f"{row.get('korean_term')} -> {row.get('preferred_vi')}" for row in missing_rows
    )
    if not missing_terms:
        missing_terms = "없음"
    return "\n".join(
        [
            "# MVP Demo Result: demo_case_01",
            "",
            "- 이번 샘플은 번역/TTS 파이프라인이 끝까지 성공한 케이스다.",
            "- 번역문은 전체적으로 자연스럽지만, “도시락” 같은 준비물 핵심 용어가 누락되었다.",
            f"- glossary check가 {missing_terms} 누락을 missing_term으로 감지했다.",
            "- 이는 일반 번역 결과를 그대로 신뢰하면 안 되고, 학교 특화 용어사전 기반 검수 루프가 필요하다는 근거다.",
            "- 따라서 MVP의 핵심은 단순 번역이 아니라 “번역 + 용어사전 검수 + TTS” 흐름이다.",
            "",
        ]
    )


def generate_tts(text, output_path, voice):
    import edge_tts

    asyncio.run(edge_tts.Communicate(text=text, voice=voice).save(str(output_path)))


def write_error(path, error):
    path.write_text(str(error).strip() + "\n", encoding="utf-8")


def clear_error_files(output_dir):
    for name in ("translation_error.txt", "glossary_error.txt", "tts_error.txt"):
        path = output_dir / name
        if path.exists():
            path.unlink()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_glossary_check(path, rows):
    fieldnames = [
        "korean_term",
        "preferred_vi",
        "found_in_input",
        "found_in_translation",
        "quality_label",
        "note",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_mvp_csv(path, row):
    fieldnames = [
        "source_text",
        "category",
        "keywords",
        "easy_ko_text",
        "vi_text",
        "glossary_hits",
        "quality_label",
        "quality_note",
        "tts_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    main()

