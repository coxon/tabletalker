"""SVG chart factory unit tests.

Each builder needs to produce *parseable* SVG that an HTML renderer can
embed directly. We don't validate against the SVG spec — the eval network
won't either — but we do assert the structural pieces the report template
relies on (root `<svg>`, the requested role, value labels in the markup).
"""

from __future__ import annotations

import re

import pytest

from app.report.charts import (
    CHART_LABELS,
    build_chart,
    supported_chart_types,
)


def test_supported_chart_types_matches_label_table() -> None:
    """`supported_chart_types` is the source of truth — keep it in lockstep
    with `CHART_LABELS` so we never claim a kind we can't render."""

    assert set(supported_chart_types()) == set(CHART_LABELS)


def test_bar_chart_includes_values_and_labels() -> None:
    image = build_chart(
        "bar",
        title="Sales by Region",
        anchor_id="chart-sales-bar",
        labels=["华东", "华南", "华北"],
        values=[300.0, 50.0, 75.0],
    )
    assert image.kind == "bar"
    assert image.type_label == "柱状图"
    assert image.anchor_id == "chart-sales-bar"
    assert image.svg.startswith("<svg")
    assert image.svg.endswith("</svg>")
    # Labels and (formatted) values both make it into the rendered markup.
    for label in ("华东", "华南", "华北"):
        assert label in image.svg
    assert "300" in image.svg


def test_line_chart_falls_back_to_bar_for_single_point() -> None:
    """A single-point line is degenerate — the factory should still emit
    something readable rather than a flat svg."""

    image = build_chart(
        "line",
        title="One Day",
        anchor_id="chart-one",
        labels=["Mon"],
        values=[42.0],
    )
    # Bar fallback uses `<rect>`; line normally uses `<polyline>`.
    assert "<rect" in image.svg


def test_pie_chart_renders_legend_percentages() -> None:
    image = build_chart(
        "pie",
        title="Share",
        anchor_id="chart-share-pie",
        labels=["A", "B", "C"],
        values=[1.0, 1.0, 2.0],
    )
    # Legend lines like `A (25.0%)` — match the format we emit.
    assert re.search(r"A \(25\.0%\)", image.svg)
    assert re.search(r"C \(50\.0%\)", image.svg)


def test_pie_clamps_negative_values() -> None:
    """Negative slices can't be drawn; the factory must clamp without
    raising so a malformed answer doesn't abort the report."""

    image = build_chart(
        "pie",
        title="Mixed",
        anchor_id="chart-mixed-pie",
        labels=["pos", "neg"],
        values=[5.0, -3.0],
    )
    assert image.svg.startswith("<svg")
    # Negative entry contributes 0 to the total → 100% goes to "pos".
    assert "pos (100.0%)" in image.svg


def test_empty_chart_for_no_data() -> None:
    image = build_chart(
        "bar",
        title="Nothing",
        anchor_id="chart-nothing",
        labels=[],
        values=[],
    )
    assert "无可视化数据" in image.svg


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        build_chart(
            "bar",
            title="Mismatched",
            anchor_id="x",
            labels=["a", "b"],
            values=[1.0],
        )


def test_bar_chart_handles_negative_values_with_baseline() -> None:
    """Bars below the zero-line must still render with a positive height
    attribute — the previous `value/max` formula produced negative heights
    that SVG silently dropped."""

    import re

    image = build_chart(
        "bar",
        title="Delta",
        anchor_id="chart-delta-bar",
        labels=["A", "B", "C"],
        values=[10.0, -5.0, 20.0],
    )
    # Every <rect> the bar code emits has a positive height.
    bar_heights = [
        float(h) for h in re.findall(r'<rect[^>]*height="([\d.]+)"', image.svg)
    ]
    # Background rect (full canvas) plus one per bar.
    assert len(bar_heights) >= 4
    for h in bar_heights:
        assert h >= 0
    # Labels for the negative bar appear as `-5` in the formatted output.
    assert "-5" in image.svg
