#!/usr/bin/env python3
"""P11-E 반영 후 전체 출력 생성 + Claude 자동 채점"""
import json, sys, os
sys.path.insert(0, '/app')
from app.services.translator import translate_short_sentence

EVAL_DIR = '/app/external_model/translation_tts/eval_chunks'
OUT = '/app/external_model/translation_tts/eval_chunks/reeval_p11e_all.jsonl'

langs = ['mn','th','ru','ms','zh','ja','vi','en']

with open(f'{EVAL_DIR}/vi_multilingual_v1.json') as f:
    sentences = json.load(f)

rows = []
for item in sentences:
    base = item['id'].rsplit('_', 1)[0]
    ko = item['text_ko']
    for lang in langs:
        out = translate_short_sentence(ko, lang)
        rows.append({'base_id': base, 'lang': lang, 'text_ko': ko, 'output': out})
        print(f'[{base}_{lang}] {out}')

with open(OUT, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

print(f'\n[DONE] {len(rows)}개 → {OUT}')
