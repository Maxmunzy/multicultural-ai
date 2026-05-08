import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

nb_path = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\file\visualize_model_comparison.ipynb")
nb = json.loads(nb_path.read_text(encoding="utf-8"))

# 코드 셀만 추출해서 실행
exec_globals = {"__name__": "__main__"}
for cell in nb["cells"]:
    if cell["cell_type"] != "code":
        continue
    src = "".join(cell["source"])
    if not src.strip():
        continue
    cell_id = cell.get("id", "?")
    print(f"\n{'='*50}\n실행: {cell_id}\n{'='*50}")
    try:
        exec(src, exec_globals)
    except Exception as e:
        print(f"[오류] {cell_id}: {e}")
        import traceback
        traceback.print_exc()
