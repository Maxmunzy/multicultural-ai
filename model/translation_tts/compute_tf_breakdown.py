#!/usr/bin/env python3
import json, os, sys
sys.path.insert(0, '/app')

from app.services.translator import (
    _classify_sentence, _LANG_TEMPLATES,
    _mask_protected_entities, _get_glossary, _build_role_sets,
    _extract_payment_method, _extract_time_context_token, _extract_time_context,
    _get_item_zone, _extract_template_items, _extract_noun_for_template,
    _extract_audience, _extract_recipient, _extract_deadline_token,
    _extract_start_date_token, _extract_amount_token, _build_from_template,
)

EVAL_DIR = '/app/external_model/translation_tts/eval_chunks'
SCORES_DIR = '/app/external_model/translation_tts/scores'

def get_path(ko_text, lang='vi'):
    lang_key = lang
    stype = _classify_sentence(ko_text) if lang_key in _LANG_TEMPLATES else 'info'
    if stype == 'info':
        return 'F', 'info'
    glossary = _get_glossary()
    _build_role_sets(glossary)
    masked, placeholders = _mask_protected_entities(ko_text, lang)
    method_str = None
    if stype == 'pay':
        method_str, masked = _extract_payment_method(masked, lang_key)
    tc, masked = _extract_time_context_token(masked, placeholders)
    if tc is None:
        tc, masked = _extract_time_context(masked, lang_key)
    item_zone = _get_item_zone(masked, stype)
    items = _extract_template_items(item_zone, glossary, lang_key)
    if not items:
        noun = _extract_noun_for_template(masked, stype)
        if noun:
            items = [(noun, noun)]
    if items:
        deadline = _extract_deadline_token(masked)
        start_date = _extract_start_date_token(masked) if stype == 'apply' else None
        amount = _extract_amount_token(masked) if stype == 'pay' else None
        result = _build_from_template(
            stype, items, lang_key,
            _extract_audience(ko_text, lang_key),
            _extract_recipient(ko_text, lang_key),
            deadline=deadline, amount=amount, method=method_str,
            time_context=tc, start_date=start_date,
        )
        if result:
            return 'T', stype
    return 'F', stype

def load_scores(path, lang_filter=None):
    result = {}
    try:
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if lang_filter and r.get('target_lang') != lang_filter:
                    continue
                result[r['eval_id']] = r['total_score']
    except FileNotFoundError:
        pass
    return result

# vi 기준으로 base_id → path/stype 결정
with open(f'{EVAL_DIR}/vi_multilingual_v1.json') as f:
    sentences = json.load(f)

path_map = {}  # base_id (e.g. 'T-001') → 'T'/'F'
stype_map = {}
for item in sentences:
    raw_id = item['id']                        # e.g. 'T-001_vi'
    base = raw_id.rsplit('_', 1)[0]            # e.g. 'T-001'
    path, stype = get_path(item['text_ko'], 'vi')
    path_map[base] = path
    stype_map[base] = stype

t_ids = sorted(b for b, p in path_map.items() if p == 'T')
f_ids = sorted(b for b, p in path_map.items() if p == 'F')
print(f"T path ({len(t_ids)}): {t_ids}")
print(f"F path ({len(f_ids)}): {f_ids}")

# 언어별 점수 수집: {lang: {eval_id_lang: score}}
langs = ['mn','th','ru','ms','zh','ja','vi','en']
lang_scores = {}
for lang in langs:
    sc = {}
    sc.update(load_scores(f'{SCORES_DIR}/scores_claude-sonnet-4-6_{lang}_multilingual_v1.jsonl'))
    sc.update(load_scores(f'{SCORES_DIR}/scores_gemini_{lang}_multilingual_v1.jsonl'))
    if lang in ('vi','en'):
        sc_gpt = load_scores(f'{SCORES_DIR}/scores_gpt-5.5-thinking_{lang}_multilingual_v1.jsonl')
        sc_cod = load_scores(f'{SCORES_DIR}/scores_gpt-5-codex_{lang}_multilingual_v1.jsonl')
    else:
        sc_gpt = load_scores(f'{SCORES_DIR}/scores_gpt-5.5-thinking_p11_all.jsonl', lang)
        sc_cod = load_scores(f'{SCORES_DIR}/scores_gpt-5-codex_multilingual_v1.jsonl', lang)
    sc.update(sc_gpt)
    sc.update(sc_cod)
    lang_scores[lang] = sc

