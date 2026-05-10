"""Generate the README benchmark charts as static SVGs.

Why a one-shot script vs committing to matplotlib in pyproject:
  - matplotlib is heavy (~30 MiB + transitive deps) and is *only* used at
    documentation build time. Adding it to the backend dep set would
    bloat every prod install for zero runtime value.
  - `uv run --with matplotlib` pulls it into a transient env per
    invocation; the project venv stays lean.

Run:
  uv run --with matplotlib python eval/render_readme_charts.py

Outputs:
  docs/images/score_breakdown.svg   — 100/100 客观项构成（饼图）
  docs/images/model_compare.svg     — 4 模型 main/followup 对比（双柱）
  docs/images/stage_timing.svg      — 端到端耗时分段（饼图）

Re-render after every fresh eval run if any of these numbers move:
  - score_breakdown:  pull from 自测报告/latest_evaluation_metrics.md
  - model_compare:    pull from eval/runs/aigw-*/summary.json
  - stage_timing:     pull from eval/runs/<latest>/summary.json metrics.stage_p50_s
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display backend needed for SVG export
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

# Match ECharts palette used in app/report/charts.py so the README visual
# language tracks the in-product reports — readers seeing both pages get
# the same colour cues for "main metric" / "supporting" / "warning".
PALETTE = ["#3366cc", "#109618", "#ff9900", "#dc3912", "#990099", "#0099c6"]

# Sans-serif with CJK fallback — matplotlib will pick whatever sans-serif
# is available; SVG embeds glyph paths so the rendered file doesn't need
# the font installed on the viewer's machine. (Set explicitly so the chart
# title / axis labels render the Chinese strings instead of falling back
# to tofu boxes when matplotlib's default sans-serif lacks CJK coverage.)
plt.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["svg.fonttype"] = "path"  # convert text to paths so SVG is portable


def chart_score_breakdown() -> None:
    """100/100 客观项构成 — pie of all earned points."""

    labels = [
        "智能分析  60 / 60",
        "智能交互  20 / 20",
        "数据接入  20 / 20",
    ]
    sizes = [60, 20, 20]
    colors = [PALETTE[0], PALETTE[1], PALETTE[2]]
    explode = [0.0, 0.0, 0.0]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    wedges, _, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        explode=explode,
        autopct=lambda pct: f"{pct:.0f}%",
        startangle=90,
        counterclock=False,
        pctdistance=0.78,
        textprops={"fontsize": 11},
        wedgeprops={"edgecolor": "white", "linewidth": 2},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontweight("bold")
        t.set_fontsize(10)
    ax.set_title("客观项 100/100 构成", fontsize=14, pad=12)
    fig.tight_layout()
    fig.savefig(OUT / "score_breakdown.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def chart_model_compare() -> None:
    """4 模型横向对比 — grouped bar of main success vs followup carry."""

    models = ["qwen3.6-plus", "glm-5", "deepseek-v3.2", "MiniMax-M2.5"]
    main_pct = [100, 100, 40, 40]
    followup_pct = [100, 80, 100, 100]

    x = np.arange(len(models))
    width = 0.36

    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)
    bars1 = ax.bar(
        x - width / 2,
        main_pct,
        width,
        label="main 成功率",
        color=PALETTE[0],
    )
    bars2 = ax.bar(
        x + width / 2,
        followup_pct,
        width,
        label="followup 上下文继承率",
        color=PALETTE[1],
    )

    ax.set_ylim(0, 115)
    ax.set_ylabel("百分比 (%)", fontsize=11)
    ax.set_title("4 模型在 5 个官方公开数据集上的横向对比", fontsize=13, pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=11)
    ax.legend(loc="upper right", fontsize=10, frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.set_major_locator(plt.MultipleLocator(20))
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    # In-bar labels so readers don't have to map bar height to the y-axis.
    for bars in (bars1, bars2):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(
                f"{int(h)}",
                xy=(bar.get_x() + bar.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=10,
                color="#222",
            )

    fig.tight_layout()
    fig.savefig(OUT / "model_compare.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def chart_stage_timing() -> None:
    """端到端耗时分段 — pie."""

    labels = [
        "finalize_llm（叙事 LLM）",
        "plan_llm（规划 LLM）",
        "profile + execute + evidence + render",
    ]
    sizes = [66, 34, 0.2]
    colors = [PALETTE[2], PALETTE[3], PALETTE[1]]
    explode = [0.0, 0.0, 0.0]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    wedges, _, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        explode=explode,
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 2 else f"~{pct:.1f}%",
        startangle=90,
        counterclock=False,
        pctdistance=0.78,
        textprops={"fontsize": 11},
        wedgeprops={"edgecolor": "white", "linewidth": 2},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontweight("bold")
        t.set_fontsize(10)
    autotexts[-1].set_color("#222")  # tiny slice needs an outside-readable label
    ax.set_title("端到端耗时几乎全在 LLM round-trip", fontsize=14, pad=12)
    fig.tight_layout()
    fig.savefig(OUT / "stage_timing.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    chart_score_breakdown()
    chart_model_compare()
    chart_stage_timing()
    for f in sorted(OUT.glob("*.svg")):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.relative_to(OUT.parent.parent)}  {size_kb:.1f} KiB")


if __name__ == "__main__":
    main()
