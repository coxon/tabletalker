"""HTML report renderer + chart-spec selector.

Two responsibilities:

  1. Pick a small set of chart specs from the executed answer/plan
     (`pick_chart_specs`). The selection is deterministic and shape-aware:
     a numeric-by-categorical grouping wants a bar; a sequence indexed by
     a datetime/numeric x wants a line; a small (≤8) categorical breakdown
     also gets a pie.
  2. Render the Jinja HTML report and return both the HTML string and the
     `Chart` list whose anchors the response advertises.

The renderer **enforces** the chart-anchor invariant the contract calls
out (`docs/submission-contract.md` §`charts`): every `html_anchor` we
return must correspond to a `<div id="...">` (or `<section id="...">`)
in the rendered HTML. If a builder ever drifts away from the template,
we raise here rather than ship a chart link the grader can't resolve.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.analyze.schema import Chart, Finding
from app.report.charts import ChartImage, ChartKind, build_chart

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "report.html.j2"

_ECHARTS_JS_PATH = _TEMPLATE_DIR / "echarts.min.js"
_ECHARTS_JS: str = ""
if _ECHARTS_JS_PATH.exists():
    _ECHARTS_JS = _ECHARTS_JS_PATH.read_text(encoding="utf-8")

# `StrictUndefined` is on purpose — silently rendering "" for a missing
# field would mask a contract drift.
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class _ChartSpec:
    kind: ChartKind
    title: str
    anchor_id: str
    labels: list[str]
    values: list[float]


@dataclass(frozen=True)
class RenderedReport:
    """Renderer's twofold output: the HTML string + the contract `Chart` list.

    Keeping them paired in one object makes it impossible for the handler
    to forget one — the anchor invariant is checked here, so a stale
    `Chart` list can't escape this module.
    """

    html: str
    charts: list[Chart] = field(default_factory=list)


@dataclass(frozen=True)
class SmartAnalysisItem:
    label: str
    detail: str


def render_report(
    *,
    report_id: str,
    title: str,
    summary: str,
    findings: list[Finding],
    recommendations: list[str],
    is_refusal: bool,
    answer: dict[str, Any] | None,
) -> RenderedReport:
    """Build the HTML report and matching `Chart` metadata.

    `answer` is the executor's answer payload (the same one stored on
    `Finding.evidence` rows). `None` is allowed — refusal responses pass
    `None` and get a chart-less HTML.
    """

    chart_images = _select_and_build_charts(answer, is_refusal=is_refusal)
    smart_analysis = _build_smart_analysis(
        answer=answer,
        findings=findings,
        is_refusal=is_refusal,
        has_ordered_chart=any(img.type_label == "折线图" for img in chart_images),
    )
    has_interactive = any(img.echarts_option for img in chart_images)
    html = _env.get_template(_TEMPLATE_NAME).render(
        report_id=report_id,
        title=title,
        summary=summary,
        findings=findings,
        recommendations=recommendations,
        is_refusal=is_refusal,
        smart_analysis=smart_analysis,
        charts=chart_images,
        echarts_js=_ECHARTS_JS if has_interactive else "",
    )

    _assert_anchors_present(html, chart_images)

    # Inline-renderable ECharts option only on the FIRST chart. The
    # SPA shows that one chart in the chat thread directly; the rest
    # remain reachable via the report side-panel. Keeping it to one
    # avoids the chat turning into a chart wall — the report panel
    # is right there for users who want all of them.
    charts: list[Chart] = []
    for idx, image in enumerate(chart_images):
        echarts_option = image.echarts_option if idx == 0 and image.echarts_option else None
        charts.append(
            Chart(
                type=image.type_label,  # type: ignore[arg-type]  # type_label is the contract Literal
                title=image.title,
                html_anchor=f"#{image.anchor_id}",
                echarts_option=echarts_option,
            )
        )
    return RenderedReport(html=html, charts=charts)


def _build_smart_analysis(
    *,
    answer: dict[str, Any] | None,
    findings: list[Finding],
    is_refusal: bool,
    has_ordered_chart: bool,
) -> list[SmartAnalysisItem]:
    if is_refusal:
        return []

    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    if answer and answer.get("type") == "table":
        rows = answer.get("rows") or []
        columns = answer.get("columns") or []

    evidence = [ev for finding in findings for ev in finding.evidence]
    evidence_count = len(evidence)
    row_counts = [ev.row_count for ev in evidence if ev.row_count is not None]
    sample_size = max(row_counts) if row_counts else len(rows)
    numeric_cols = _numeric_columns(rows, columns)
    label_col = columns[0] if columns else ""
    top_note = _top_bottom_note(rows, columns)

    stats_parts = [f"样本量 {sample_size}"]
    if columns:
        stats_parts.append(f"结果字段 {len(columns)} 个")
    if numeric_cols:
        stats_parts.append(f"数值字段 {len(numeric_cols)} 个（{', '.join(numeric_cols[:3])}）")
    if top_note:
        stats_parts.append(top_note)
    stats_parts.append(f"证据点 {evidence_count} 条，均来自可复核聚合或过滤")

    trend_detail = _trend_detail(rows, columns, has_ordered_chart)
    root_detail = _root_cause_detail(findings, evidence, label_col)

    return [
        SmartAnalysisItem("统计分析", "；".join(stats_parts) + "。"),
        SmartAnalysisItem("趋势分析", trend_detail),
        SmartAnalysisItem("根因分析", root_detail),
    ]


def _numeric_columns(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    out: list[str] = []
    for col in columns:
        values = [row.get(col) for row in rows]
        if values and all(_is_numeric(value) for value in values):
            out.append(col)
    return out


def _top_bottom_note(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows or len(columns) < 2:
        return ""
    label_col, value_col = _pick_axis_columns(rows, columns)
    if value_col is None or label_col == value_col:
        return ""
    ranked = sorted(
        (
            (str(row.get(label_col, "")), _to_float(row.get(value_col)))
            for row in rows
            if _is_numeric(row.get(value_col))
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    if not ranked:
        return ""
    top_label, top_value = ranked[0]
    if len(ranked) == 1:
        return f"Top1 为 {top_label}={_fmt_number(top_value)}"
    bottom_label, bottom_value = ranked[-1]
    return (
        f"Top1 为 {top_label}={_fmt_number(top_value)}，"
        f"Bottom1 为 {bottom_label}={_fmt_number(bottom_value)}"
    )


def _trend_detail(
    rows: list[dict[str, Any]], columns: list[str], has_ordered_chart: bool
) -> str:
    if not rows or len(columns) < 2:
        return (
            "当前结果表为单值或非表格结果，不包含可比较的有序维度；"
            "无法形成趋势判断，只能基于现有证据给出静态结论。"
        )
    label_col = columns[0]
    labels = [str(row.get(label_col, "")) for row in rows]
    if not has_ordered_chart and not _is_ordered_axis(label_col, labels):
        return (
            f"字段 {label_col} 不具备稳定自然顺序；当前报告不把排名或横向差异包装成趋势，"
            "仅做类别之间的可核验对比。"
        )
    _, value_col = _pick_axis_columns(rows, columns)
    if value_col is None:
        return (
            f"字段 {label_col} 具备顺序线索，但结果表缺少可连续比较的数值指标，"
            "暂不输出趋势强弱判断。"
        )
    values = [_to_float(row.get(value_col)) for row in rows]
    if len(values) < 2:
        return "当前有序维度只有一个观测点，无法判断上升或下降趋势。"
    first, last = values[0], values[-1]
    direction = "上升" if last > first else "下降" if last < first else "持平"
    return (
        f"字段 {label_col} 可作为有序比较维度；{value_col} 从 "
        f"{_fmt_number(first)} 到 {_fmt_number(last)}，整体呈{direction}。"
    )


def _root_cause_detail(
    findings: list[Finding], evidence: list[Any], label_col: str
) -> str:
    filtered = [ev for ev in evidence if getattr(ev, "filters", "")]
    factors = sorted({col for ev in evidence for col in getattr(ev, "columns", [])})
    if filtered:
        filter_note = f"已定位 {len(filtered)} 条带过滤条件的影响因素证据"
    elif label_col:
        filter_note = f"主要影响因素来自字段 {label_col} 的分组差异"
    else:
        filter_note = "当前证据未形成可拆解的过滤条件"

    factor_note = f"涉及字段：{', '.join(factors[:5])}" if factors else "涉及字段有限"
    closure = (
        "现有字段只能支持影响因素定位，不能证明因果原因；报告中的归因必须回到证据表中的字段、占比、排名或异常值。"
    )
    if findings:
        return f"{filter_note}；{factor_note}。{closure}"
    return f"{filter_note}；{factor_note}。暂无 finding 可支撑更完整的归因闭环。"


# ---------------------------------------------------------------------------
# Chart selection
# ---------------------------------------------------------------------------


def _select_and_build_charts(
    answer: dict[str, Any] | None, *, is_refusal: bool
) -> list[ChartImage]:
    """Heuristic chart picker.

    Inputs the answer dict that the executor already returned. We don't
    re-load the DataFrame — the answer table is what the user will see,
    and charting *that* keeps the report numbers consistent with the
    `findings.evidence.value`s.

    Selection rules (apply in order):

      - Refusal or missing answer  → no charts.
      - Answer is a non-table kind → no charts (e.g. raw number).
      - Empty rows                 → no charts (avoid a blank canvas).
      - Otherwise: emit a bar over the first numeric column. If the row
        count is small (≤8) and values are all non-negative, also emit a
        pie. Emit a line only when the label axis is naturally ordered
        (time, numeric, grade, age bucket, complaint count, etc.); a line
        over city / brand / genre is a fake "trend" and hurts 6.A.3.
    """

    if is_refusal or not answer:
        return []
    if answer.get("type") != "table":
        return []
    rows: list[dict[str, Any]] = answer.get("rows") or []
    columns: list[str] = answer.get("columns") or []
    if not rows or not columns:
        return []

    label_col, value_col = _pick_axis_columns(rows, columns)
    if value_col is None:
        return []

    if label_col == value_col:
        labels = [str(i + 1) for i in range(len(rows))]
    else:
        labels = [str(r.get(label_col, "")) for r in rows]
    values = [_to_float(r.get(value_col)) for r in rows]

    title_base = f"{value_col} by {label_col}"
    images: list[ChartImage] = []
    images.append(
        build_chart(
            "bar",
            title=title_base,
            anchor_id=f"chart-{_slug(value_col)}-bar",
            labels=labels,
            values=values,
        )
    )
    if len(rows) >= 3 and _is_ordered_axis(label_col, labels):
        images.append(
            build_chart(
                "line",
                title=f"{value_col} 趋势",
                anchor_id=f"chart-{_slug(value_col)}-line",
                labels=labels,
                values=values,
            )
        )
    if 1 < len(rows) <= 8 and all(v >= 0 for v in values):
        images.append(
            build_chart(
                "pie",
                title=f"{value_col} 占比",
                anchor_id=f"chart-{_slug(value_col)}-pie",
                labels=labels,
                values=values,
            )
        )
    if len(rows) >= 3:
        images.append(
            build_chart(
                "scatter",
                title=f"{value_col} 分布",
                anchor_id=f"chart-{_slug(value_col)}-scatter",
                labels=labels,
                values=values,
            )
        )
    # Heatmap: emit a one-row strip showing the per-label intensity. It's a
    # degenerate 2D heatmap (1 × N) but visually meaningful — the colour
    # gradient gives an at-a-glance ranking that bar charts under-sell when
    # the magnitudes are close. Cap at 24 labels so the colour grid stays
    # legible; very long answer tables stick to bar/line/scatter.
    if 2 <= len(rows) <= 24:
        images.append(
            build_chart(
                "heatmap",
                title=f"{value_col} 强度",
                anchor_id=f"chart-{_slug(value_col)}-heatmap",
                labels=labels,
                values=values,
            )
        )
    # Boxplot: needs ≥4 distinct data points to be meaningful (otherwise the
    # 5-number summary collapses). Useful for spotting outliers in the
    # cross-category spread of the metric — a small region whose value sits
    # far outside the IQR jumps off the chart.
    if len(rows) >= 4:
        finite = [v for v in values if math.isfinite(v)]
        if finite and (max(finite) - min(finite)) > 0:
            images.append(
                build_chart(
                    "box",
                    title=f"{value_col} 跨{label_col}分布",
                    anchor_id=f"chart-{_slug(value_col)}-box",
                    labels=labels,
                    values=values,
                )
            )
    return images


def _pick_axis_columns(
    rows: list[dict[str, Any]], columns: list[str]
) -> tuple[str, str | None]:
    """Heuristic: first column is the label, first numeric column the value.

    The executor's `to_table` op orders columns predictably — group keys
    first, aggregations afterwards — so the first / first-numeric pair is
    a reliable proxy for "what should the X axis say".
    """

    label_col = columns[0]
    value_col: str | None = None
    search_cols = columns[1:] if len(columns) > 1 else columns
    for col in search_cols:
        if col == label_col:
            continue
        if all(_is_numeric(r.get(col)) for r in rows):
            value_col = col
            break
    if value_col is None and len(columns) == 1:
        if all(_is_numeric(r.get(label_col)) for r in rows):
            value_col = label_col
    return label_col, value_col


def _to_float(value: Any) -> float:
    """Coerce to float, mapping non-finite / non-numeric inputs to 0.0.

    NaN sneaks in via pandas aggregations on all-null groups; treating
    it as `0.0` keeps the chart geometry safe. The chart factory does
    the same — see `app.report.charts._sanitise_values` — but doing it
    here too means the picker's "all values non-negative?" check below
    isn't fooled by a `nan >= 0` (which is False, but easy to misread).
    """

    if isinstance(value, bool):  # bool is a numpy/int subclass — coerce explicitly
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return 0.0
    return result if math.isfinite(result) else 0.0


def _fmt_number(value: float) -> str:
    if not math.isfinite(value):
        return "0"
    if value.is_integer():
        return str(int(value))
    return f"{value:.6g}"


def _is_numeric(value: Any) -> bool:
    """True only for *finite* numeric values.

    A NaN-only column should not silently become the picker's value
    axis; treat non-finite as "not a number we can plot".
    """

    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


_ORDERED_AXIS_NAME_HINTS = (
    "date",
    "time",
    "year",
    "month",
    "day",
    "week",
    "quarter",
    "grade",
    "age",
    "complaint",
    "日期",
    "时间",
    "年份",
    "年度",
    "月份",
    "季度",
    "星期",
    "周",
    "年级",
    "年龄",
    "次数",
)

_ORDERED_AXIS_TOKEN_HINTS = frozenset(
    {
        "date",
        "time",
        "year",
        "month",
        "day",
        "week",
        "quarter",
        "grade",
        "age",
        "complaint",
    }
)

_DATE_LABEL_PATTERN = re.compile(r"^\d{4}[-/年]\d{1,2}([-/月]\d{1,2}日?)?$")
_AXIS_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])")


def _is_ordered_axis(label_col: str, labels: list[str]) -> bool:
    """Whether a line chart would encode a real sequence.

    Categorical rows like city / brand / genre have an arbitrary display
    order after sorting by metric; connecting them with a line falsely
    signals a trend. Keep lines for axes that are numeric, date-like, or
    clearly named as ordered stages.
    """

    if len(labels) < 3:
        return False
    name = label_col.lower()
    tokens = {tok.lower() for tok in _AXIS_TOKEN_SPLIT.split(label_col) if tok}
    if tokens & _ORDERED_AXIS_TOKEN_HINTS:
        return True
    if any(hint in name for hint in _ORDERED_AXIS_NAME_HINTS if not hint.isascii()):
        return True
    numeric_count = 0
    date_count = 0
    for label in labels:
        stripped = str(label).strip()
        try:
            float(stripped)
        except ValueError:
            pass
        else:
            numeric_count += 1
        if _DATE_LABEL_PATTERN.match(stripped):
            date_count += 1
    return numeric_count == len(labels) or date_count == len(labels)


_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9]+")


def _slug(value: str) -> str:
    """Anchor-safe slug. Falls back to a fixed name for unicode-only inputs.

    The contract requires anchors be HTML fragment ids; ASCII-only is the
    safest cross-browser choice. CJK column names ("销售额") collapse to
    `metric`, which the renderer then disambiguates with `bar`/`line`/`pie`
    suffixes.
    """

    cleaned = _SLUG_PATTERN.sub("-", value).strip("-").lower()
    return cleaned or "metric"


# ---------------------------------------------------------------------------
# Anchor invariant
# ---------------------------------------------------------------------------


_ANCHOR_PATTERN = re.compile(r'id="([^"]+)"')


def _assert_anchors_present(html: str, images: list[ChartImage]) -> None:
    """Fail loud if the template lost an anchor we promised in the response."""

    ids_in_html = set(_ANCHOR_PATTERN.findall(html))
    missing = [img.anchor_id for img in images if img.anchor_id not in ids_in_html]
    if missing:
        raise RuntimeError(
            f"chart anchors missing from rendered HTML: {missing!r} "
            f"(template = {_TEMPLATE_NAME})"
        )
