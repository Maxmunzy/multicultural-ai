"""
01_version_trend_improved.py
============================
버전별 F1 추이 (seen / unseen) — v4_merged seen 데이터 반영 개선판

실행: python gen_01_version_trend_improved.py  (model/extraction/file/ 에서)
출력: ../docs/img/A_01_version_trend.png
"""
import platform
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np

if platform.system() == 'Windows':
    matplotlib.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    matplotlib.rc('font', family='AppleGothic')
else:
    matplotlib.rc('font', family='NanumGothic')
matplotlib.rcParams['axes.unicode_minus'] = False

OUT = Path('..') / 'docs' / 'img'
OUT.mkdir(parents=True, exist_ok=True)

# ── 색상 ──────────────────────────────────────────────────────────────────────
C_SEEN   = '#3B67FF'   # 파란 (seen)
C_UNSEEN = '#F59E0B'   # 앰버 (unseen)
C_V4     = '#D62728'   # 빨간 (v4_merged 강조)
C_INK    = '#111827'
C_INK2   = '#374151'
C_INK3   = '#6B7280'
C_LINE   = '#E5E7EB'
C_SEEN_BG   = '#EFF6FF'
C_UNSEEN_BG = '#FFFBEB'

# ── 데이터 ────────────────────────────────────────────────────────────────────
LABELS = [
    'v2\n(갈산초\n5,475)',
    'v3\n(신규학교\n27,799)',
    'v3.1 Small\n(증강\n28,247)',
    'base-v1\n(v3.1.3\n22,523)',
    'v4_merged\n(재학습\n47,148)',
]

SEEN_F1   = [0.3905, 0.8225, 0.8223, 0.8397, 0.7380]
UNSEEN_F1 = [0.3905, 0.4184, 0.4168, 0.4166, 0.4687]

N = len(LABELS)
x = np.arange(N)

# ── 피겨 ──────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 6.5), facecolor='white')
ax.set_facecolor('white')

# ── 라인 ──────────────────────────────────────────────────────────────────────
ax.plot(x, SEEN_F1,   'o-', color=C_SEEN,   linewidth=2.5, markersize=9,
        label='Seen (val split · 5,650개)', zorder=4)
ax.plot(x, UNSEEN_F1, 's-', color=C_UNSEEN, linewidth=2.5, markersize=9,
        label='Unseen (galsan · 5,388개)', zorder=4)

# ── v4_merged 강조 점 ──────────────────────────────────────────────────────────
ax.scatter(N-1, SEEN_F1[-1],   s=260, color=C_V4, zorder=6,
           edgecolors='white', linewidth=2.5)
ax.scatter(N-1, UNSEEN_F1[-1], s=260, color=C_V4, zorder=6,
           edgecolors='white', linewidth=2.5)

# ── 수치 레이블 ───────────────────────────────────────────────────────────────
for i, (s, u) in enumerate(zip(SEEN_F1, UNSEEN_F1)):
    is_v4 = (i == N - 1)
    # seen 수치
    ax.text(i, s + 0.025, f'{s:.4f}',
            ha='center', va='bottom',
            fontsize=10.5 if is_v4 else 9.5,
            color=C_V4 if is_v4 else C_SEEN,
            fontweight='bold' if is_v4 else 'normal')
    # unseen 수치
    ax.text(i, u - 0.032, f'{u:.4f}',
            ha='center', va='top',
            fontsize=10.5 if is_v4 else 9.5,
            color=C_V4 if is_v4 else C_UNSEEN,
            fontweight='bold' if is_v4 else 'normal')

# ── v4_merged 세로 구분선 ─────────────────────────────────────────────────────
ax.axvline(N - 1, color=C_LINE, linewidth=1.5, linestyle='--', zorder=1)

# ── seen 하락 설명 박스 ───────────────────────────────────────────────────────
ax.annotate(
    'seen ↓  —  val split이 base-v1\n학습 데이터와 도메인 일부 겹침',
    xy=(N-1, SEEN_F1[-1]),
    xytext=(N-1 - 0.55, SEEN_F1[-1] - 0.17),
    fontsize=9, color=C_SEEN,
    ha='center', va='top',
    arrowprops=dict(arrowstyle='->', color=C_SEEN, lw=1.3,
                    connectionstyle='arc3,rad=0.25'),
    bbox=dict(boxstyle='round,pad=0.4', facecolor=C_SEEN_BG,
              edgecolor=C_SEEN, linewidth=1, alpha=0.95),
)

