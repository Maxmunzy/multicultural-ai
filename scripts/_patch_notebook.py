"""
train_koelectra_base.ipynb 패치:
1. cell-6 INPUT_FILE → v4_merged_train.jsonl
2. 셀 끝에 HF Hub 업로드 셀 추가
"""
import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

nb_path = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\file\train_koelectra_base.ipynb")
nb = json.loads(nb_path.read_text(encoding="utf-8"))

# ── 1. cell-6: INPUT_FILE 변경 ─────────────────────────────────────────────
for cell in nb["cells"]:
    if cell.get("id") == "cell-6":
        src = "".join(cell["source"])
        src = src.replace(
            "INPUT_FILE = 'v3.1.3_dual_labeled.jsonl'",
            "INPUT_FILE = 'v4_merged_train.jsonl'     # v3.1.3(22,523) + v4_clean(24,625) 병합"
        )
        # 주석 업데이트
        src = src.replace(
            "# INPUT_FILE = 'v3.1.3_dual_labeled.jsonl'",
            "# INPUT_FILE = 'v3.1.3_dual_labeled.jsonl'  # 이전 버전"
        ) if "# INPUT_FILE = 'v3.1.3_dual_labeled.jsonl'" in src else src
        cell["source"] = [src]
        print("cell-6 업데이트 완료")

# ── 2. HF Hub 업로드 셀 추가 (cell-28, cell-29) ───────────────────────────
hf_md_cell = {
    "cell_type": "markdown",
    "id": "cell-28",
    "metadata": {},
    "source": [
        "## 14. HF Hub 업로드\n",
        "\n",
        "`yunjeong116/koelectra-extractor` 에 새 가중치를 푸시합니다.  \n",
        "Colab Secrets 에 `HF_TOKEN` 을 설정하거나 아래 변수에 직접 입력하세요."
    ]
}

hf_code_cell = {
    "cell_type": "code",
    "execution_count": None,
    "id": "cell-29",
    "metadata": {},
    "outputs": [],
    "source": [
        "from huggingface_hub import HfApi\n",
        "\n",
        "HF_REPO  = 'yunjeong116/koelectra-extractor'\n",
        "HF_SUBFOLDER = 'koelectra-extractor'  # repo 내 서브폴더\n",
        "\n",
        "# Colab Secrets 사용 (권장)\n",
        "try:\n",
        "    from google.colab import userdata\n",
        "    HF_TOKEN = userdata.get('HF_TOKEN')\n",
        "except Exception:\n",
        "    HF_TOKEN = ''  # ← 직접 입력: 'hf_...'\n",
        "\n",
        "assert HF_TOKEN, 'HF_TOKEN 이 비어있습니다. Colab Secrets 또는 직접 입력 필요.'\n",
        "\n",
        "api = HfApi()\n",
        "api.upload_folder(\n",
        "    folder_path=OUTPUT_DIR,\n",
        "    repo_id=HF_REPO,\n",
        "    path_in_repo=HF_SUBFOLDER,\n",
        "    repo_type='model',\n",
        "    commit_message=f'retrain: v3.1.3 + v4_merged (47,148 sentences), threshold={best_thr}',\n",
        "    token=HF_TOKEN,\n",
        ")\n",
        "print(f'업로드 완료: https://huggingface.co/{HF_REPO}')"
    ]
}

# cell-26(zip 다운로드) 뒤, cell-27(마지막 마크다운) 앞에 삽입
insert_after = "cell-26"
new_cells = []
for cell in nb["cells"]:
    new_cells.append(cell)
    if cell.get("id") == insert_after:
        new_cells.append(hf_md_cell)
        new_cells.append(hf_code_cell)
        print("HF Hub 셀 삽입 완료 (cell-28, cell-29)")

nb["cells"] = new_cells

# ── 저장 ──────────────────────────────────────────────────────────────────
nb_path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"저장 완료: {nb_path}  (총 {len(nb['cells'])}개 셀)")
