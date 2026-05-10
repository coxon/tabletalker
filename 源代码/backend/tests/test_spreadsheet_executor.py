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
    HeadOp,
    LiteralExpr,
    LoadCsvOp,
    Plan,
    SortOp,
    TailOp,
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
    # Assert the whole payload, not just the first row, so a regression in
    # ordering or in any non-first row trips the test loudly.
    # 华北 is filtered out; 华东 sums to 300 (100+200), 华南 to 50; sorted desc.
    assert rows == [
        {"region": "华东", "total": 300},
        {"region": "华南", "total": 50},
    ]
    assert len(report.verses) == 6
    assert report.verses[0].verb == "load"
    assert report.verses[-1].verb == "render"


def test_forward_reference_rejected(workspace: Path) -> None:
    # No CSV write needed: validation rejects the forward ref before any
    # op runs, so I/O never happens.
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


def test_answer_must_be_render_payload(workspace: Path) -> None:
    """Plans that don't end with `to_table` / `to_chart` get rejected up
    front — the answer slot must be a renderable dict, not a raw DataFrame."""
    _write_sales(workspace)
    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="raw", path="sales.csv"),
        ],
        answer="raw",  # raw is a DataFrame, not a render payload
    )
    with pytest.raises(PlanValidationError, match="not a render payload"):
        execute(plan, workspace)


def test_aggregate_accepts_dataframe_producer(workspace: Path) -> None:
    """Whole-frame aggregation is valid after load/filter/select."""
    _write_sales(workspace)
    plan = Plan(
        ops=[
            LoadCsvOp(kind="load_csv", out="raw", path="sales.csv"),
            AggregateOp(
                kind="aggregate",
                out="totals",
                src="raw",
                aggs=[AggSpec(column="amount", fn="sum", **{"as": "total"})],
            ),
            ToTableOp(kind="to_table", out="result", src="totals"),
        ],
        answer="result",
    )
    report = execute(plan, workspace)
    assert report.answer["rows"] == [{"total": 425}]


def test_head_and_tail_reject_negative_n() -> None:
    """Schema-level: pandas treats negatives as "all but last/first N" — the
    LLM shouldn't accidentally trigger that surprise. Reject at validation."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        HeadOp(kind="head", out="x", src="raw", n=-1)
    with pytest.raises(pydantic.ValidationError):
        TailOp(kind="tail", out="x", src="raw", n=-1)


def test_unknown_fields_in_plan_rejected() -> None:
    """A typo'd or hallucinated key from the LLM should fail validation,
    not silently get dropped."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="extra"):
        # `colum` is a typo of `col` — Plan must reject it instead of
        # accepting a silently-broken expression.
        Plan.model_validate(
            {
                "ops": [
                    {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                    {
                        "kind": "filter_rows",
                        "out": "f",
                        "src": "raw",
                        "where": {"colum": "amount"},  # typo
                    },
                ]
            }
        )


def test_call_expr_arity_enforced_at_schema() -> None:
    """`if` takes exactly 3 args; `abs` exactly 1. Bad counts must fail at
    plan validation, not deep inside expr.evaluate()."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match=r"'if'.*3"):
        Plan.model_validate(
            {
                "ops": [
                    {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                    {
                        "kind": "add_column",
                        "out": "x",
                        "src": "raw",
                        "name": "flag",
                        # `if` requires exactly (cond, then, else) — only one arg
                        # given. Should fail at schema validation.
                        "expr": {
                            "fn": "if",
                            "args": [{"lit": True}],
                        },
                    },
                ]
            }
        )

    with pytest.raises(pydantic.ValidationError, match=r"'abs'.*1"):
        Plan.model_validate(
            {
                "ops": [
                    {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                    {
                        "kind": "add_column",
                        "out": "x",
                        "src": "raw",
                        "name": "a",
                        "expr": {
                            "fn": "abs",
                            "args": [{"lit": 1}, {"lit": 2}],  # abs takes 1
                        },
                    },
                ]
            }
        )
