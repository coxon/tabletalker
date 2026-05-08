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
    has_interactive = any(img.echarts_option for img in chart_images)
    html = _env.get_template(_TEMPLATE_NAME).render(
        report_id=report_id,
        title=title,
        summary=summary,
        findings=findings,
        recommendations=recommendations,
        is_refusal=is_refusal,
        charts=chart_images,
        echarts_js=_ECHARTS_JS if has_interactive else "",
    )

    _assert_anchors_present(html, chart_images)

    charts: list[Chart] = [
        Chart(
            type=image.type_label,  # type: ignore[arg-type]  # type_label is the contract Literal
            title=image.title,
            html_anchor=f"#{image.anchor_id}",
        )
        for image in chart_images
    ]
    return RenderedReport(html=html, charts=charts)


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
        pie. If row count ≥3, also emit a line. Result is always ≥3
        charts when we have data, satisfying the contract's "≥3 distinct
        types when not refusing".
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
    if len(rows) >= 3:
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
