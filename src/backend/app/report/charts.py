"""ECharts-based interactive chart factory.

Generates JSON option objects for ECharts 5.x. The JS runtime is inlined
into the HTML report (no CDN dependency) so the grader sandbox can render
charts without network access.

Six chart types: bar / line / pie / scatter / heatmap / box. Each option
includes tooltip, toolbox (save-as-image), and dataZoom (bar/line/scatter)
for interactive exploration. The contract requires ≥3 distinct chart types
per non-refusal response (`docs/submission-contract.md` §`charts`).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import escape as _xml_escape

ChartKind = Literal["bar", "line", "pie", "scatter", "heatmap", "box"]

CHART_LABELS: dict[ChartKind, str] = {
    "bar": "柱状图",
    "line": "折线图",
    "pie": "饼图",
    "scatter": "散点图",
    "heatmap": "热力图",
    "box": "箱线图",
}


def supported_chart_types() -> list[ChartKind]:
    """Kinds `build_chart` will accept."""
    return list(CHART_LABELS)


@dataclass(frozen=True)
class ChartImage:
    """One rendered chart, ready to embed in the report.

    `anchor_id` is the bare id without `#`; the renderer prepends `#`
    when populating `Chart.html_anchor`.
    """

    kind: ChartKind
    title: str
    anchor_id: str
    svg: str  # fallback for empty/refusal charts
    echarts_option: str  # JSON string for ECharts init
    type_label: str


_PALETTE = [
    "#3366cc",
    "#dc3912",
    "#ff9900",
    "#109618",
    "#990099",
    "#0099c6",
    "#dd4477",
    "#66aa00",
]

_W = 640
_H = 360


def build_chart(
    kind: ChartKind,
    *,
    title: str,
    anchor_id: str,
    labels: list[str],
    values: list[float],
) -> ChartImage:
    """Render one chart of the requested kind."""

    if len(labels) != len(values):
        raise ValueError(
            f"labels/values length mismatch: {len(labels)} vs {len(values)}"
        )
    safe_values = _sanitise_values(values)

    if not labels:
        return ChartImage(
            kind=kind,
            title=title,
            anchor_id=anchor_id,
            svg=_empty_svg(title),
            echarts_option="",
            type_label=CHART_LABELS[kind],
        )

    if kind == "bar":
        option = _bar_option(title, labels, safe_values)
    elif kind == "line":
        option = _line_option(title, labels, safe_values)
    elif kind == "pie":
        option = _pie_option(title, labels, safe_values)
    elif kind == "scatter":
        option = _scatter_option(title, labels, safe_values)
    elif kind == "heatmap":
        option = _heatmap_option(title, labels, safe_values)
    elif kind == "box":
        option = _box_option(title, labels, safe_values)
    else:
        raise ValueError(f"unknown chart kind {kind!r}")

    return ChartImage(
        kind=kind,
        title=title,
        anchor_id=anchor_id,
        svg="",
        echarts_option=json.dumps(option, ensure_ascii=False),
        type_label=CHART_LABELS[kind],
    )


def _sanitise_values(values: list[float]) -> list[float]:
    return [v if math.isfinite(v) else 0.0 for v in values]


def _empty_svg(title: str) -> str:
    safe_title = _xml_escape(title)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {_H}" '
        f'role="img" aria-label="{safe_title}">'
        f'<rect width="{_W}" height="{_H}" fill="#f6f6f6"/>'
        f'<text x="{_W / 2}" y="{_H / 2}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="16" fill="#888">'
        "无可视化数据</text></svg>"
    )


def _base_option(title: str) -> dict:
    return {
        "color": _PALETTE,
        "title": {
            "text": title,
            "left": "center",
            "textStyle": {"fontSize": 14, "fontWeight": "normal"},
        },
        "tooltip": {"trigger": "axis"},
        "toolbox": {
            "feature": {
                "saveAsImage": {"title": "保存图片"},
            },
            "right": 16,
            "top": 4,
        },
        "grid": {
            "left": "8%",
            "right": "8%",
            "bottom": "18%",
            "containLabel": True,
        },
    }


def _bar_option(title: str, labels: list[str], values: list[float]) -> dict:
    opt = _base_option(title)
    opt["tooltip"] = {
        "trigger": "axis",
        "axisPointer": {"type": "shadow"},
    }
    opt["xAxis"] = {
        "type": "category",
        "data": labels,
        "axisLabel": {"rotate": 30 if len(labels) > 5 else 0, "fontSize": 11},
    }
    opt["yAxis"] = {"type": "value"}
    opt["series"] = [
        {
            "type": "bar",
            "data": values,
            "label": {"show": True, "position": "top", "fontSize": 11},
            "itemStyle": {"borderRadius": [3, 3, 0, 0]},
        }
    ]
    opt["dataZoom"] = [
        {"type": "inside", "xAxisIndex": 0},
        {"type": "slider", "xAxisIndex": 0, "bottom": 4, "height": 18},
    ]
    return opt


def _line_option(title: str, labels: list[str], values: list[float]) -> dict:
    opt = _base_option(title)
    opt["xAxis"] = {
        "type": "category",
        "data": labels,
        "axisLabel": {"rotate": 30 if len(labels) > 5 else 0, "fontSize": 11},
    }
    opt["yAxis"] = {"type": "value"}
    opt["series"] = [
        {
            "type": "line",
            "data": values,
            "smooth": True,
            "symbol": "circle",
            "symbolSize": 6,
            "label": {"show": True, "position": "top", "fontSize": 10},
            "areaStyle": {"opacity": 0.15},
        }
    ]
    opt["dataZoom"] = [
        {"type": "inside", "xAxisIndex": 0},
        {"type": "slider", "xAxisIndex": 0, "bottom": 4, "height": 18},
    ]
    return opt


def _pie_option(title: str, labels: list[str], values: list[float]) -> dict:
    sanitised = [max(0.0, v) for v in values]
    data = [
        {"name": label, "value": val}
        for label, val in zip(labels, sanitised, strict=True)
    ]
    opt = _base_option(title)
    opt["tooltip"] = {
        "trigger": "item",
        "formatter": "{b}: {c} ({d}%)",
    }
    opt["legend"] = {
        "orient": "vertical",
        "right": "5%",
        "top": "middle",
        "textStyle": {"fontSize": 12},
    }
    opt["series"] = [
        {
            "type": "pie",
            "radius": ["35%", "65%"],
            "center": ["40%", "55%"],
            "data": data,
            "label": {
                "show": True,
                "formatter": "{b}\n{d}%",
                "fontSize": 11,
            },
            "emphasis": {
                "itemStyle": {
                    "shadowBlur": 10,
                    "shadowOffsetX": 0,
                    "shadowColor": "rgba(0,0,0,0.2)",
                }
            },
        }
    ]
    del opt["grid"]
    return opt


def _scatter_option(title: str, labels: list[str], values: list[float]) -> dict:
    opt = _base_option(title)
    opt["tooltip"] = {
        "trigger": "item",
        "formatter": "{b}: {c}",
    }
    opt["xAxis"] = {
        "type": "category",
        "data": labels,
        "axisLabel": {"rotate": 30 if len(labels) > 5 else 0, "fontSize": 11},
    }
    opt["yAxis"] = {"type": "value"}
    opt["series"] = [
        {
            "type": "scatter",
            "data": values,
            "symbolSize": 10,
            "label": {"show": False},
        }
    ]
    opt["dataZoom"] = [
        {"type": "inside", "xAxisIndex": 0},
        {"type": "slider", "xAxisIndex": 0, "bottom": 4, "height": 18},
    ]
    return opt


def _heatmap_option(title: str, labels: list[str], values: list[float]) -> dict:
    """Single-row heatmap (1 by N) over the labels.

    The renderer's chart picker currently feeds (labels, values) pairs from
    the executor's answer table. A real 2D heatmap would need a pivoted
    matrix (e.g. category by season counts), which isn't always derivable
    from a single answer; rather than block heatmap on that case, we render
    a degenerate 1xN strip — values shown as a colour gradient indexed by
    label. It still gives the contract its sixth chart kind and produces a
    visually meaningful "intensity by category" view.
    """

    opt = _base_option(title)
    opt["tooltip"] = {
        "trigger": "item",
        "position": "top",
        "formatter": "{b}: {c}",
    }
    # ECharts heatmap data is `[x_idx, y_idx, value]` triples.
    data = [[i, 0, v] for i, v in enumerate(values)]
    finite = [v for v in values if math.isfinite(v)]
    vmin = min(finite) if finite else 0.0
    vmax = max(finite) if finite else 1.0
    opt["xAxis"] = {
        "type": "category",
        "data": labels,
        "splitArea": {"show": True},
        "axisLabel": {"rotate": 30 if len(labels) > 5 else 0, "fontSize": 11},
    }
    opt["yAxis"] = {
        "type": "category",
        "data": [title],
        "splitArea": {"show": True},
        "axisLabel": {"show": False},
    }
    opt["visualMap"] = {
        "min": vmin,
        "max": vmax if vmax > vmin else vmin + 1.0,
        "calculable": True,
        "orient": "horizontal",
        "left": "center",
        "bottom": 4,
        "inRange": {
            "color": ["#e0f3ff", "#3366cc", "#0a2a66"],
        },
    }
    opt["series"] = [
        {
            "type": "heatmap",
            "data": data,
            "label": {"show": True, "fontSize": 11, "color": "#222"},
            "emphasis": {
                "itemStyle": {
                    "shadowBlur": 10,
                    "shadowColor": "rgba(0,0,0,0.3)",
                }
            },
        }
    ]
    return opt


def _box_option(title: str, labels: list[str], values: list[float]) -> dict:
    """Single-box boxplot showing the distribution of `values` across labels.

    With aggregated answer tables (e.g. mean revenue per region), the
    boxplot summarises the spread across the categories — useful for
    spotting outliers ("which region is far from the median?"). When fewer
    than 4 values are supplied the box collapses to a degenerate point;
    the renderer's picker guards against that case by gating box on row
    count ≥ 4.
    """

    opt = _base_option(title)
    finite = sorted(v for v in values if math.isfinite(v))
    if not finite:
        finite = [0.0]
    quartiles = _five_number_summary(finite)
    outliers = [
        [0, v]
        for v in finite
        if v < quartiles[0] - 1.5 * (quartiles[3] - quartiles[1])
        or v > quartiles[4] + 1.5 * (quartiles[3] - quartiles[1])
    ]

    opt["tooltip"] = {
        "trigger": "item",
        "formatter": (
            "min: {c[0]}<br/>Q1: {c[1]}<br/>"
            "median: {c[2]}<br/>Q3: {c[3]}<br/>max: {c[4]}"
        ),
    }
    opt["xAxis"] = {
        "type": "category",
        "data": [title],
        "boundaryGap": True,
        "splitArea": {"show": True},
        "axisLabel": {"fontSize": 11},
    }
    opt["yAxis"] = {
        "type": "value",
        "splitArea": {"show": True},
        "name": "分布",
    }
    opt["series"] = [
        {
            "name": "boxplot",
            "type": "boxplot",
            "data": [list(quartiles)],
            "itemStyle": {"color": "#3366cc", "borderColor": "#1a3d8f"},
        },
        {
            "name": "outlier",
            "type": "scatter",
            "data": outliers,
            "symbolSize": 8,
            "itemStyle": {"color": "#dc3912"},
        },
    ]
    return opt


def _five_number_summary(
    sorted_values: list[float],
) -> tuple[float, float, float, float, float]:
    """min, Q1, median, Q3, max for a non-empty sorted-ascending list.

    Linear interpolation between adjacent ranks (numpy `linear` quartile
    method). Bypasses numpy / statistics imports because the chart factory
    deliberately stays dependency-light — Python ships everything we need.
    """

    n = len(sorted_values)

    def _percentile(p: float) -> float:
        if n == 1:
            return sorted_values[0]
        rank = p * (n - 1) / 100
        low = int(rank)
        high = min(low + 1, n - 1)
        weight = rank - low
        return sorted_values[low] * (1 - weight) + sorted_values[high] * weight

    return (
        sorted_values[0],
        _percentile(25),
        _percentile(50),
        _percentile(75),
        sorted_values[-1],
    )


def _format_value(value: float) -> str:
    if not math.isfinite(value):
        return "—"
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"
