"""Evidence builder unit tests — pure logic, no executor or LLM."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.analyze.evidence import EvidenceContext, build_evidence
from app.spreadsheet.executor import execute
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


def _ctx() -> EvidenceContext:
    return EvidenceContext(dataset="hackathon-test", table="sales.csv")


def test_aggregate_plan_emits_count_and_per_row_evidence(workspace: Path) -> None:
    """The canonical filter→group→aggregate flow:
    one count(*) row + one per (group-row, agg-spec) row."""

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
    rows = build_evidence(plan, report.answer, report.op_results, _ctx())

    # 1 filter-level count(*) + 2 per-row aggregate rows = 3.
    assert len(rows) == 3

    # The count(*) row pins the post-filter total. Filter excluded 华北
    # (1 row out of 4); 3 remain.
    count_row = rows[0]
    assert count_row.aggregation == "count(*)"
    assert count_row.value == 3
    assert count_row.row_count == 3
    assert count_row.filters == "(region != '华北')"
    assert count_row.columns == ["region"]

    # Per-row evidence: regions are emitted in answer order (sorted desc
    # by total → 华东 first, 华南 second).
    east, south = rows[1], rows[2]
    assert east.aggregation == "sum(amount)"
    assert east.value == 300  # 100 + 200
    assert east.filters == "(region != '华北') & (region == '华东')"
    assert "amount" in east.columns and "region" in east.columns

    assert south.aggregation == "sum(amount)"
    assert south.value == 50
    assert south.filters == "(region != '华北') & (region == '华南')"


def test_no_filter_no_aggregate_emits_single_total(workspace: Path) -> None:
    """A `head` of the raw load: no filter, no aggregate. We still emit
    a single count(*) row over the load output, with empty filter."""

    _write_sales(workspace)
    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="raw", path="sales.csv"),
            ToTableOp(kind="to_table", out="answer", src="raw"),
        ],
        answer="answer",
    )
    report = execute(plan, workspace)
    rows = build_evidence(plan, report.answer, report.op_results, _ctx())

    assert len(rows) == 1
    assert rows[0].filters == ""
    assert rows[0].aggregation == "count(*)"
    # Whole-table count: 4 rows in the fixture.
    assert rows[0].value == 4
    assert rows[0].row_count == 4
    # Falls back to result columns when no filter columns are referenced.
    assert rows[0].columns == ["region", "amount"]


def test_quoted_column_name_with_spaces(workspace: Path) -> None:
    """Headers with spaces / parens get backtick-quoted in `filters` so
    the grader's pandas eval can parse them. `Age` stays bare."""

    df = pd.DataFrame(
        {
            "Age": [25, 30, 60],
            "Purchase Amount (USD)": [10.0, 20.0, 30.0],
        }
    )
    path = workspace / "shop.csv"
    df.to_csv(path, index=False)

    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="raw", path="shop.csv"),
            FilterRowsOp(
                kind="filter_rows",
                out="senior",
                src="raw",
                where=BinOpExpr(
                    op=">=",
                    args=[ColRefExpr(col="Age"), LiteralExpr(lit=55)],
                ),
            ),
            GroupByOp(kind="group_by", out="g", src="senior", by=["Age"]),
            AggregateOp(
                kind="aggregate",
                out="agg",
                src="g",
                aggs=[
                    AggSpec(column="Purchase Amount (USD)", fn="mean", **{"as": "avg_amt"})
                ],
            ),
            ToTableOp(kind="to_table", out="answer", src="agg"),
        ],
        answer="answer",
    )
    report = execute(plan, workspace)
    rows = build_evidence(plan, report.answer, report.op_results, _ctx())

    count_row = rows[0]
    assert count_row.filters == "(Age >= 55)"
    # Per-row: backtick-quoted alias survives into `aggregation`.
    agg_row = rows[1]
    assert agg_row.aggregation == "mean(Purchase Amount (USD))"
    assert agg_row.filters == "(Age >= 55) & (Age == 60)"


def test_string_literals_quoted_with_apostrophe_doubled(workspace: Path) -> None:
    """Apostrophes in string literals must be doubled SQL-style or the
    grader's predicate parsing breaks."""

    df = pd.DataFrame({"name": ["O'Brien", "Smith"], "score": [10, 20]})
    path = workspace / "names.csv"
    df.to_csv(path, index=False)

    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="raw", path="names.csv"),
            FilterRowsOp(
                kind="filter_rows",
                out="match",
                src="raw",
                where=BinOpExpr(
                    op="==",
                    args=[ColRefExpr(col="name"), LiteralExpr(lit="O'Brien")],
                ),
            ),
            ToTableOp(kind="to_table", out="answer", src="match"),
        ],
        answer="answer",
    )
    report = execute(plan, workspace)
    rows = build_evidence(plan, report.answer, report.op_results, _ctx())
    assert rows[0].filters == "(name == 'O''Brien')"
