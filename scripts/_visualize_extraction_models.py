"""추출 모델 성능 비교 시각화 — 7개 그래프 생성"""
import sys, platform
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
sys.stdout.reconfigure(encoding="utf-8")

# ── 한글 폰트 ────────────────────────────────────────────────────────────────
if platform.system() == 'Windows':
    matplotlib.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    matplotlib.rc('font', family='AppleGothic')
else:
    matplotlib.rc('font', family='NanumGothic')
matplotlib.rcParams['axes.unicode_minus'] = False

OUT = Path(r"c:\AI-human4\P1\multicultural-ai\model\extraction\docs\img")
OUT.mkdir(parents=True, exist_ok=True)
print(f"출력 폴더: {OUT}")

C = {
    'v2': '#9ecae1', 'v3': '#4292c6', 'v3.1': '#2171b5',
    'base': '#e6550d', 'seen': '#74c476', 'unseen': '#fd8d3c', 'gray': '#969696',
}

MODELS = {
    'v2\n(갈산초\n5,475)': {
        'train_size': 5475, 'threshold': 0.50,
        'seen':   {'acc': 0.7682, 'f1': 0.3905, 'prec': 0.7362, 'rec': 0.2658},
        'unseen': {'acc': 0.6873, 'f1': 0.3905, 'prec': 0.7362, 'rec': 0.2658},
        'color': C['v2'],
    },
    'v3\n(신규학교\n27,799)': {
        'train_size': 27799, 'threshold': 0.65,
        'seen':   {'acc': 0.8958, 'f1': 0.8225, 'prec': 0.8149, 'rec': 0.8303},
        'unseen': {'acc': 0.7069, 'f1': 0.4184, 'prec': 0.2836, 'rec': 0.7978},
        'color': C['v3'],
    },
    'v3.1 Small\n(증강\n28,247)': {
        'train_size': 28247, 'threshold': 0.55,
        'seen':   {'acc': 0.8940, 'f1': 0.8223, 'prec': 0.8025, 'rec': 0.8431},
        'unseen': {'acc': 0.6873, 'f1': 0.4168, 'prec': 0.2765, 'rec': 0.8455},
        'color': C['v3.1'],
    },
    'Base\n(소프트라벨\n22,523)': {
        'train_size': 22523, 'threshold': 0.40,
        'seen':   {'acc': 0.9069, 'f1': 0.8387, 'prec': 0.8459, 'rec': 0.8315},
        'unseen': {'acc': 0.7188, 'f1': 0.4157, 'prec': 0.2865, 'rec': 0.7570},
        'color': C['base'],
    },
}
model_keys = list(MODELS.keys())

THR_DATA = {
    'thr':  [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70],
    'f1':   [0.8393, 0.8388, 0.8387, 0.8375, 0.8362, 0.8354, 0.8347],
    'prec': [0.8447, 0.8451, 0.8459, 0.8461, 0.8466, 0.8469, 0.8467],
    'rec':  [0.8339, 0.8327, 0.8315, 0.8291, 0.8260, 0.8242, 0.8230],
}

DATA_VERSIONS = {
    'v2.1\n(갈산초)':       {'size': 5475,  'true_ratio': 0.220},
    'v3\n(신규학교)':        {'size': 27799, 'true_ratio': 0.291},
    'v3.1\n(증강)':         {'size': 28247, 'true_ratio': 0.291},
    'v3.1.3\n(B그룹 제외)': {'size': 22523, 'true_ratio': 0.162},
    'v4_merged\n(재학습용)': {'size': 47148, 'true_ratio': 0.262},
}


# ── 그래프 1: 버전별 F1 추이 ───────────────────────────────────────────────
print("[1/7] 버전별 F1 추이...")
seen_f1s   = [MODELS[k]['seen']['f1']   for k in model_keys]
unseen_f1s = [MODELS[k]['unseen']['f1'] for k in model_keys]
x = np.arange(len(model_keys))

