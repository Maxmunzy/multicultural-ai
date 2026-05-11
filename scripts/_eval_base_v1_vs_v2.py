"""
base-v1 (v3.1.3 학습) vs base (v4_merged 재학습) — galsan unseen 비교
evaluate_model.py 출력을 캡처해서 MD 파일 생성까지 자동화.
"""
import json, sys, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

ROOT   = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction")
TEST   = ROOT / "data/draft/unseen_test_galsan.jsonl"
V1     = ROOT / "checkpoints/koelectra-binary-base-v1"
V2     = ROOT / "checkpoints/koelectra-binary-base"
SCRIPT = ROOT / "file/evaluate_model.py"
PYTHON = r"C:\Users\chiej\miniconda3\envs\multicultural\python.exe"

env = {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
       **__import__("os").environ}

print("평가 실행 중...")
result = subprocess.run(
    [PYTHON, str(SCRIPT),
     "--test_data", str(TEST),
     "--v2_model",  str(V1),
     "--v3_model",  str(V2)],
    capture_output=True, text=True, encoding="utf-8", env=env,
    timeout=600,
)
output = result.stdout + result.stderr
print(output)
Path(r"c:\AI-human4\P1\multicultural-ai\scripts\_eval_output.txt").write_text(output, encoding="utf-8")
print("완료. _eval_output.txt 에 저장됨")
