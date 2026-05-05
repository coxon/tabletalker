"""Group-by / aggregate / sort / head / tail."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.ops.aggregate import handle_aggregate, handle_group_by
from app.spreadsheet.ops.sort import handle_head, handle_sort, handle_tail
from app.spreadsheet.schema import (
    AggregateOp,
    AggSpec,
    GroupByOp,
    HeadOp,
    SortOp,
    TailOp,
)


def test_group_then_aggregate(ctx: SpreadsheetContext) -> None:
    handle_group_by(GroupByOp(kind="group_by", out="g", src="sales", by=["region"]), ctx)
    handle_aggregate(
        AggregateOp(
            kind="aggregate",
            out="totals",
            src="g",
            aggs=[
                AggSpec(column="amount", fn="sum", **{"as": "total"}),
                AggSpec(column="orders", fn="sum", **{"as": "n_orders"}),
            ],
        ),
        ctx,
    )
    df = ctx.get("totals")
    assert set(df.columns) == {"region", "total", "n_orders"}
    east = df[df["region"] == "华东"].iloc[0]
    assert east["total"] == 300
    assert east["n_orders"] == 30


def test_sort_desc(ctx: SpreadsheetContext) -> None:
    handle_sort(
        SortOp(kind="sort", out="sorted", src="sales", by=["amount"], desc=[True]),
        ctx,
    )
    df = ctx.get("sorted")
    assert df["amount"].tolist() == [200, 150, 100, 75, 50]


def test_sort_rejects_mismatched_desc_length() -> None:
    """`desc` length must match `by` length — caught at schema validation."""
    with pytest.raises(ValidationError) as exc_info:
        SortOp(
            kind="sort",
            out="sorted",
            src="sales",
            by=["amount", "region"],
            desc=[True],  # length 1, but `by` has 2 columns
        )
    assert "sort.desc length" in str(exc_info.value)


def test_head_and_tail(ctx: SpreadsheetContext) -> None:
    handle_head(HeadOp(kind="head", out="top", src="sales", n=2), ctx)
    handle_tail(TailOp(kind="tail", out="bot", src="sales", n=2), ctx)
    assert len(ctx.get("top")) == 2
    assert len(ctx.get("bot")) == 2
