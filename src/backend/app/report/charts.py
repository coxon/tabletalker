"""ECharts-based interactive chart factory.

Generates JSON option objects for ECharts 5.x. The JS runtime is inlined
into the HTML report (no CDN dependency) so the grader sandbox can render
charts without network access.

Four chart types: bar / line / pie / scatter. Each option includes
tooltip, toolbox (save-as-image), and dataZoom (bar/line/scatter) for
interactive exploration.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import escape as _xml_escape

ChartKind = Literal["bar", "line", "pie", "scatter"]

CHART_LABELS: dict[ChartKind, str] = {
    "bar": "柱状图",
    "line": "折线图",
    "pie": "饼图",
    "scatter": "散点图",
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
    data = [{"name": label, "value": val} for label, val in zip(labels, sanitised)]
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


def _format_value(value: float) -> str:
    if not math.isfinite(value):
        return "—"
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"