# ── unseen 상승 설명 박스 ─────────────────────────────────────────────────────
ax.annotate(
    'unseen ↑  —  새 학교 통신문에서\n실전 일반화 성능 향상 ★',
    xy=(N-1, UNSEEN_F1[-1]),
    xytext=(N-1 - 1.1, UNSEEN_F1[-1] - 0.07),
    fontsize=9, color='#92400E',
    ha='center', va='top',
    arrowprops=dict(arrowstyle='->', color=C_UNSEEN, lw=1.3,
                    connectionstyle='arc3,rad=0.2'),
    bbox=dict(boxstyle='round,pad=0.4', facecolor=C_UNSEEN_BG,
              edgecolor=C_UNSEEN, linewidth=1, alpha=0.92),
)

# ── 핵심 메시지 박스 (우상단) ─────────────────────────────────────────────────
msg = (
    '실전 기준(unseen)은 v4_merged가 우수\n'
    'Recall  0.7556 → 0.8680  (+11.2%p)\n'
    'F1        0.4166 → 0.4687  (+0.0521)'
)
ax.text(0.985, 0.97, msg,
        transform=ax.transAxes,
        ha='right', va='top',
        fontsize=9.5, color='#1E3A5F',
        linespacing=1.7,
        bbox=dict(boxstyle='round,pad=0.55', facecolor='#EFF6FF',
                  edgecolor='#3B67FF', linewidth=1.3))

# ── 축 설정 ───────────────────────────────────────────────────────────────────
ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=9.5)
ax.set_ylim(0.28, 0.98)
ax.set_ylabel('F1 (할 일 클래스)', fontsize=12, color=C_INK2)
ax.spines[['top', 'right']].set_visible(False)
ax.spines[['left', 'bottom']].set_color(C_LINE)
ax.tick_params(colors=C_INK3)
ax.grid(axis='y', alpha=0.35, color=C_LINE)
ax.axhline(0.8, color=C_LINE, linestyle=':', linewidth=1)
ax.text(0.01, 0.808, 'F1 = 0.80', color=C_INK3, fontsize=8.5,
        transform=ax.get_yaxis_transform())

# ── 범례 ─────────────────────────────────────────────────────────────────────
legend_handles = [
    Line2D([0],[0], marker='o', color='w', markerfacecolor=C_SEEN,
           markersize=10, linestyle='-', linewidth=2,
           label='Seen  (val split · 5,650개)'),
    Line2D([0],[0], marker='s', color='w', markerfacecolor=C_UNSEEN,
           markersize=10, linestyle='-', linewidth=2,
           label='Unseen  (galsan · 5,388개)  ← 실전 기준'),
]
ax.legend(handles=legend_handles, fontsize=10.5,
          loc='lower center', bbox_to_anchor=(0.38, -0.18), ncol=2,
          frameon=True, framealpha=0.97, edgecolor=C_LINE)

# ── 제목 ──────────────────────────────────────────────────────────────────────
fig.text(0.02, 0.97,
         '모델 버전별 F1 추이 — Seen vs Unseen',
         ha='left', va='top', fontsize=16, fontweight='bold', color=C_INK)
fig.text(0.02, 0.90,
         'v4_merged: seen F1 소폭 하락 / unseen F1 상승 — 실전 일반화 성능이 핵심',
         ha='left', va='top', fontsize=10, color=C_INK3)
fig.add_artist(
    plt.Line2D([0.02, 0.98], [0.995, 0.995],
               color=C_SEEN, linewidth=3, transform=fig.transFigure,
               solid_capstyle='round')
)

# ── 저장 ─────────────────────────────────────────────────────────────────────
plt.tight_layout(rect=[0, 0.07, 1, 0.88])
out = OUT / 'A_01_version_trend.png'
plt.savefig(out, dpi=180, bbox_inches='tight', facecolor='white')
print(f'저장 완료: {out.resolve()}')
plt.show()