fig, ax = plt.subplots(figsize=(11, 6))
ax.plot(x, seen_f1s,   'o-', color=C['seen'],   linewidth=2.5, markersize=9, label='Seen (val split, 5,650개)')
ax.plot(x, unseen_f1s, 's--', color=C['unseen'], linewidth=2.5, markersize=9, label='Unseen (galsan, 5,388개)')
for i, (s, u) in enumerate(zip(seen_f1s, unseen_f1s)):
    ax.annotate(f'{s:.4f}', (i, s), textcoords='offset points', xytext=(0, 10),
                ha='center', fontsize=10, color='#2ca25f', fontweight='bold')
    ax.annotate(f'{u:.4f}', (i, u), textcoords='offset points', xytext=(0, -18),
                ha='center', fontsize=10, color='#d94801')
last = len(model_keys) - 1
drop = seen_f1s[last] - unseen_f1s[last]
ax.annotate('', xy=(last, unseen_f1s[last]+0.01), xytext=(last, seen_f1s[last]-0.01),
            arrowprops=dict(arrowstyle='<->', color='#999', lw=1.5))
ax.text(last+0.12, (seen_f1s[last]+unseen_f1s[last])/2, f'Gap\n{drop:.3f}',
        fontsize=9, color='#666', va='center')
ax.set_xticks(x); ax.set_xticklabels(model_keys, fontsize=10)
ax.set_ylim(0.3, 1.0); ax.set_ylabel('F1 (할 일 클래스)', fontsize=12)
ax.set_title('모델 버전별 F1 추이 — Seen vs Unseen\n(파인튜닝 효과는 seen에서 크고, unseen 일반화가 핵심 과제)', fontsize=13)
ax.legend(fontsize=11, loc='lower right')
ax.axhline(0.8, color='gray', linestyle=':', alpha=0.5, linewidth=1)
ax.text(3.35, 0.805, 'F1=0.80', color='gray', fontsize=9)
ax.grid(axis='y', alpha=0.3); ax.spines[['top','right']].set_visible(False)
plt.tight_layout(); plt.savefig(OUT/'01_version_trend.png', dpi=150, bbox_inches='tight'); plt.close()


# ── 그래프 2: Accuracy/Precision/Recall/F1 종합 막대 ──────────────────────
print("[2/7] 지표 종합 막대...")
compare_models = {
    'v3\nSmall':   MODELS['v3\n(신규학교\n27,799)'],
    'v3.1\nSmall': MODELS['v3.1 Small\n(증강\n28,247)'],
    'Base':        MODELS['Base\n(소프트라벨\n22,523)'],
}
metrics = ['acc','prec','rec','f1']; metric_labels = ['Accuracy','Precision','Recall','F1']
m_colors = ['#8dd3c7','#ffffb3','#bebada','#fb8072']
x = np.arange(len(compare_models)); w = 0.18
offsets = [-1.5*w, -0.5*w, 0.5*w, 1.5*w]

fig, ax = plt.subplots(figsize=(10, 6))
for i, (metric, label, color) in enumerate(zip(metrics, metric_labels, m_colors)):
    vals = [m['seen'][metric] for m in compare_models.values()]
    bars = ax.bar(x+offsets[i], vals, w, label=label, color=color, edgecolor='white', linewidth=0.8)
    for bar, val in zip(bars, vals):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.004,
                f'{val:.3f}', ha='center', va='bottom', fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(list(compare_models.keys()), fontsize=12)
ax.set_ylim(0.75, 1.0); ax.set_ylabel('Score (seen val split)', fontsize=12)
ax.set_title('모델별 Accuracy / Precision / Recall / F1 비교\n(seen: v3.1_val_split 5,650개)', fontsize=13)
ax.legend(fontsize=10, loc='lower right')
ax.axhline(0.8, color='gray', linestyle=':', alpha=0.4)
ax.grid(axis='y', alpha=0.3); ax.spines[['top','right']].set_visible(False)
plt.tight_layout(); plt.savefig(OUT/'02_metric_bar.png', dpi=150, bbox_inches='tight'); plt.close()


