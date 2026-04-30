"""classifier 학습 CSV에서 텍스트 컬럼 콤마 따옴표 처리.

마지막 콤마 = 라벨 구분자로 보고, 그 앞 텍스트에 콤마 있으면 따옴표로 감쌈.
RFC 4180 quoted CSV로 통일.
"""
import sys
from pathlib import Path


def fix_csv(path: Path) -> int:
    """수정된 행 개수 반환."""
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = 0
    out_lines = []
    for i, line in enumerate(lines):
        if not line.strip() or i == 0:  # 빈 줄/헤더 그대로
            out_lines.append(line)
            continue
        idx = line.rfind(",")
        if idx == -1:
            out_lines.append(line)
            continue
        text = line[:idx]
        label = line[idx + 1:]
        if "," in text and not (text.startswith('"') and text.endswith('"')):
            text = '"' + text.replace('"', '""') + '"'
            changed += 1
        out_lines.append(f"{text},{label}")
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return changed


if __name__ == "__main__":
    p = Path(sys.argv[1])
    n = fix_csv(p)
    print(f"수정: {n}행 / 총 {len(p.read_text(encoding='utf-8').splitlines())}행")
