"""v12 추출 + 원본 raw text 같이 출력. 사용자 채팅 직접 비교용."""
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '/app/sentence_extraction')
from hybrid_infer import HybridInferer
import pdfplumber

CKPT = Path('/app/sentence_extraction/data/hybrid_v12_split_best.pt')
PDF = Path(sys.argv[1])

# 원본 raw text (pdfplumber)
print(f'=== {PDF.name} ===\n')
print('--- 원본 raw text (pdfplumber.extract_text) ---')
with pdfplumber.open(PDF) as pdf:
    for pi, page in enumerate(pdf.pages):
        txt = page.extract_text() or ''
        print(f'[page {pi}]')
        print(txt)
        print()

# v12 추출
inferer = HybridInferer(CKPT)
sents = inferer.extract_sentences(PDF, split_parser=True)
print(f'--- v12 분리파서 추출 ({len(sents)} sents) ---')
for i, s in enumerate(sents):
    print(f'[{i:02d}] {s}')