# ── 그래프 3: Precision-Recall 트레이드오프 ───────────────────────────────
print("[3/7] Precision-Recall 트레이드오프...")
fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
for ax, split_key, title_suffix in [
    (axes[0], 'seen',   'Seen (val split)'),
    (axes[1], 'unseen', 'Unseen (galsan)'),
]:
    for name, data in MODELS.items():
        p = data[split_key]['prec']; r = data[split_key]['rec']; f = data[split_key]['f1']
        short = name.split('\n')[0]
        ax.scatter(r, p, s=200, color=data['color'], zorder=5, edgecolors='white', linewidth=1.5)
        ax.annotate(f'{short}\nF1={f:.3f}', (r, p), textcoords='offset points',
                    xytext=(8, 5), fontsize=9, color=data['color'], fontweight='bold')
    r_range = np.linspace(0.01, 1.0, 200)
    for f1_val, ls in [(0.5,':'), (0.6,'--'), (0.7,'-.'), (0.8,'-')]:
        denom = 2*r_range - f1_val
        with np.errstate(divide='ignore', invalid='ignore'):
            p_range = np.where(denom > 0, f1_val*r_range/denom, np.nan)
        mask = (~np.isnan(p_range)) & (p_range > 0) & (p_range <= 1)
        ax.plot(r_range[mask], p_range[mask], ls, color='lightgray', linewidth=0.8, alpha=0.7)
        idx = np.where(mask)[0]
        if len(idx) > 10:
            ax.text(r_range[idx[-8]], p_range[idx[-8]], f'F1={f1_val}', fontsize=7, color='#aaa', va='center')
    ax.set_xlim(0.1, 1.05); ax.set_ylim(0.1, 1.05)
    ax.set_xlabel('Recall (할 일 탐지율)', fontsize=11); ax.set_ylabel('Precision (오탐 없는 비율)', fontsize=11)
    ax.set_title(f'Precision-Recall 트레이드오프\n({title_suffix})', fontsize=12)
    ax.grid(alpha=0.2); ax.spines[['top','right']].set_visible(False)
    ax.text(0.13, 0.97, '← Recall↑: 놓치는 할 일 ↓\n   Precision↓: 노이즈 포함 ↑',
            fontsize=8, color='#555', va='top',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.7))
plt.suptitle('모델별 Precision-Recall 트레이드오프', fontsize=14, y=1.01)
plt.tight_layout(); plt.savefig(OUT/'03_precision_recall_tradeoff.png', dpi=150, bbox_inches='tight'); plt.close()


# ── 그래프 4: Seen→Unseen 성능 하락 ───────────────────────────────────────
print("[4/7] Seen→Unseen 하락...")
target_keys  = ['v3\n(신규학교\n27,799)', 'v3.1 Small\n(증강\n28,247)', 'Base\n(소프트라벨\n22,523)']
short_labels = ['v3 Small', 'v3.1 Small', 'Base']
colors_t     = [C['v3'], C['v3.1'], C['base']]
seen_f1_t    = [MODELS[k]['seen']['f1']   for k in target_keys]
unseen_f1_t  = [MODELS[k]['unseen']['f1'] for k in target_keys]
drops        = [s - u for s, u in zip(seen_f1_t, unseen_f1_t)]
x = np.arange(len(target_keys)); w = 0.3

fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={'width_ratios': [2, 1]})
ax = axes[0]
bars1 = ax.bar(x-w/2, seen_f1_t,   w, label='Seen (val split)', color=C['seen'],   edgecolor='white')
bars2 = ax.bar(x+w/2, unseen_f1_t, w, label='Unseen (galsan)', color=C['unseen'], edgecolor='white')
for bar, val in zip(bars1, seen_f1_t):
    ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.005, f'{val:.4f}',
            ha='center', va='bottom', fontsize=10, fontweight='bold')
for bar, val in zip(bars2, unseen_f1_t):
    ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.005, f'{val:.4f}',
            ha='center', va='bottom', fontsize=10)
ax.set_xticks(x); ax.set_xticklabels(short_labels, fontsize=12)
ax.set_ylim(0.35, 0.96); ax.set_ylabel('F1 (할 일)', fontsize=12)
ax.set_title('Seen vs Unseen F1 비교', fontsize=12)
ax.legend(fontsize=10); ax.grid(axis='y', alpha=0.3); ax.spines[['top','right']].set_visible(False)

