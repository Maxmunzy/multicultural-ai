"""v12 Colab 학습 노트북 — 본문/표 완전 분리 데이터 + LayoutXLM 2 layer unfreeze.

진단 (2026-05-28):
  - v11: 본문+표를 한 sequence로 merge → reading order로 본문 뒤섞임 → 정량 -0.26 폭락
  - 근본: 표 word가 본문 사이에 끼면 본문 segmentation 망가짐

v12 axis: 학습 데이터를 본문/표 record로 **완전 분리** (한 sequence에 절대 안 섞음):
  - 본문 record: clean_bboxes(정상 표 영역) 밖 v6 word + v6 라벨 (mismatch 0)
  - 표 record: camelot EAV word(cell 단위 "header: value") + cell 단위 B/I 라벨
  - 노이즈 필터: 헤더 표어(인접 반복/자간) + 본문 오검출(긴 cell) → 본문 복귀
  - inference도 본문/표 각각 hybrid forward 후 좌표 merge (룰 없음)

체크포인트: hybrid_v12_split_best.pt
"""
import json
from pathlib import Path

cells = []

def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text})

def code(text):
    cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text})

md("""# SchoolBridge — Hybrid v12 (본문/표 완전 분리 학습)

**v12 변경**: 학습 데이터를 본문 record / 표 record로 완전 분리.

**진단**:
- v11: 본문+표를 한 sequence로 merge → reading order로 본문 뒤섞임 → 정량 recall 0.84→0.59 폭락
- **root cause**: 표 word가 본문 word 사이에 끼면 본문 segmentation 망가짐

**v12 해결**: 한 page를 본문 record + 표 record **별도 sample**로 (한 sequence에 절대 안 섞음).
- 본문 record: 정상 표 영역 밖 v6 word + v6 라벨 (mismatch 0)
- 표 record: camelot EAV word(cell 단위 "header: value") + cell 단위 B/I
- 노이즈 필터: 헤더 표어(인접 반복/자간) + 본문 오검출(긴 cell) → 본문 복귀

**유지** (v10/v11과 동일):
- LayoutXLM 마지막 2 layer unfreeze + KoCharELECTRA-small + CRF
- random crop OFF, batch=2, EPOCHS=5, lr=3e-5

**기대 효과**:
- 본문: v6 라벨 그대로 학습 → 본문 정량 회복 (표 안 섞임)
- 표: cell 단위 "header: value" → inference에서 정규식 없이 모델이 재현

**inference**: 본문 word / 표 EAV word 각각 hybrid forward → 좌표 merge (룰 0)

**Colab 세팅**: 런타임 → T4 GPU.""")

md("## 1. 환경변수")
code("""import os
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
os.environ['TORCH_USE_CUDA_DSA'] = '1'
print('LAUNCH_BLOCKING:', os.environ.get('CUDA_LAUNCH_BLOCKING'))""")

md("## 2. 패키지 설치\n\n**이 셀 실행 후 반드시 [런타임 → 런타임 재시작] 클릭**")
code("""!pip install -q torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121
!pip install -q transformers==4.41.0 accelerate==0.30.0
!pip install -q sentencepiece pdfplumber pymupdf pillow
!pip install -q pytorch-crf
!pip install -q 'git+https://github.com/facebookresearch/detectron2.git'
print('=' * 50)
print('설치 완료. 반드시 [런타임 → 런타임 재시작] 클릭!')
print('=' * 50)""")

md("## 3. 환경 확인")
code("""import os
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'

import torch, transformers, detectron2, torchcrf
print('PyTorch:', torch.__version__, '| CUDA:', torch.cuda.is_available())
print('transformers:', transformers.__version__)
assert torch.__version__.startswith('2.4'), 'torch 재설치 + 재시작 필요'
assert transformers.__version__.startswith('4.41'), 'transformers 재설치 + 재시작 필요'
print('OK')""")

