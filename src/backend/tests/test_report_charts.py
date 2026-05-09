"""ECharts chart factory unit tests.

Each builder needs to produce a valid ECharts option JSON that the report
template can embed. For empty data, a fallback SVG is used. We validate
structural pieces: kind, type_label, anchor_id, and option content.
"""

from __future__ import annotations

import json

import pytest

from app.report.charts import (
    CHART_LABELS,
    build_chart,
    supported_chart_types,
)


def test_supported_chart_types_matches_label_table() -> None:
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
    assert image.echarts_option
    opt = json.loads(image.echarts_option)
    assert opt["series"][0]["type"] == "bar"
    assert opt["xAxis"]["data"] == ["华东", "华南", "华北"]
    assert opt["series"][0]["data"] == [300.0, 50.0, 75.0]


def test_line_chart_produces_line_series() -> None:
    image = build_chart(
        "line",
        title="Trend",
        anchor_id="chart-trend-line",
        labels=["Mon", "Tue", "Wed"],
        values=[10.0, 20.0, 15.0],
    )
    opt = json.loads(image.echarts_option)
    assert opt["series"][0]["type"] == "line"


def test_pie_chart_renders_data_with_names() -> None:
    image = build_chart(
        "pie",
        title="Share",
        anchor_id="chart-share-pie",
        labels=["A", "B", "C"],
        values=[1.0, 1.0, 2.0],
    )
    opt = json.loads(image.echarts_option)
    assert opt["series"][0]["type"] == "pie"
    data = opt["series"][0]["data"]
    names = [d["name"] for d in data]
    assert "A" in names
    assert "C" in names


def test_pie_clamps_negative_values() -> None:
    image = build_chart(
        "pie",
        title="Mixed",
        anchor_id="chart-mixed-pie",
        labels=["pos", "neg"],
        values=[5.0, -3.0],
    )
    opt = json.loads(image.echarts_option)
    data = opt["series"][0]["data"]
    for d in data:
        assert d["value"] >= 0


def test_scatter_chart() -> None:
    image = build_chart(
        "scatter",
        title="Distribution",
        anchor_id="chart-dist-scatter",
        labels=["A", "B", "C"],
        values=[10.0, 20.0, 30.0],
    )
    assert image.kind == "scatter"
    assert image.type_label == "散点图"
    opt = json.loads(image.echarts_option)
    assert opt["series"][0]["type"] == "scatter"


def test_empty_chart_for_no_data() -> None:
    image = build_chart(
        "bar",
        title="Nothing",
        anchor_id="chart-nothing",
        labels=[],
        values=[],
    )
    assert "无可视化数据" in image.svg
    assert image.echarts_option == ""


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        build_chart(
            "bar",
            title="Mismatched",
            anchor_id="x",
            labels=["a", "b"],
            values=[1.0],
        )


def test_bar_chart_handles_negative_values() -> None:
    image = build_chart(
        "bar",
        title="Delta",
        anchor_id="chart-delta-bar",
        labels=["A", "B", "C"],
        values=[10.0, -5.0, 20.0],
    )
    opt = json.loads(image.echarts_option)
    assert opt["series"][0]["data"] == [10.0, -5.0, 20.0]


def test_all_chart_types_have_tooltip() -> None:
    for kind in supported_chart_types():
        image = build_chart(
            kind,
            title=f"Test {kind}",
            anchor_id=f"chart-test-{kind}",
            labels=["X", "Y", "Z"],
            values=[1.0, 2.0, 3.0],
        )
        opt = json.loads(image.echarts_option)
        assert "tooltip" in opt
