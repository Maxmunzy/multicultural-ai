"""v8 Colab 학습 노트북 생성 — Hybrid + CRF + 표 cell 단위 라벨 (v8 jsonl).

v7 (CRF) base에서 학습 데이터만 v6 → v8로 교체.
- jsonl: layoutxlm_bio_train_v8.jsonl
- checkpoint: hybrid_v8_crf_best.pt
- Drive backup: /content/drive/MyDrive/hybrid_v8_crf_best.pt
"""
import json
from pathlib import Path

cells = []

def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text})

def code(text):
    cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text})

md("""# SchoolBridge — Hybrid + CRF v8 학습 (표 cell 단위 라벨 axis)

**v8 변경**:
- 학습 데이터 라벨링 정책: v6 표 영역 라벨링 일관성 X (cell별로 O/I/B 들쭉날쭉)
- v8: pdfplumber.find_tables로 표 검출 → **cell = sentence** (cell 안 multi-line은 한 sentence로 묶음)
- 본문(표 밖) 라벨은 v6 그대로 유지
- 4019 record 중 2825 (70%) ok, 1194 (30%) no_tables (v6 유지)

**전제**:
- v6 → v8 재라벨 jsonl (layoutxlm_bio_train_v8.jsonl)
- hybrid_model.py use_crf=True 그대로 (v7과 동일 architecture)
- v7 CRF + parser dedup 효과는 inference 시점에 그대로 유지

**Colab 세팅**: 런타임 → T4 GPU""")

md("## 1. 환경변수 (반드시 첫 셀)")
code("""import os
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
os.environ['TORCH_USE_CUDA_DSA'] = '1'
print('LAUNCH_BLOCKING:', os.environ.get('CUDA_LAUNCH_BLOCKING'))""")

md("## 2. 패키지 설치 (CRF 포함)\n\n**이 셀 실행 후 반드시 [런타임 → 런타임 재시작] 클릭**")
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

import torch
import transformers
import detectron2
import torchcrf
print('PyTorch:', torch.__version__, '| CUDA:', torch.cuda.is_available())
print('transformers:', transformers.__version__)
print('detectron2:', detectron2.__version__)
print('torchcrf:', torchcrf.__version__ if hasattr(torchcrf, '__version__') else 'OK')

assert torch.__version__.startswith('2.4'), 'torch 재설치 + 재시작 필요'
assert transformers.__version__.startswith('4.41'), 'transformers 재설치 + 재시작 필요'
print('OK — all versions match.')""")

md("## 4. 파일 업로드 + Drive 마운트\n\n**업로드 파일**: `hybrid_model.py`, `hybrid_dataset.py`, `layoutxlm_bio_train_v8.jsonl`, `pdfs.zip` (또는 `pdfs.tar`)")
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

md("## 5. v8 학습 데이터 로드")
code("""records = []
with open('layoutxlm_bio_train_v8.jsonl', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

n_pdfs_unique = len({r['pdf'] for r in records})
total_chars = sum(r['n_chars'] for r in records)
total_b = sum(r['n_b_sent'] for r in records)
total_i = sum(r['n_i_sent'] for r in records)
total_o = sum(r['n_o'] for r in records)

print(f'Page records: {len(records)}')
print(f'Unique PDFs: {n_pdfs_unique}')
print(f'B-SENT: {total_b:,} ({100*total_b/(total_b+total_i+total_o):.1f}%)')
print(f'I-SENT: {total_i:,} ({100*total_i/(total_b+total_i+total_o):.1f}%)')
print(f'O:      {total_o:,} ({100*total_o/(total_b+total_i+total_o):.1f}%)')

missing_unique = set(r['pdf'] for r in records if not (PDF_DIR / r['pdf']).exists())
print(f'Missing PDFs: {len(missing_unique)}')
if missing_unique:
    records = [r for r in records if (PDF_DIR / r['pdf']).exists()]
    print(f'Kept records: {len(records)}')""")

md("## 6. 모델 + Dataset 로드 (CRF 활성화)")
code("""import torch, random, time
from torch.utils.data import DataLoader
from transformers import LayoutXLMProcessor, AutoTokenizer

import sys
sys.path.insert(0, '.')
from hybrid_model import HybridSentenceExtractor, HybridConfig, count_params
from hybrid_dataset import HybridDataset, hybrid_collate_fn

# v7과 동일 — CRF 활성화
config = HybridConfig(use_crf=True)
model = HybridSentenceExtractor(config)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)
total, trainable = count_params(model)
print(f'Total: {total/1e6:.1f}M, Trainable: {trainable/1e6:.1f}M (CRF enabled)')

layoutxlm_processor = LayoutXLMProcessor.from_pretrained(config.layoutxlm_id, apply_ocr=False)
char_tokenizer = AutoTokenizer.from_pretrained(config.kochar_id)

random.seed(42)
random.shuffle(records)
n_val = max(50, len(records) // 10)
val_records = records[:n_val]
train_records = records[n_val:]

train_ds = HybridDataset(train_records, PDF_DIR, layoutxlm_processor, char_tokenizer)
val_ds = HybridDataset(val_records, PDF_DIR, layoutxlm_processor, char_tokenizer)

BATCH = 2
train_loader = DataLoader(train_ds, batch_size=BATCH, shuffle=True, num_workers=2, collate_fn=hybrid_collate_fn)
val_loader = DataLoader(val_ds, batch_size=BATCH, shuffle=False, num_workers=2, collate_fn=hybrid_collate_fn)
print(f'Train: {len(train_records)} | Val: {len(val_records)}')
print(f'Batches (batch={BATCH}): train {len(train_loader)} | val {len(val_loader)}')""")

md("## 7. 학습 (5 epoch, CRF loss, v8 jsonl)")
code("""import shutil

trainable_params = [p for p in model.parameters() if p.requires_grad]
optimizer = torch.optim.AdamW(trainable_params, lr=3e-5, weight_decay=0.01)
EPOCHS = 5
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

best_val = float('inf')
DRIVE_PATH = '/content/drive/MyDrive/hybrid_v8_crf_best.pt'

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
        }, 'hybrid_v8_crf_best.pt')
        try:
            shutil.copy('hybrid_v8_crf_best.pt', DRIVE_PATH)
            print(f'  > saved best + drive backup ({DRIVE_PATH})')
        except Exception as e:
            print(f'  > saved best (drive failed: {e})')

print(f'Best val: {best_val:.4f}')
print(f'Drive: {DRIVE_PATH}')""")

md("## 8. Drive 저장 확인")
code("""import os
DRIVE_PATH = '/content/drive/MyDrive/hybrid_v8_crf_best.pt'
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

out = Path("sentence_extraction/colab_upload_hybrid/hybrid_train_colab_v8.ipynb")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

with open(out, encoding="utf-8") as f:
    parsed = json.load(f)
print(f"OK: {len(parsed['cells'])} cells, valid JSON, {out.stat().st_size} bytes")