md("## 4. 파일 업로드 + Drive 마운트\n\n**필수**: `hybrid_model.py` (unfreeze_last_n 옵션), `hybrid_dataset.py`, `layoutxlm_bio_train_v12.jsonl`, `pdfs.zip`")
code("""from google.colab import files, drive
from pathlib import Path
import zipfile, json

drive.mount('/content/drive')

uploaded = files.upload()
for name in uploaded:
    print(f'  {name}: {len(uploaded[name])/1024/1024:.1f} MB')

for name in uploaded:
    if name.endswith('.zip'):
        with zipfile.ZipFile(name) as z:
            z.extractall('.')
        print(f'{name} extracted')

PDF_DIR = None
for cand in [Path('all_pdfs'), Path('pdfs') / 'all_pdfs', Path('pdfs'), Path('.')]:
    if cand.exists():
        pdfs_here = list(cand.glob('*.pdf'))
        if pdfs_here:
            PDF_DIR = cand
            break

assert PDF_DIR is not None, 'PDF_DIR not found'
n_pdfs = len(list(PDF_DIR.rglob('*.pdf')))
print(f'PDF_DIR: {PDF_DIR}, PDF count: {n_pdfs}')""")

md("## 5. 학습 데이터 로드 (v12 jsonl — 본문/표 분리 record)")
code("""records = []
with open('layoutxlm_bio_train_v12.jsonl', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

n_body = sum(1 for r in records if r.get('kind') == 'body')
n_table = sum(1 for r in records if r.get('kind') == 'table')
n_pdfs_unique = len({r['pdf'] for r in records})
total_b = sum(r['n_b_sent'] for r in records)
total_i = sum(r['n_i_sent'] for r in records)
total_o = sum(r['n_o'] for r in records)
print(f'Records: {len(records)} (body {n_body}, table {n_table}), Unique PDFs: {n_pdfs_unique}')
print(f'B-SENT: {total_b:,} ({100*total_b/(total_b+total_i+total_o):.1f}%)')
print(f'I-SENT: {total_i:,} ({100*total_i/(total_b+total_i+total_o):.1f}%)')
print(f'O:      {total_o:,} ({100*total_o/(total_b+total_i+total_o):.1f}%)')

missing_unique = set(r['pdf'] for r in records if not (PDF_DIR / r['pdf']).exists())
if missing_unique:
    records = [r for r in records if (PDF_DIR / r['pdf']).exists()]
    print(f'Kept records: {len(records)}')""")

md("## 6. 모델 + Dataset 로드 (LayoutXLM 2 layer unfreeze, CRF ON, random crop OFF)")
code("""import torch, random, time
from torch.utils.data import DataLoader
from transformers import LayoutXLMProcessor, AutoTokenizer

import sys
sys.path.insert(0, '.')
from hybrid_model import HybridSentenceExtractor, HybridConfig, count_params
from hybrid_dataset import HybridDataset, hybrid_collate_fn

# v12: v10/v11과 동일 모델 axis (학습 데이터만 본문/표 분리)
config = HybridConfig(
    use_crf=True,
    layoutxlm_unfreeze_last_n=2,
)
print(f'kochar_id: {config.kochar_id}')
print(f'layoutxlm_unfreeze_last_n: {config.layoutxlm_unfreeze_last_n}')

model = HybridSentenceExtractor(config)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)
total, trainable = count_params(model)
print(f'Total: {total/1e6:.1f}M, Trainable: {trainable/1e6:.1f}M')

layoutxlm_processor = LayoutXLMProcessor.from_pretrained(config.layoutxlm_id, apply_ocr=False)
char_tokenizer = AutoTokenizer.from_pretrained(config.kochar_id)

random.seed(42)
random.shuffle(records)
n_val = max(50, len(records) // 10)
val_records = records[:n_val]
train_records = records[n_val:]

# random crop OFF
train_ds = HybridDataset(train_records, PDF_DIR, layoutxlm_processor, char_tokenizer, is_train=False)
val_ds = HybridDataset(val_records, PDF_DIR, layoutxlm_processor, char_tokenizer, is_train=False)

BATCH = 2
train_loader = DataLoader(train_ds, batch_size=BATCH, shuffle=True, num_workers=2, collate_fn=hybrid_collate_fn)
val_loader = DataLoader(val_ds, batch_size=BATCH, shuffle=False, num_workers=2, collate_fn=hybrid_collate_fn)
print(f'Train: {len(train_records)} | Val: {len(val_records)}')
print(f'Batches (batch={BATCH}): train {len(train_loader)} | val {len(val_loader)}')""")