# base_id + lang → 4평가자 평균 계산
def avg4(base, lang):
    eid = f'{base}_{lang}'
    ev_keys = ['claude', 'gemini', 'gpt55', 'codex']
    # 실제로는 같은 dict에 all evaluators merged
    sc = lang_scores[lang].get(eid)
    # But we merged all into one dict, so there might be key conflicts.
    # Let's just get all scores from the merged dict properly
    return lang_scores[lang].get(eid)

# Re-do properly: per-evaluator separate dicts
lang_ev_scores = {}
for lang in langs:
    d = {
        'claude': load_scores(f'{SCORES_DIR}/scores_claude-sonnet-4-6_{lang}_multilingual_v1.jsonl'),
        'gemini': load_scores(f'{SCORES_DIR}/scores_gemini_{lang}_multilingual_v1.jsonl'),
    }
    if lang in ('vi','en'):
        d['gpt55'] = load_scores(f'{SCORES_DIR}/scores_gpt-5.5-thinking_{lang}_multilingual_v1.jsonl')
        d['codex'] = load_scores(f'{SCORES_DIR}/scores_gpt-5-codex_{lang}_multilingual_v1.jsonl')
    else:
        d['gpt55'] = load_scores(f'{SCORES_DIR}/scores_gpt-5.5-thinking_p11_all.jsonl', lang)
        d['codex'] = load_scores(f'{SCORES_DIR}/scores_gpt-5-codex_multilingual_v1.jsonl', lang)
    lang_ev_scores[lang] = d

def get_avg(base, lang):
    eid = f'{base}_{lang}'
    vals = [lang_ev_scores[lang][ev].get(eid) for ev in ('claude','gemini','gpt55','codex')]
    vals = [v for v in vals if v is not None]
    return round(sum(vals)/len(vals), 1) if vals else None

# T/F 경로별 평균
print("\n=== T/F 경로별 평균 (4평가자) ===")
print(f"{'lang':5} | {'T path':8} | {'F path':8} | {'전체':6}")
print("-"*38)
for lang in langs:
    t_sc = [get_avg(b, lang) for b in t_ids]
    f_sc = [get_avg(b, lang) for b in f_ids]
    t_sc = [x for x in t_sc if x]
    f_sc = [x for x in f_sc if x]
    t_avg = round(sum(t_sc)/len(t_sc), 1) if t_sc else '-'
    f_avg = round(sum(f_sc)/len(f_sc), 1) if f_sc else '-'
    all_sc = t_sc + f_sc
    all_avg = round(sum(all_sc)/len(all_sc), 1) if all_sc else '-'
    print(f"{lang:5} | {str(t_avg):8} | {str(f_avg):8} | {str(all_avg):6}")

# 8개국 합산
all_t, all_f = [], []
for lang in langs:
    for b in t_ids:
        v = get_avg(b, lang)
        if v: all_t.append(v)
    for b in f_ids:
        v = get_avg(b, lang)
        if v: all_f.append(v)
print("-"*38)
print(f"{'평균':5} | {round(sum(all_t)/len(all_t),1):8} | {round(sum(all_f)/len(all_f),1):8} | {round((sum(all_t)+sum(all_f))/(len(all_t)+len(all_f)),1):6}")

# stype별
print("\n=== stype별 평균 (8개국) ===")
stype_scores = {}
for base, stype in stype_map.items():
    for lang in langs:
        v = get_avg(base, lang)
        if v:
            stype_scores.setdefault(stype, []).append(v)
for stype in ['submit','pay','prepare','apply','fill','info']:
    sc = stype_scores.get(stype, [])
    if sc:
        n = len(sc) // 8
        print(f"  {stype:8} ({'T' if stype!='info' else 'F':1}) | {n:2}문장 | {round(sum(sc)/len(sc),1):5}점")
