import sys
sys.stdout.reconfigure(encoding='utf-8')
from transformers import pipeline

ckpt = r'c:\AI-human4\P1\multicultural-ai\model\extraction\checkpoints\koelectra-binary-v3.1'
print('로드 중...')
clf = pipeline('text-classification', model=ckpt, tokenizer=ckpt, device=-1, truncation=True, max_length=128)
print('완료')
tests = ['5월 20일까지 동의서를 제출해주세요.', '안녕하십니까', '납부해주시기 바랍니다.']
results = clf(tests)
for t, r in zip(tests, results):
    print(f"  label={r['label']} score={r['score']:.3f} | {t}")
