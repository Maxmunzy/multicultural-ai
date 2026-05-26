"""v5 dump → markdown 변환. PoC PDF별 추출 sentence + Claude vs BIO 매칭."""

from __future__ import annotations

import io
import json
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

with open("sentence_extraction/data/v5_dump.json", encoding="utf-8") as f:
    v5 = json.load(f)
with open("sentence_extraction/data/eval_bio_v5_entity.json", encoding="utf-8") as f:
    eval5 = json.load(f)
eval5_map = {r["pdf"]: r for r in eval5}


def norm(s: str) -> str:
    return "".join(s.split())


lines: list[str] = []
lines.append("# v5 (현재 best) 추출 sentence + 누락 todo 분석\n")
lines.append("PoC 6장 가정통신문. 본문은 KoCharELECTRA BIO 모델, 표는 entity별 묶음 + cell bullet 분리 룰.\n")

ORDER = [
    "2026 북부과학교육관 어린이날 행사 안내 가정통신문.pdf",
    "2026 2,3,5,6학년 구강검진 실시안내.pdf",
    "2025. 겨울방학 도서관 이용 및 독서캠프 신청 안내.pdf",
    "2026년+5월+서귀포외국문화학습관+토요프로그램+추가+모집+안내.pdf",
    "인플루엔자예방접종접종안내(2019).pdf",
    "2024학년도 4학년 현장체험학습 정산 안내.pdf",
]

for pdf in ORDER:
    data = v5.get(pdf, {})
    e = eval5_map.get(pdf, {})
    bio_sents = data.get("bio", [])
    table_sents = data.get("table", [])
    best = data.get("best_parser", "?")
    claude_todos = e.get("claude_todos", [])
    bio_todos = e.get("bio_todos", [])
    recall = e.get("recall", 0)
    precision = e.get("precision", 0)

    lines.append("---\n")
    lines.append(f"## {pdf}\n")
    lines.append(f"- best parser: `{best}`")
    lines.append(f"- BIO sentence: {len(bio_sents)}개, 표 sentence: {len(table_sents)}개")
    lines.append(f"- Claude todo: {len(claude_todos)}개, 우리 모델 todo: {len(bio_todos)}개")
    lines.append(f"- **recall {recall:.3f}, precision {precision:.3f}**\n")

    # 매칭 분석 — 누락된 Claude todo
    c_norms = [(norm(t), t) for t in claude_todos]
    b_norms = [norm(t) for t in bio_todos]
    missed: list[str] = []
    for cn, ct in c_norms:
        ok = False
        for bn in b_norms:
            if cn == bn or cn in bn or bn in cn:
                ok = True
                break
        if not ok:
            missed.append(ct)

    lines.append("### 본문 추출 sentence (BIO 모델)\n")
    lines.append("```")
    for i, s in enumerate(bio_sents):
        s1 = s.replace("\n", " ⏎ ")
        lines.append(f"[{i:02d}] {s1}")
    lines.append("```\n")

    if table_sents:
        lines.append("### 표 추출 sentence (entity 묶음 + bullet 분리)\n")
        lines.append("```")
        for i, s in enumerate(table_sents):
            lines.append(f"[{i:02d}] {s}")
        lines.append("```\n")

    lines.append("### Claude 정답 todo (분류기 통과 후)\n")
    lines.append("```")
    for i, t in enumerate(claude_todos):
        lines.append(f"[{i:02d}] {t}")
    lines.append("```\n")

    lines.append("### 우리 모델 todo (분류기 통과 후)\n")
    lines.append("```")
    for i, t in enumerate(bio_todos):
        lines.append(f"[{i:02d}] {t}")
    lines.append("```\n")

    if missed:
        lines.append(f"### ⚠ 누락된 Claude todo ({len(missed)}개)\n")
        for t in missed:
            lines.append(f"- `{t}`")
        lines.append("")
    else:
        lines.append("### ✅ 누락 없음 (Claude todo 모두 매칭)\n")

with open("sentence_extraction/v5_extraction_report.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Wrote sentence_extraction/v5_extraction_report.md")