md("## 7. 학습 (5 epoch, ~4시간 예상)")
code("""import shutil

trainable_params = [p for p in model.parameters() if p.requires_grad]
optimizer = torch.optim.AdamW(trainable_params, lr=3e-5, weight_decay=0.01)
EPOCHS = 5
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

best_val = float('inf')
DRIVE_PATH = '/content/drive/MyDrive/hybrid_v12_split_best.pt'

for epoch in range(EPOCHS):
    model.train()
    train_loss = 0.0
    n_batches = 0
    t0 = time.time()
    for batch in train_loader:
        layoutxlm_inputs = {k: v.to(device) for k, v in batch['layoutxlm_inputs'].items()}
        char_input_ids = batch['char_input_ids'].to(device)
        char_attention_mask = batch['char_attention_mask'].to(device)
        char_to_word = batch['char_to_word'].to(device)
        labels = batch['labels'].to(device)

        outputs = model(
            layoutxlm_inputs=layoutxlm_inputs,
            word_ids_list=batch['word_ids_list'],
            char_input_ids=char_input_ids,
            char_attention_mask=char_attention_mask,
            char_to_word=char_to_word,
            labels=labels,
        )
        loss = outputs['loss']
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
        optimizer.step()
        train_loss += loss.item()
        n_batches += 1
        if n_batches % 50 == 0:
            print(f'  step {n_batches}/{len(train_loader)} loss={loss.item():.4f}')
    scheduler.step()

    model.eval()
    val_loss = 0.0
    with torch.no_grad():
        for batch in val_loader:
            layoutxlm_inputs = {k: v.to(device) for k, v in batch['layoutxlm_inputs'].items()}
            char_input_ids = batch['char_input_ids'].to(device)
            char_attention_mask = batch['char_attention_mask'].to(device)
            char_to_word = batch['char_to_word'].to(device)
            labels = batch['labels'].to(device)
            outputs = model(
                layoutxlm_inputs=layoutxlm_inputs,
                word_ids_list=batch['word_ids_list'],
                char_input_ids=char_input_ids,
                char_attention_mask=char_attention_mask,
                char_to_word=char_to_word,
                labels=labels,
            )
            val_loss += outputs['loss'].item()

    train_loss /= max(n_batches, 1)
    val_loss /= max(len(val_loader), 1)
    elapsed = time.time() - t0
    print(f'Epoch {epoch+1}/{EPOCHS}  train={train_loss:.4f}  val={val_loss:.4f}  ({elapsed:.0f}s)')
    if val_loss < best_val:
        best_val = val_loss
        torch.save({
            'state_dict': model.state_dict(),
            'config': config.__dict__,
        }, 'hybrid_v12_split_best.pt')
        try:
            shutil.copy('hybrid_v12_split_best.pt', DRIVE_PATH)
            print(f'  > saved best + drive backup ({DRIVE_PATH})')
        except Exception as e:
            print(f'  > saved best (drive failed: {e})')

print(f'Best val: {best_val:.4f}')
print(f'Drive: {DRIVE_PATH}')""")

md("## 8. Drive 저장 확인")
code("""import os
DRIVE_PATH = '/content/drive/MyDrive/hybrid_v12_split_best.pt'
if os.path.exists(DRIVE_PATH):
    size_mb = os.path.getsize(DRIVE_PATH) / 1024 / 1024
    print(f'OK: {DRIVE_PATH} ({size_mb:.1f} MB)')
else:
    print(f'NOT FOUND: {DRIVE_PATH}')""")

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "accelerator": "GPU",
        "colab": {"gpuType": "T4", "provenance": []},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path("sentence_extraction/colab_upload_hybrid/hybrid_train_colab_v12.ipynb")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

with open(out, encoding="utf-8") as f:
    parsed = json.load(f)
print(f"OK: {len(parsed['cells'])} cells, valid JSON, {out.stat().st_size} bytes")
