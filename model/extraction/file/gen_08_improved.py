"""
08_key_result_v4_improvement.png — 개선판
PPT용 핵심 그래프: base-v1 → v4_merged 성능 향상

실행: python gen_08_improved.py  (model/extraction/file/ 에서)
출력: ../docs/img/A_08_key_result_v4_improved.png
"""
import platform
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np

# ── 한글 폰트 ─────────────────────────────────────────────────────────────────
if platform.system() == 'Windows':
    matplotlib.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    matplotlib.rc('font', family='AppleGothic')
else:
    matplotlib.rc('font', family='NanumGothic')
matplotlib.rcParams['axes.unicode_minus'] = False

OUT = Path('..') / 'docs' / 'img'
OUT.mkdir(parents=True, exist_ok=True)

# ── 프로젝트 블루 팔레트 ──────────────────────────────────────────────────────
C_V1    = '#9CA3AF'   # base-v1: medium gray
C_V4    = '#3B67FF'   # v4_merged: primary blue
C_HERO  = '#22C55E'   # success green (핵심 지표 강조)
C_INK   = '#111827'
C_INK2  = '#374151'
C_INK3  = '#6B7280'
C_LINE  = '#E5E7EB'
C_BLUE_LT = '#DBEAFE'  # light blue track for hero
C_GRAY_LT = '#F3F4F6'  # light gray track

# ── 데이터 ────────────────────────────────────────────────────────────────────
V1 = {'Accuracy': 0.7203, 'F1': 0.4166, 'Precision': 0.2875, 'Recall': 0.7556}
V4 = {'Accuracy': 0.7400, 'F1': 0.4687, 'Precision': 0.3210, 'Recall': 0.8680}
DELTAS = {k: V4[k] - V1[k] for k in V1}

# 표시 순서: Recall 맨 위(영향 크고 PPT 핵심)
METRICS = ['Recall', 'F1', 'Precision', 'Accuracy']
Y = np.arange(len(METRICS))

# ── 피겨 설정 ─────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 6.5), facecolor='white')
gs = fig.add_gridspec(
    1, 2,
    width_ratios=[3.0, 1.0],
    wspace=0.06,
    left=0.17, right=0.97,
    top=0.84, bottom=0.14,
)
ax   = fig.add_subplot(gs[0])   # 덤벨 차트
ax_r = fig.add_subplot(gs[1])   # 향상 폭 + 요약 카드

ax.set_facecolor('white')
ax_r.set_facecolor('white')

# ── 덤벨 차트 ─────────────────────────────────────────────────────────────────
for yi, metric in zip(Y, METRICS):
    v1, v4 = V1[metric], V4[metric]
    is_hero = (metric == 'Recall')

    # 연결 트랙
    ax.plot([v1, v4], [yi, yi],
            color=C_BLUE_LT if is_hero else C_GRAY_LT,
            linewidth=16 if is_hero else 11,
            solid_capstyle='round', zorder=1)

    # before 점 (회색)
    ax.scatter(v1, yi, s=360 if is_hero else 280,
               color=C_V1, zorder=5, edgecolors='white', linewidth=2.5)
    # after 점 (파란)
    ax.scatter(v4, yi, s=360 if is_hero else 280,
               color=C_V4, zorder=5, edgecolors='white', linewidth=2.5)

    # 수치 레이블
    lbl_fs = 12.5 if is_hero else 11
    ax.text(v1 - 0.024, yi, f'{v1:.4f}',
            ha='right', va='center', fontsize=lbl_fs,
            color=C_V1, fontweight='bold' if is_hero else 'normal')
    ax.text(v4 + 0.024, yi, f'{v4:.4f}',
            ha='left', va='center', fontsize=lbl_fs,
            color=C_V4, fontweight='bold')

    # 향상 뱃지 (트랙 위)
    delta = DELTAS[metric]
    badge_fc = '#DCFCE7' if is_hero else '#F0FDF4'
    badge_ec = '#22C55E' if is_hero else '#BBF7D0'
    badge_fs = 11.5 if is_hero else 9.5
    ax.text((v1 + v4) / 2, yi + (0.065 if is_hero else 0.055),
            f'+{delta:.4f}',
            ha='center', va='bottom', fontsize=badge_fs, fontweight='bold',
            color='#15803D',
            bbox=dict(boxstyle='round,pad=0.32',
                      facecolor=badge_fc, edgecolor=badge_ec, linewidth=1.3))

    # 메트릭 이름 (y축 대신)
    m_label = f'★ {metric}' if is_hero else metric
    ax.text(-0.005, yi, m_label,
            ha='right', va='center',
            fontsize=14 if is_hero else 12,
            color=C_INK if is_hero else C_INK2,
            fontweight='bold' if is_hero else 'normal',
            transform=ax.get_yaxis_transform())