ax2 = axes[1]
drop_bars = ax2.bar(x, drops, color=colors_t, edgecolor='white', width=0.5)
for bar, d in zip(drop_bars, drops):
    ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.003, f'{d:.4f}',
             ha='center', va='bottom', fontsize=11, fontweight='bold')
ax2.set_xticks(x); ax2.set_xticklabels(short_labels, fontsize=12)
ax2.set_ylim(0, 0.55); ax2.set_ylabel('F1 하락폭 (seen - unseen)', fontsize=11)
ax2.set_title('일반화 격차\n(낮을수록 좋음)', fontsize=12)
ax2.grid(axis='y', alpha=0.3); ax2.spines[['top','right']].set_visible(False)
best_idx = int(np.argmin(drops))
ax2.annotate('최소 격차', xy=(best_idx, drops[best_idx]),
             xytext=(best_idx+0.35, drops[best_idx]+0.06),
             arrowprops=dict(arrowstyle='->', color='green'),
             fontsize=10, color='green', fontweight='bold')
plt.suptitle('Seen → Unseen 성능 하락 비교 (일반화 능력)', fontsize=14, y=1.01)
plt.tight_layout(); plt.savefig(OUT/'04_seen_vs_unseen_drop.png', dpi=150, bbox_inches='tight'); plt.close()


# ── 그래프 5: 레이더 차트 ─────────────────────────────────────────────────
print("[5/7] 레이더 차트...")
radar_metrics = ['Accuracy', 'F1', 'Precision', 'Recall']
n = len(radar_metrics)
angles = np.linspace(0, 2*np.pi, n, endpoint=False).tolist() + [0]

def get_vals(model_key, split):
    return [MODELS[model_key][split][k] for k in ['acc','f1','prec','rec']]

fig, axes = plt.subplots(1, 2, figsize=(13, 6), subplot_kw=dict(polar=True))
for ax, pairs, title in [
    (axes[0], [('v3.1 Small\n(증강\n28,247)', 'seen', C['v3.1'], 'v3.1 Small'),
               ('Base\n(소프트라벨\n22,523)',   'seen', C['base'],  'Base')], 'Seen (val split)'),
    (axes[1], [('v3.1 Small\n(증강\n28,247)', 'unseen', C['v3.1'], 'v3.1 Small'),
               ('Base\n(소프트라벨\n22,523)',   'unseen', C['base'],  'Base')], 'Unseen (galsan)'),
]:
    for model_key, split, color, label in pairs:
        vals = get_vals(model_key, split)
        plot_vals = vals + vals[:1]
        ax.plot(angles, plot_vals, 'o-', linewidth=2, color=color,
                label=f'{label} (F1={vals[1]:.4f})')
        ax.fill(angles, plot_vals, alpha=0.12, color=color)
    ax.set_xticks(angles[:-1]); ax.set_xticklabels(radar_metrics, fontsize=12)
    ax.set_ylim(0, 1); ax.set_yticks([0.2,0.4,0.6,0.8,1.0])
    ax.set_yticklabels(['0.2','0.4','0.6','0.8','1.0'], fontsize=8)
    ax.set_title(title, fontsize=12, pad=18)
    ax.legend(loc='upper right', bbox_to_anchor=(1.4, 1.15), fontsize=10)
    ax.grid(color='gray', alpha=0.3)
plt.suptitle('v3.1 Small vs Base — 4개 지표 레이더 차트', fontsize=14, y=1.02)
plt.tight_layout(); plt.savefig(OUT/'05_radar.png', dpi=150, bbox_inches='tight'); plt.close()


