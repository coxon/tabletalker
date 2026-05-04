"""Join / pivot / melt / output ops."""

from __future__ import annotations

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.ops.join import handle_join
from app.spreadsheet.ops.output import handle_to_chart, handle_to_table
from app.spreadsheet.ops.reshape import handle_melt, handle_pivot
from app.spreadsheet.schema import (
    JoinOp,
    MeltOp,
    PivotOp,
    ToChartOp,
    ToTableOp,
)


def test_join_inner(ctx: SpreadsheetContext, regions_df: pd.DataFrame) -> None:
    ctx.put("regions", regions_df)
    handle_join(
        JoinOp(
            kind="join",
            out="merged",
            left="sales",
            right="regions",
            on=["region"],
            how="inner",
        ),
        ctx,
    )
    merged = ctx.get("merged")
    assert "manager" in merged.columns
    assert len(merged) == 5  # all sales rows have a matching region


def test_pivot_then_melt_round_trip(ctx: SpreadsheetContext) -> None:
    handle_pivot(
        PivotOp(
            kind="pivot",
            out="wide",
            src="sales",
            index=["region"],
            columns="quarter",
            values="amount",
            aggfn="sum",
        ),
        ctx,
    )
    wide = ctx.get("wide")
    assert "Q1" in wide.columns and "Q2" in wide.columns

    handle_melt(
        MeltOp(
            kind="melt",
            out="long",
            src="wide",
            id_vars=["region"],
            var_name="quarter",
            value_name="amount",
        ),
        ctx,
    )
    long = ctx.get("long")
    assert set(long.columns) == {"region", "quarter", "amount"}


def test_to_table_payload(ctx: SpreadsheetContext) -> None:
    handle_to_table(ToTableOp(kind="to_table", out="answer", src="sales", title="Sales"), ctx)
    payload = ctx.get("answer")
    assert payload["type"] == "table"
    assert payload["title"] == "Sales"
    assert payload["columns"] == ["region", "quarter", "amount", "orders"]
    assert len(payload["rows"]) == 5
    assert payload["rows"][0]["region"] == "华东"


def test_to_chart_payload(ctx: SpreadsheetContext) -> None:
    handle_to_chart(
        ToChartOp(kind="to_chart", out="chart", src="sales", chart="bar", x="region", y="amount"),
        ctx,
    )
    payload = ctx.get("chart")
    assert payload["type"] == "chart"
    assert payload["chart"] == "bar"
    assert payload["x"] == "region"
    assert payload["y"] == ["amount"]
