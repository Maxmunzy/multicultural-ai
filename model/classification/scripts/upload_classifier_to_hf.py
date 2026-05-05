"""
KcELECTRA 분류 모델 → HuggingFace Hub 업로드 스크립트
======================================================
사용법:
    1. HF 토큰 발급: https://huggingface.co/settings/tokens  (write 권한)
    2. HF_TOKEN과 HF_USERNAME을 아래 상수에 채우기
    3. python scripts/upload_classifier_to_hf.py

업로드 결과:
    HF Hub repo: HF_USERNAME/kcelectra-category
    서브폴더:     kcelectra-category-v3/
    → AutoModel.from_pretrained("HF_USERNAME/kcelectra-category",
                                subfolder="kcelectra-category-v3")

완료 후 반드시:
    classifier_kcelectra.py 의 _BASE_MODEL_ID 를 실제 repo ID로 수정할 것.
"""

import os
import sys
from pathlib import Path

# ── 여기 두 값을 채워 주세요 ──────────────────────────────────────
HF_TOKEN    = ""   # HF write 토큰 (빈 문자열이면 huggingface-cli login 세션 사용)
HF_USERNAME = "kysophia"
# ─────────────────────────────────────────────────────────────────

REPO_NAME   = "kcelectra-category"
SUBFOLDER   = "kcelectra-category-v3"

_HERE      = Path(__file__).parent.parent   # classification/
CKPT_DIR   = _HERE / "checkpoints" / "kcelectra-category-v3"


def _check_prerequisites():
    if not HF_USERNAME:
        print("[오류] HF_USERNAME을 이 스크립트 상단에 입력하세요.")
        sys.exit(1)

    if not CKPT_DIR.exists():
        print(f"[오류] 체크포인트 폴더가 없습니다: {CKPT_DIR}")
        print("  Colab 학습 완료 후 kcelectra-category-v3/ 를 이 경로에 두세요.")
        sys.exit(1)

    required = ["config.json", "label2id.json", "tokenizer.json", "tokenizer_config.json"]
    missing  = [f for f in required if not (CKPT_DIR / f).exists()]
    has_weights = any((CKPT_DIR / w).exists() for w in ("model.safetensors", "pytorch_model.bin"))

    if missing:
        print(f"[오류] 필수 파일 누락: {missing}")
        sys.exit(1)
    if not has_weights:
        print("[오류] model.safetensors 또는 pytorch_model.bin 이 없습니다.")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi  # noqa: F401
    except ImportError:
        print("[오류] huggingface_hub 가 설치되지 않았습니다.")
        print("  pip install huggingface-hub")
        sys.exit(1)


def upload():
    _check_prerequisites()

    from huggingface_hub import HfApi

    api      = HfApi(token=HF_TOKEN or None)
    repo_id  = f"{HF_USERNAME}/{REPO_NAME}"

    print(f"[1/3] repo 생성 또는 확인: {repo_id}")
    api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True, private=False)

    print(f"[2/3] 파일 업로드: {CKPT_DIR} → {repo_id}/{SUBFOLDER}/")
    api.upload_folder(
        folder_path=str(CKPT_DIR),
        repo_id=repo_id,
        path_in_repo=SUBFOLDER,
        commit_message=f"Add KcELECTRA classification v3 checkpoint",
    )

    print(f"\n[3/3] 완료!")
    print(f"  Hub URL : https://huggingface.co/{repo_id}")
    print(f"  로드 코드:")
    print(f'    AutoTokenizer.from_pretrained("{repo_id}", subfolder="{SUBFOLDER}")')
    print(f'    AutoModelForSequenceClassification.from_pretrained(')
    print(f'        "{repo_id}", subfolder="{SUBFOLDER}", num_labels=6)')
    print(f"\n  classifier_kcelectra.py 의 _BASE_MODEL_ID = \"{repo_id}\" 로 수정하세요.")


if __name__ == "__main__":
    upload()
