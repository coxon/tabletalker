"""End-to-end executor tests with hand-built Plans (no LLM)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.spreadsheet.executor import (
    OpExecutionError,
    PlanValidationError,
    execute,
)
from app.spreadsheet.schema import (
    AggregateOp,
    AggSpec,
    BinOpExpr,
    ColRefExpr,
    FilterRowsOp,
    GroupByOp,
    LiteralExpr,
    LoadCsvOp,
    Plan,
    SortOp,
    ToTableOp,
)


def _write_sales(workspace: Path) -> Path:
    df = pd.DataFrame(
        {
            "region": ["华东", "华东", "华南", "华北"],
            "amount": [100, 200, 50, 75],
        }
    )
    path = workspace / "sales.csv"
    df.to_csv(path, index=False)
    return path


def test_full_pipeline_load_filter_group_aggregate_sort_table(workspace: Path) -> None:
    _write_sales(workspace)
    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="raw", path="sales.csv"),
            FilterRowsOp(
                kind="filter_rows",
                out="non_north",
                src="raw",
                where=BinOpExpr(
                    op="!=",
                    args=[ColRefExpr(col="region"), LiteralExpr(lit="华北")],
                ),
            ),
            GroupByOp(kind="group_by", out="g", src="non_north", by=["region"]),
            AggregateOp(
                kind="aggregate",
                out="totals",
                src="g",
                aggs=[AggSpec(column="amount", fn="sum", **{"as": "total"})],
            ),
            SortOp(kind="sort", out="ranked", src="totals", by=["total"], desc=[True]),
            ToTableOp(kind="to_table", out="answer", src="ranked", title="By region"),
        ],
        answer="answer",
    )
    report = execute(plan, workspace)
    assert report.answer["type"] == "table"
    rows = report.answer["rows"]
    assert rows[0] == {"region": "华东", "total": 300}
    assert len(report.verses) == 6
    assert report.verses[0].verb == "load"
    assert report.verses[-1].verb == "render"


def test_forward_reference_rejected(workspace: Path) -> None:
    _write_sales(workspace)
    plan = Plan(
        ops=[
            FilterRowsOp(
                kind="filter_rows",
                out="filt",
                src="raw",  # but `raw` is produced AFTER this op
                where=BinOpExpr(
                    op="==", args=[ColRefExpr(col="region"), LiteralExpr(lit="华东")]
                ),
            ),
            LoadCsvOp(kind="load_csv", out="raw", path="sales.csv"),
        ]
    )
    with pytest.raises(PlanValidationError, match="undefined input"):
        execute(plan, workspace)


def test_duplicate_output_name_rejected(workspace: Path) -> None:
    _write_sales(workspace)
    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="x", path="sales.csv"),
            LoadCsvOp(kind="load_csv", out="x", path="sales.csv"),
        ]
    )
    with pytest.raises(PlanValidationError, match="reuses output name"):
        execute(plan, workspace)


def test_op_failure_wraps_with_index(workspace: Path) -> None:
    _write_sales(workspace)
    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="raw", path="sales.csv"),
            SortOp(kind="sort", out="s", src="raw", by=["NOT_A_COLUMN"]),
        ]
    )
    with pytest.raises(OpExecutionError) as info:
        execute(plan, workspace)
    assert info.value.op_index == 1
    assert info.value.op.kind == "sort"