ax.set_yticks([])
ax.set_xlim(0.14, 1.04)
ax.set_ylim(-0.6, len(METRICS) - 0.35)
ax.set_xlabel('Score  (galsan unseen · 5,388문장)', fontsize=11, color=C_INK2, labelpad=8)
ax.spines[['top', 'right', 'left']].set_visible(False)
ax.spines['bottom'].set_color(C_LINE)
ax.tick_params(axis='x', colors=C_INK3, labelsize=10)
ax.xaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter('%.2f'))
ax.grid(axis='x', alpha=0.35, color=C_LINE)

# 범례
legend_handles = [
    Line2D([0],[0], marker='o', color='w', markerfacecolor=C_V1,
           markersize=12, label='base-v1  (v3.1.3 · 22,523행)'),
    Line2D([0],[0], marker='o', color='w', markerfacecolor=C_V4,
           markersize=12, label='v4_merged  (재학습 · 47,148행)'),
]
ax.legend(handles=legend_handles, fontsize=10.5,
          loc='upper center', bbox_to_anchor=(0.5, -0.13), ncol=2,
          frameon=True, framealpha=0.97, edgecolor=C_LINE,
          borderpad=0.8, handletextpad=0.5)

# ── 오른쪽 패널: 향상 폭 막대 + 요약 카드 ─────────────────────────────────────
delta_vals  = [DELTAS[m] for m in METRICS]
bar_colors  = [C_V4 if m == 'Recall' else C_BLUE_LT for m in METRICS]
text_colors = [C_V4 if m == 'Recall' else C_INK3 for m in METRICS]

bars = ax_r.barh(Y, delta_vals, height=0.42,
                 color=bar_colors, edgecolor='white', linewidth=1)
for bar, val, tc, m in zip(bars, delta_vals, text_colors, METRICS):
    ax_r.text(val + 0.0018, bar.get_y() + bar.get_height() / 2,
              f'+{val:.4f}',
              va='center', ha='left',
              fontsize=11 if m == 'Recall' else 9.5,
              fontweight='bold' if m == 'Recall' else 'normal',
              color=tc)

ax_r.set_yticks([])
ax_r.set_xlim(-0.002, 0.155)
ax_r.set_ylim(-0.6, len(METRICS) - 0.35)
ax_r.set_xlabel('향상 폭 (Δ)', fontsize=10, color=C_INK2, labelpad=8)
ax_r.spines[['top', 'right', 'left']].set_visible(False)
ax_r.spines['bottom'].set_color(C_LINE)
ax_r.tick_params(axis='x', colors=C_INK3, labelsize=8)
ax_r.grid(axis='x', alpha=0.3, color=C_LINE)

# ── 상단: 핵심 콜아웃 텍스트 ─────────────────────────────────────────────────
# 오른쪽 패널 위에 "Recall +11.2%p" 강조 텍스트
recall_delta_pct = DELTAS['Recall'] * 100  # 11.24
ax_r.text(0.5, 1.22,
          f'Recall  +{recall_delta_pct:.1f}%p',
          ha='center', va='bottom',
          fontsize=15, fontweight='bold', color=C_V4,
          transform=ax_r.transAxes)
ax_r.text(0.5, 1.09,
          '놓치는 할 일 대폭 감소',
          ha='center', va='bottom',
          fontsize=10, color=C_INK3,
          transform=ax_r.transAxes)

# ── 전체 제목 ─────────────────────────────────────────────────────────────────
fig.text(0.02, 0.97,
         'v4_merged 재학습 효과 — 4개 지표 전부 향상',
         ha='left', va='top',
         fontsize=17, fontweight='bold', color=C_INK)
fig.text(0.02, 0.90,
         f'테스트셋: galsan unseen  ·  5,388문장  ·  할 일:노이즈 = 1 : 6.6  ·  Recall 중심 평가',
         ha='left', va='top',
         fontsize=10, color=C_INK3)

# 상단 강조선
fig.add_artist(
    plt.Line2D([0.02, 0.98], [0.995, 0.995],
               color=C_V4, linewidth=3, transform=fig.transFigure,
               solid_capstyle='round')
)

# ── 저장 ─────────────────────────────────────────────────────────────────────
out = OUT / 'A_08_key_result_v4_improvement.png'
plt.savefig(out, dpi=180, bbox_inches='tight', facecolor='white')
print(f'저장 완료: {out.resolve()}')
plt.show()
