#!/usr/bin/env python3
import json, os
from collections import defaultdict

scores_dir = '/app/external_model/translation_tts/scores'
langs = ['mn','th','ru','ms','zh','ja','vi','en']
results = defaultdict(dict)

def load_scores(path, lang_filter=None):
    rows = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            if lang_filter is None or r.get('target_lang') == lang_filter:
                rows.append(r)
    return rows

for lang in langs:
    rows = load_scores(f'{scores_dir}/scores_claude-sonnet-4-6_{lang}_multilingual_v1.jsonl')
    results[lang]['claude'] = round(sum(r['total_score'] for r in rows)/len(rows), 1)

for lang in langs:
    rows = load_scores(f'{scores_dir}/scores_gemini_{lang}_multilingual_v1.jsonl')
    results[lang]['gemini'] = round(sum(r['total_score'] for r in rows)/len(rows), 1)

for lang in ['vi','en']:
    rows = load_scores(f'{scores_dir}/scores_gpt-5.5-thinking_{lang}_multilingual_v1.jsonl')
    results[lang]['gpt55'] = round(sum(r['total_score'] for r in rows)/len(rows), 1)

all_gpt55 = load_scores(f'{scores_dir}/scores_gpt-5.5-thinking_p11_all.jsonl')
for lang in ['mn','th','ru','ms','zh','ja']:
    rows = [r for r in all_gpt55 if r.get('target_lang') == lang]
    results[lang]['gpt55'] = round(sum(r['total_score'] for r in rows)/len(rows), 1)

for lang in ['vi','en']:
    rows = load_scores(f'{scores_dir}/scores_gpt-5-codex_{lang}_multilingual_v1.jsonl')
    results[lang]['codex'] = round(sum(r['total_score'] for r in rows)/len(rows), 1)

all_codex = load_scores(f'{scores_dir}/scores_gpt-5-codex_multilingual_v1.jsonl')
for lang in ['mn','th','ru','ms','zh','ja']:
    rows = [r for r in all_codex if r.get('target_lang') == lang]
    results[lang]['codex'] = round(sum(r['total_score'] for r in rows)/len(rows), 1)

labels = {
    'mn': 'MN', 'th': 'TH', 'ru': 'RU', 'ms': 'MS',
    'zh': 'ZH', 'ja': 'JA', 'vi': 'VI', 'en': 'EN'
}

print("lang  | Claude | GPT55 | Gemini | Codex | avg4")
print("------+--------+-------+--------+-------+------")
all_avgs = []
for lang in langs:
    c  = results[lang]['claude']
    g  = results[lang]['gpt55']
    ge = results[lang]['gemini']
    co = results[lang]['codex']
    avg4 = round((c+g+ge+co)/4, 1)
    all_avgs.append(avg4)
    print(f"{labels[lang]:5} | {c:6} | {g:5} | {ge:6} | {co:5} | {avg4:5}")

print("------+--------+-------+--------+-------+------")
c_avg  = round(sum(results[l]['claude'] for l in langs)/8, 1)
g_avg  = round(sum(results[l]['gpt55']  for l in langs)/8, 1)
ge_avg = round(sum(results[l]['gemini'] for l in langs)/8, 1)
co_avg = round(sum(results[l]['codex']  for l in langs)/8, 1)
tot    = round(sum(all_avgs)/8, 1)
print(f"{'ALL':5} | {c_avg:6} | {g_avg:5} | {ge_avg:6} | {co_avg:5} | {tot:5}")
