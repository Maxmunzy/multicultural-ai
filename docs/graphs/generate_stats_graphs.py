"""SchoolBridge 5/13 발표용 통계 그래프 7종 일괄 생성.

데이터 소스:
- KOSIS 국적별 혼인 (2014~2025) — 한국인 남편 × 외국인 아내
- KESS 연도별 다문화 학생수 (2012~2025) — 초등학교 한정
- KESS 부모 국적별 다문화 학생수 (2025 초등 기준)
- KESS 행정구역별 다문화(유형별) 학생수 (2025 초등 기준)
- 여가부 2024 전국 다문화가족 실태조사 (한국어 능력 4영역)

출력: docs/graphs/*.png (PPT 직접 삽입용, 1600x900px 기준)
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams


# ── 한글 폰트 설정 (Windows Malgun Gothic) ───────────────────────────
def _setup_korean_font() -> str:
    candidates = ["Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            rcParams["font.family"] = name
            rcParams["axes.unicode_minus"] = False
            return name
    print("⚠️  한글 폰트 못 찾음 — 한글 깨질 수 있음")
    return "default"


_FONT = _setup_korean_font()
print(f"[font] using: {_FONT}")

OUT = Path(__file__).parent
OUT.mkdir(exist_ok=True)

# 색 — 차분한 톤 + SchoolBridge 강조색
PRIMARY = "#2B6CB0"     # blue
ACCENT  = "#E55A45"     # red (강조)
WARM    = "#D4A017"     # gold
MUTED   = "#A8B5C2"     # gray-blue
GREEN   = "#3FA86E"


def save(fig, name: str, source: str = ""):
    """그래프 저장. source 있으면 우하단에 출처 텍스트 자동 삽입."""
    if source:
        fig.text(0.99, 0.005, f"출처: {source}",
                 ha="right", va="bottom", fontsize=8,
                 color="#888", style="italic")
    path = OUT / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [OK] {path.name}")


# ── 1. 국제결혼 연도별 추이 (2014~2025) ─────────────────────────────
def chart_marriage_trend():
    years = [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
    counts = [16152, 14677, 14822, 14869, 16608, 17687, 11100, 8985, 12007, 14710, 15624, 15610]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(years, counts, marker="o", linewidth=2.5, color=PRIMARY, markersize=7)
    ax.fill_between(years, counts, alpha=0.10, color=PRIMARY)
    # 코로나 변곡점 강조
    ax.scatter([2020, 2021], [11100, 8985], s=120, color=ACCENT, zorder=5)
    ax.annotate("코로나 급감\n(-49%)", xy=(2021, 8985), xytext=(2021.5, 5500),
                fontsize=10, color=ACCENT,
                arrowprops=dict(arrowstyle="->", color=ACCENT))
    ax.annotate("회복", xy=(2024, 15624), xytext=(2022.7, 19000),
                fontsize=10, color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.set_title("한국인 남편 × 외국인 아내 결혼 추이 (2014~2025*)",
                 fontsize=14, weight="bold", pad=15)
    ax.set_xlabel("연도", fontsize=10)
    ax.set_ylabel("결혼 건수")
    ax.set_xticks(years)
    xtick_labels = [f"{y}*" if y == 2025 else str(y) for y in years]
    ax.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=9)
    ax.set_ylim(0, 21000)  # 위쪽 여유 (회복 annotation용)
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # 잠정치 안내 — 그래프 영역 우상단 작은 텍스트
    ax.text(0.02, 0.97, "* 2025: 잠정치 (확정치는 2026년 8~9월 공표 예정)",
            transform=ax.transAxes, ha="left", va="top",
            fontsize=8, color="#888", style="italic")
    save(fig, "1_marriage_trend",
         source="통계청 KOSIS '한국인 남편의 혼인종류/외국인 아내의 국적별 혼인' (2014~2025)")


# ── 2. 2025년 국가 순위 (가로 막대) ────────────────────────────────
def chart_country_ranking():
    # 2025 한국인 남편 × 외국인 아내 (총계)
    data = [
        ("베트남", 4762, True),
        ("중국", 2510, True),
        ("태국", 1951, True),
        ("일본", 1483, True),
        ("미국", 638, True),
        ("필리핀", 527, False),
        ("라오스", 462, False),
        ("캄보디아", 371, False),
        ("러시아", 339, True),
        ("몽골", 183, True),
        ("기타", 1384, False),
    ]
    countries = [d[0] for d in data][::-1]
    counts = [d[1] for d in data][::-1]
    colors = [PRIMARY if d[2] else MUTED for d in data][::-1]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(countries, counts, color=colors, edgecolor="white", linewidth=1)
    for bar, count in zip(bars, counts):
        ax.text(bar.get_width() + 50, bar.get_y() + bar.get_height()/2,
                f"{count:,}", va="center", fontsize=10)
    ax.set_title("외국인 아내 국적 순위 (2025*) — 우리 9개 언어 커버 80%+",
                 fontsize=14, weight="bold", pad=15)
    ax.set_xlabel("결혼 건수   (* 2025 잠정치 기준)", fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # 범례
    from matplotlib.patches import Patch
    legend = [Patch(color=PRIMARY, label="SchoolBridge 9개 언어 직접 지원"),
              Patch(color=MUTED, label="기타")]
    ax.legend(handles=legend, loc="lower right", frameon=False)
    save(fig, "2_country_ranking",
         source="통계청 KOSIS '한국인 남편의 혼인종류/외국인 아내의 국적별 혼인' (2025)")


# ── 3. 다문화 초등 학생 13년 추이 (누적 면적) ─────────────────────
def chart_student_trend():
    years = list(range(2012, 2026))
    domestic = [29282, 32823, 41546, 50191, 59970, 68610, 76181, 83602, 85089, 86399, 84241, 82491, 80155, 76201]
    midentry = [2669, 3006, 3262, 3965, 4577, 4843, 5023, 5148, 5073, 4953, 5087, 5617, 6037, 6216]
    foreign  = [1789, 3531, 3417, 6006, 9425, 9280, 11823, 15131, 17532, 20019, 22312, 27531, 31267, 34184]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.stackplot(years, domestic, midentry, foreign,
                 labels=["국제결혼 가정-국내출생", "중도입국", "외국인 가정 (부모 둘 다 외국인)"],
                 colors=[PRIMARY, WARM, ACCENT], alpha=0.85)
    ax.set_title("초등 다문화 학생 13년 추이 — 3.5배 증가, 외국인 가정 비중 급증",
                 fontsize=14, weight="bold", pad=15)
    ax.set_xlabel("연도")
    ax.set_ylabel("학생 수")
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) for y in years], rotation=0)
    ax.legend(loc="upper left", frameon=False)
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # 외국인가정 비중 강조 텍스트
    ax.annotate("외국인 가정 비중\n2012: 5.3% → 2025: 29.3%",
                xy=(2025, 116601), xytext=(2018, 110000),
                fontsize=10, color=ACCENT, weight="bold",
                arrowprops=dict(arrowstyle="->", color=ACCENT))
    save(fig, "3_student_trend",
         source="한국교육개발원 KESS '연도별 다문화 학생수' (초등학교, 2012~2025)")


# ── 4. 부모 국적별 학생 (2025 초등) — 가로 막대 ────────────────────
def chart_parent_nationality():
    # 2025 초등 (총 116,601)
    data = [
        ("베트남", 35569, True),
        ("중국", 31349, True),
        ("필리핀", 9412, False),
        ("중국 한국계", 5641, True),
        ("중앙아시아", 5443, False),
        ("캄보디아", 4571, False),
        ("일본", 3616, True),
        ("몽골", 3023, True),
        ("러시아", 2213, True),
        ("태국", 1881, True),
        ("미국", 1618, True),
        ("기타", 12265, False),
    ]
    countries = [d[0] for d in data][::-1]
    counts = [d[1] for d in data][::-1]
    colors = [PRIMARY if d[2] else MUTED for d in data][::-1]
    total = sum(d[1] for d in data)

    fig, ax = plt.subplots(figsize=(10, 6.5))
    bars = ax.barh(countries, counts, color=colors, edgecolor="white", linewidth=1)
    for bar, count in zip(bars, counts):
        pct = count / total * 100
        ax.text(bar.get_width() + 300, bar.get_y() + bar.get_height()/2,
                f"{count:,} ({pct:.1f}%)", va="center", fontsize=9)
    ax.set_title("부모 국적별 다문화 초등학생 (2025) — 우리 9개 언어 73%+ 커버",
                 fontsize=14, weight="bold", pad=15)
    ax.set_xlabel("학생 수")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    from matplotlib.patches import Patch
    legend = [Patch(color=PRIMARY, label="SchoolBridge 9개 언어 직접 지원"),
              Patch(color=MUTED, label="기타")]
    ax.legend(handles=legend, loc="lower right", frameon=False)
    save(fig, "4_parent_nationality",
         source="한국교육개발원 KESS '연도별 부모 국적별 다문화 학생수' (초등학교, 2025)")


# ── 5. 시도별 분포 (2025 초등) — 가로 막대 ────────────────────────
def chart_region_distribution():
    data = [
        ("경기", 35199),
        ("서울", 12563),
        ("인천", 9338),
        ("경남", 8134),
        ("충남", 7835),
        ("경북", 6578),
        ("전남", 5556),
        ("전북", 4874),
        ("부산", 4660),
        ("충북", 4607),
        ("대구", 3902),
        ("광주", 3207),
        ("강원", 2775),
        ("울산", 2386),
        ("대전", 2322),
        ("제주", 2127),
        ("세종", 538),
    ]
    sidos = [d[0] for d in data][::-1]
    counts = [d[1] for d in data][::-1]
    total = sum(counts)
    colors = [ACCENT if c == "경기" else (WARM if c in ("서울", "인천") else MUTED) for c in sidos]

    fig, ax = plt.subplots(figsize=(10, 6.5))
    bars = ax.barh(sidos, counts, color=colors, edgecolor="white", linewidth=1)
    for bar, count in zip(bars, counts):
        pct = count / total * 100
        ax.text(bar.get_width() + 200, bar.get_y() + bar.get_height()/2,
                f"{count:,} ({pct:.1f}%)", va="center", fontsize=9)
    ax.set_title("시도별 다문화 초등학생 분포 (2025) — 경기 30%, 수도권 49%",
                 fontsize=14, weight="bold", pad=15)
    ax.set_xlabel("학생 수")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "5_region_distribution",
         source="한국교육개발원 KESS '행정구역별 다문화(유형별) 학생수' (초등학교, 2025)")


# ── 6. TOP5 vs BOTTOM5 — 시군구 다문화 학생 격차 (표 형식) ───────
def chart_hotspot_paradox():
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # TOP 5 (많은 곳)
    top5 = [
        ("경기 안산시", 5205),
        ("경기 시흥시", 3368),
        ("경기 부천시", 2942),
        ("경기 수원시", 2765),
        ("경기 화성시", 2718),
    ]
    # BOTTOM 5 (적은 곳)
    bottom5 = [
        ("경북 울릉군", 6),
        ("인천 옹진군", 13),
        ("대구 군위군", 38),
        ("경기 과천시", 39),
        ("강원 양양군", 45),
    ]

    # 상단 제목
    ax.text(0.5, 0.95, "시군구별 다문화 초등학생 격차 (2025)",
            ha="center", fontsize=15, weight="bold", color="#222")

    # 좌우 영역 동일 폭 (각 0.40, 가운데 0.10 여백)
    # 좌측: x = 0.05 ~ 0.45 (헤더 가운데 0.25)
    # 우측: x = 0.55 ~ 0.95 (헤더 가운데 0.75)

    # 좌측 표 헤더 (TOP 5)
    ax.text(0.25, 0.84, "다문화 학생 많은 곳 TOP 5",
            ha="center", fontsize=12, weight="bold", color=ACCENT)
    # 좌측 표 행
    for i, (name, count) in enumerate(top5):
        y = 0.74 - i * 0.085
        ax.text(0.08, y, f"{i+1}", ha="center", fontsize=11, weight="bold", color="#999")
        ax.text(0.13, y, name, ha="left", fontsize=11.5, color="#222")
        ax.text(0.43, y, f"{count:,}명", ha="right", fontsize=12, weight="bold", color=ACCENT)
    # 좌측 합계
    top_sum = sum(c for _, c in top5)
    ax.plot([0.05, 0.45], [0.30, 0.30], color="#CCC", linewidth=1)
    ax.text(0.13, 0.24, "TOP 5 합계", ha="left", fontsize=10, color="#666")
    ax.text(0.43, 0.24, f"{top_sum:,}명", ha="right", fontsize=11, weight="bold", color=ACCENT)

    # 가운데 세로 분리선
    ax.plot([0.50, 0.50], [0.20, 0.78], color="#DDD", linewidth=1, linestyle="--")

    # 우측 표 헤더 (BOTTOM 5)
    ax.text(0.75, 0.84, "다문화 학생 적은 곳 BOTTOM 5",
            ha="center", fontsize=12, weight="bold", color=PRIMARY)
    # 우측 표 행
    for i, (name, count) in enumerate(bottom5):
        y = 0.74 - i * 0.085
        ax.text(0.58, y, f"{i+1}", ha="center", fontsize=11, weight="bold", color="#999")
        ax.text(0.63, y, name, ha="left", fontsize=11.5, color="#222")
        ax.text(0.93, y, f"{count}명", ha="right", fontsize=12, weight="bold", color=PRIMARY)
    # 우측 합계
    bot_sum = sum(c for _, c in bottom5)
    ax.plot([0.55, 0.95], [0.30, 0.30], color="#CCC", linewidth=1)
    ax.text(0.63, 0.24, "BOTTOM 5 합계", ha="left", fontsize=10, color="#666")
    ax.text(0.93, 0.24, f"{bot_sum}명", ha="right", fontsize=11, weight="bold", color=PRIMARY)

    # 하단 강조 — 격차 한 줄
    fig.text(0.5, 0.13,
             "안산 5,205명 vs 울릉 6명  →  약 870배 격차",
             ha="center", fontsize=14, color="#222", weight="bold",
             bbox=dict(boxstyle="round,pad=0.5", fc="#FFF5F0", ec=ACCENT, lw=1.5))
    # 그 아래 — 조심스러운 보조 멘트
    fig.text(0.5, 0.05,
             "전국 시군구 간 다문화 학생 분포 매우 불균등 — 작은 지역일수록 행정·교육 자원 격차 가능성",
             ha="center", fontsize=10, color="#666", style="italic")
    # ax 영역을 figure 전체로 확장 — 출처(우하단)와 그래프 끝 정렬
    plt.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
    save(fig, "6_hotspot_paradox",
         source="한국교육개발원 KESS '행정구역별 다문화(유형별) 학생수' (초등학교, 2025) 시군구 단위")


# ── 7. 한국어 능력 4영역 (여가부 2024) — 막대 ────────────────────
def chart_korean_ability():
    domains = ["듣기", "말하기", "읽기", "쓰기"]
    scores = [4.04, 4.01, 3.82, 3.68]
    colors = [GREEN, GREEN, ACCENT, ACCENT]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(domains, scores, color=colors, edgecolor="white", linewidth=1.5, width=0.6)
    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                f"{score:.2f}", ha="center", fontsize=12, weight="bold")
    # 5점 만점 reference line
    ax.axhline(5.0, linestyle="--", color=MUTED, alpha=0.5, label="5점 만점")
    ax.axhline(3.89, linestyle=":", color=PRIMARY, alpha=0.5, label="평균 3.89")
    ax.set_title("결혼이민자 한국어 능력 4영역 (5점 척도, 2024 여가부)",
                 fontsize=13, weight="bold", pad=15)
    ax.set_ylabel("점수 (5점 척도)")
    ax.set_ylim(0, 5.5)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # 강조 텍스트 — 막대 위 빈 공간(top-left)에 박스로 배치, 어두운 텍스트로 가독성 확보
    # 화살표 target 은 막대의 좌측 모서리 (score 라벨이 막대 위 가운데에 있어서 가운데 가리키면 가림)
    ax.annotate("가정통신문은 '읽기' 영역\n→ 결혼이민자가 가장 약함",
                xy=(1.7, 3.50), xytext=(0.0, 5.05),
                fontsize=10.5, color="#222", weight="bold", ha="left",
                arrowprops=dict(arrowstyle="->", color=ACCENT, lw=1.8),
                bbox=dict(boxstyle="round,pad=0.45", fc="#FFF5F0",
                          ec=ACCENT, lw=1.5))
    save(fig, "7_korean_ability",
         source="여성가족부 '2024년 전국 다문화가족 실태조사'")


# ── 8. 가정통신문 어휘 난이도 — "일상 회화 ≠ 가정통신문" ────────
def chart_form_letter_vocab():
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.axis("off")

    # 상단 제목 + 부제
    ax.text(0.5, 0.96, "가정통신문 = '일상 회화'와 다른 한국어 영역",
            ha="center", fontsize=15, weight="bold", color="#222")
    ax.text(0.5, 0.89,
            "한국어 평균 3.89/5는 '일상 회화' 기준 — 가정통신문은 행정·격식·한자어가 다수",
            ha="center", fontsize=10, color="#555")

    # 좌측 — 실제 가정통신문 발췌 (회색 톤 박스)
    ax.text(0.23, 0.83, "실제 가정통신문 발췌",
            ha="center", fontsize=11, weight="bold", color="#444")
    sample_text = (
        "5월 23일 현장체험학습을 실시합니다.\n\n"
        "참가 동의서를 4월 28일까지 담임선생님께\n"
        "제출해 주시기 바랍니다.\n\n"
        "회비 12,000원은 CMS 자동이체로 납부\n"
        "부탁드리며, 회신 시 학번·반·이름\n"
        "기재 요망."
    )
    ax.text(0.23, 0.48, sample_text, ha="center", va="center",
            fontsize=10, color="#222",
            bbox=dict(boxstyle="round,pad=0.6", fc="#FAFAFA",
                      ec="#999", lw=1.2))

    # 우측 — 어려운 단어 그리드 (빨간 칩들)
    ax.text(0.72, 0.83, "결혼이민자가 어려워하는 행정·격식·한자어",
            ha="center", fontsize=11, weight="bold", color=ACCENT)
    hard_words = [
        "실시", "동의서", "담임",
        "제출", "회비", "자동이체",
        "납부", "회신", "기재 요망",
    ]
    grid_x0 = 0.56
    grid_y0 = 0.72
    cell_w = 0.10
    cell_h = 0.10
    for i, word in enumerate(hard_words):
        col = i % 3
        row = i // 3
        x = grid_x0 + col * cell_w + cell_w / 2
        y = grid_y0 - row * cell_h
        ax.text(x, y, word, ha="center", va="center",
                fontsize=11, color=ACCENT, weight="bold",
                bbox=dict(boxstyle="round,pad=0.4",
                          fc="#FFF5F0", ec=ACCENT, lw=1.3))

    # 우측 보조 텍스트
    ax.text(0.72, 0.36,
            "한자어·격식체·학교 행정 용어\n→ 일상 한국어 능력만으로 부족",
            ha="center", fontsize=10, color="#444")

    # 하단 메시지 (강조 박스)
    ax.text(0.5, 0.10,
            "→ 한국어 자체 능력으론 안 통함. SchoolBridge가 9개 언어로 변환·전달",
            ha="center", fontsize=12, weight="bold", color=PRIMARY,
            bbox=dict(boxstyle="round,pad=0.55", fc="#E8F2FB",
                      ec=PRIMARY, lw=1.5))

    save(fig, "8_form_letter_vocab",
         source="자체 분석 (가정통신문 어휘 예시) / 평균 점수: 여성가족부 2024 다문화가족 실태조사")


# ── 9. 간접 데이터 종합 — 가정통신문 영역 격차의 일관된 신호 ──────
def chart_indirect_evidence():
    fig, ax = plt.subplots(figsize=(11, 5.8))

    # 데이터 — 모두 2024 여가부 다문화가족 실태조사
    data = [
        ("학부모 모임 비참여", 71.6, "결혼이민자 학부모 71.6%가 학부모 모임에 참여 안 함"),
        ("모임·활동 정보 부족", 31.2, "학교·지역 모임 정보가 부족하다고 응답"),
        ("진학/진로 정보 부족", 21.8, "6~24세 자녀 양육 어려움 1순위 (3위)"),
        ("자녀 학습 지도 어려움", 19.7, "6~24세 자녀 양육 어려움 1순위 (4위)"),
        ("자녀에게 한국어 가르치기 어려움", 17.8, "5세 이하 자녀 양육 어려움 1순위 (3위)"),
    ]
    labels = [d[0] for d in data][::-1]
    values = [d[1] for d in data][::-1]

    # 색 — 비율 큰 순서대로 진해짐 (warm gradient)
    colors = ["#F5C6B6", "#F2A189", "#EE8268", "#E66E4F", ACCENT][::-1]

    bars = ax.barh(labels, values, color=colors, edgecolor="white", linewidth=1.5)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 1.2, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%", va="center", fontsize=12, weight="bold", color="#222")

    ax.set_xlim(0, 85)
    ax.set_xlabel("응답 비율 (%)", fontsize=10, color="#666")
    ax.set_title("가정통신문 영역 격차 — 간접 신호 5종 (2024 여가부)",
                 fontsize=14, weight="bold", pad=15)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.3, axis="x")

    # 하단 메시지
    fig.text(0.5, 0.09,
             "→ '가정통신문 이해도' 직접 통계는 부재. 그러나 정보·소통 격차 신호가 일관적으로 한 방향을 가리킨다.",
             ha="center", fontsize=10.5, color=PRIMARY, weight="bold")

    plt.subplots_adjust(left=0.20, right=0.95, top=0.88, bottom=0.22)
    save(fig, "9_indirect_evidence",
         source="여성가족부 '2024년 전국 다문화가족 실태조사'")


if __name__ == "__main__":
    print("\n[그래프 9종 생성 시작]\n")
    chart_marriage_trend()
    chart_country_ranking()
    chart_student_trend()
    chart_parent_nationality()
    chart_region_distribution()
    chart_hotspot_paradox()
    chart_korean_ability()
    chart_form_letter_vocab()
    chart_indirect_evidence()
    print(f"\n[OK] 완료. 출력 폴더: {OUT}")