# ── 그래프 6: Threshold 탐색 커브 ─────────────────────────────────────────
print("[6/7] Threshold 커브...")
fig, ax = plt.subplots(figsize=(9, 5))
ax.plot(THR_DATA['thr'], THR_DATA['f1'],   'o-', color='#e6550d', linewidth=2.5, markersize=8, label='F1', zorder=5)
ax.plot(THR_DATA['thr'], THR_DATA['prec'], 's--', color='#3182bd', linewidth=2,   markersize=7, label='Precision')
ax.plot(THR_DATA['thr'], THR_DATA['rec'],  '^-.', color='#31a354', linewidth=2,   markersize=7, label='Recall')
best_thr = THR_DATA['thr'][int(np.argmax(THR_DATA['f1']))]
best_f1  = max(THR_DATA['f1'])
ax.axvline(best_thr, color='#e6550d', linestyle=':', alpha=0.7, linewidth=1.5)
ax.annotate(f'최적 threshold={best_thr}\nF1={best_f1:.4f}',
            xy=(best_thr, best_f1), xytext=(best_thr+0.03, best_f1-0.004),
            arrowprops=dict(arrowstyle='->', color='#e6550d', lw=1.5),
            fontsize=10, color='#e6550d', fontweight='bold')
for thr, f1_val in zip(THR_DATA['thr'], THR_DATA['f1']):
    ax.text(thr, f1_val+0.0005, f'{f1_val:.4f}', ha='center', va='bottom', fontsize=8, color='#e6550d')
ax.set_xlabel('Threshold', fontsize=12); ax.set_ylabel('Score', fontsize=12)
ax.set_ylim(0.815, 0.860); ax.set_xticks(THR_DATA['thr'])
ax.set_title('Base 모델 Threshold 탐색\n(곡선이 평탄 — 모델이 양 끝으로 명확히 분리하는 증거)', fontsize=13)
ax.legend(fontsize=11); ax.grid(alpha=0.3); ax.spines[['top','right']].set_visible(False)
plt.tight_layout(); plt.savefig(OUT/'06_threshold_curve.png', dpi=150, bbox_inches='tight'); plt.close()


# ── 그래프 7: 학습 데이터 버전별 True 비율 ─────────────────────────────────
print("[7/7] 데이터 True 비율...")
dv_keys   = list(DATA_VERSIONS.keys())
dv_sizes  = [DATA_VERSIONS[k]['size']       for k in dv_keys]
dv_ratios = [DATA_VERSIONS[k]['true_ratio'] for k in dv_keys]
dv_colors = [C['v3'], C['v3'], C['v3.1'], C['base'], C['unseen']]
x = np.arange(len(dv_keys))

fig, ax1 = plt.subplots(figsize=(11, 5.5))
ax2 = ax1.twinx()
bars = ax1.bar(x, dv_sizes, color=dv_colors, alpha=0.35, edgecolor='white', width=0.5)
line, = ax2.plot(x, [r*100 for r in dv_ratios], 'o-', color='#e6550d',
                 linewidth=2.5, markersize=9, label='True 비율 (%)', zorder=5)
for i, (size, ratio) in enumerate(zip(dv_sizes, dv_ratios)):
    ax1.text(i, size+400, f'{size:,}', ha='center', va='bottom', fontsize=9, color='#444')
    ax2.text(i, ratio*100+0.8, f'{ratio*100:.1f}%', ha='center', va='bottom',
             fontsize=10, color='#e6550d', fontweight='bold')
ax1.set_xticks(x); ax1.set_xticklabels(dv_keys, fontsize=10)
ax1.set_ylabel('학습 데이터 총 문장 수', fontsize=12, color='#555')
ax2.set_ylabel('is_todo=True 비율 (%)', fontsize=12, color='#e6550d')
ax2.tick_params(axis='y', colors='#e6550d')
ax2.set_ylim(0, 40); ax1.set_ylim(0, 58000)
ax1.set_title('학습 데이터 버전별 크기 및 True 비율 변화\n(v4_merged: True 비율 의도적 상향 — recall 보정 목적)', fontsize=13)
bar_patch = mpatches.Patch(color='#9ecae1', alpha=0.5, label='데이터 크기 (막대)')
ax1.legend(handles=[bar_patch, line], fontsize=10, loc='upper left')
ax1.grid(axis='y', alpha=0.2); ax1.spines[['top','right']].set_visible(False)
ax2.spines[['top']].set_visible(False)
plt.tight_layout(); plt.savefig(OUT/'07_data_true_ratio.png', dpi=150, bbox_inches='tight'); plt.close()

print("\n완료!")
for p in sorted(OUT.glob('*.png')):
    print(f"  {p.name}")
