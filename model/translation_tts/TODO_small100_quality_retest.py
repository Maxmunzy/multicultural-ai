"""SMaLL-100 정확도 우선 설정 재실험 계획.

현재 결론 (2026-05-06):
- NLLB greedy(num_beams=1)가 20개 학교 공지 샘플 전부에서 SMaLL-100보다 우세
- SMaLL-100 주요 실패 패턴:
    1. 반복 출력: "Lời bài hát:", "Chương trình giảng dạy:" 무한반복
    2. 금액 오역: won → USD (후처리 없으므로)
    3. 테이블 구조 파괴
- SMaLL-100은 평균 2.24배 빠름 — 품질만 확보하면 성능 이점이 큼

재실험 목적:
- 반복 출력이 repetition_penalty 부족 때문인지 확인
- slot placeholder(__SLOT0__)가 SMaLL-100 통과 시 보존되는지 확인
- 정확도 우선 설정에서 NLLB 대비 품질 gap이 얼마나 줄어드는지 확인

실험 전 필수 조건:
    pip install hf_transfer  # 빠른 다운로드 (선택)
    # 모델 크기: SMaLL-100 약 600MB (NLLB와 유사)
    # HuggingFace: alirezamsh/small100

재실험 설정 후보:
"""

# ── 실험 설정 후보 ──────────────────────────────────────────────
RETEST_CONFIGS = [
    {
        "name": "A_beam4_rp15",
        "num_beams": 4,
        "repetition_penalty": 1.5,
        "no_repeat_ngram_size": 4,
        "max_length": 256,
        "length_penalty": 1.0,
        "note": "반복 출력 억제 우선. 속도 손해 있음 (beam4).",
    },
    {
        "name": "B_beam4_rp13_ngram4",
        "num_beams": 4,
        "repetition_penalty": 1.3,
        "no_repeat_ngram_size": 4,
        "max_length": 256,
        "length_penalty": 1.0,
        "note": "현재 NLLB와 동일 penalty. SMaLL-100이 beam4로 개선되는지 확인.",
    },
    {
        "name": "C_greedy_rp15_ngram4",
        "num_beams": 1,
        "repetition_penalty": 1.5,
        "no_repeat_ngram_size": 4,
        "max_length": 256,
        "length_penalty": 1.0,
        "note": "greedy + 강한 penalty. 속도 유지 + 반복 억제 균형.",
    },
]

# ── 슬롯 placeholder 통과 검증 대상 샘플 ───────────────────────
SLOT_TEST_SAMPLES = [
    # (korean, expected_slot_survival)
    ("신청은 __SLOT0__ 에서 문의는 __SLOT1__", ["__SLOT0__", "__SLOT1__"]),
    ("__SLOT0__까지 제출해 주세요", ["__SLOT0__"]),
    ("참가비 __SLOT0__ 납부", ["__SLOT0__"]),
]

# ── 실험 실행 코드 (모델 다운로드 후 주석 해제) ────────────────
# TODO: 아래 코드는 SMaLL-100 모델 다운로드 후 실행할 것.
#       실행 전: pip install transformers torch
#       모델: alirezamsh/small100 (HuggingFace)
#
# import torch
# from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
# import csv, time
#
# MODEL_NAME = "alirezamsh/small100"
# SOURCE_LANG = "ko"   # SMaLL-100은 2글자 ISO 코드 사용
# TARGET_LANG = "vi"
#
# tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
# tokenizer.src_lang = SOURCE_LANG
# model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
# model.eval()
#
# def run_small100(text: str, config: dict) -> tuple[str, float]:
#     target_id = tokenizer.convert_tokens_to_ids(TARGET_LANG)
#     inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
#     t0 = time.time()
#     with torch.no_grad():
#         out = model.generate(
#             **inputs,
#             forced_bos_token_id=target_id,
#             num_beams=config["num_beams"],
#             repetition_penalty=config["repetition_penalty"],
#             no_repeat_ngram_size=config["no_repeat_ngram_size"],
#             max_length=config["max_length"],
#             length_penalty=config["length_penalty"],
#         )
#     elapsed = time.time() - t0
#     return tokenizer.batch_decode(out, skip_special_tokens=True)[0], elapsed
#
# # slot placeholder 통과 검증
# for sample, expected_slots in SLOT_TEST_SAMPLES:
#     for cfg in RETEST_CONFIGS:
#         result, _ = run_small100(sample, cfg)
#         passed = all(slot in result for slot in expected_slots)
#         print(f"[{cfg['name']}] slot_pass={passed} | in={sample!r} | out={result!r}")
#
# # 학교 공지 샘플 품질 평가
# # small100_vs_nllb_vi.csv의 text_ko 컬럼 재사용
# with open("outputs/model_compare/small100_vs_nllb_vi.csv") as f:
#     reader = csv.DictReader(f)
#     samples = [(r["eval_id"], r["text_ko"], r["nllb_translation"]) for r in reader]
#
# results = []
# for eval_id, text_ko, nllb_ref in samples:
#     for cfg in RETEST_CONFIGS:
#         translated, elapsed = run_small100(text_ko, cfg)
#         repeat_flag = translated.count(translated[:20]) > 3 if len(translated) > 20 else False
#         results.append({
#             "eval_id": eval_id,
#             "config": cfg["name"],
#             "translation": translated,
#             "time_sec": round(elapsed, 3),
#             "repeat_detected": repeat_flag,
#             "nllb_ref": nllb_ref,
#         })
#         print(f"{eval_id} [{cfg['name']}] {elapsed:.2f}s repeat={repeat_flag}")
#         print(f"  → {translated[:80]}")
#
# # 결과 저장
# import json
# with open("outputs/model_compare/small100_retest_results.json", "w", encoding="utf-8") as f:
#     json.dump(results, f, ensure_ascii=False, indent=2)

# ── 평가 기준 ────────────────────────────────────────────────────
# 서비스 적용 판단 기준 (NLLB 대비):
#   1. 반복 출력 0% — 필수 (현재 30% 샘플에서 발생)
#   2. slot placeholder(__SLOT0__) 100% 보존 — 필수
#   3. 날짜/금액/준비물 용어 보존율 >= NLLB 수준
#   4. 속도 이점 1.5배 이상 유지 — beam4 사용 시 확인 필요
