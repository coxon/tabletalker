"""Select / filter ops + the expression DSL."""

from __future__ import annotations

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.ops.select import handle_filter_rows, handle_select_columns
from app.spreadsheet.schema import (
    BinOpExpr,
    ColRefExpr,
    FilterRowsOp,
    LiteralExpr,
    SelectColumnsOp,
)


def test_select_columns_keeps_only_named(ctx: SpreadsheetContext) -> None:
    op = SelectColumnsOp(
        kind="select_columns", out="picked", src="sales", columns=["region", "amount"]
    )
    handle_select_columns(op, ctx)
    df = ctx.get("picked")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["region", "amount"]


def test_filter_rows_with_eq(ctx: SpreadsheetContext) -> None:
    where = BinOpExpr(
        op="==",
        args=[ColRefExpr(col="region"), LiteralExpr(lit="华东")],
    )
    op = FilterRowsOp(kind="filter_rows", out="east", src="sales", where=where)
    handle_filter_rows(op, ctx)
    df = ctx.get("east")
    assert len(df) == 2
    assert (df["region"] == "华东").all()


def test_filter_rows_with_compound_and(ctx: SpreadsheetContext) -> None:
    inner_left = BinOpExpr(
        op="==", args=[ColRefExpr(col="region"), LiteralExpr(lit="华东")]
    )
    inner_right = BinOpExpr(
        op=">", args=[ColRefExpr(col="amount"), LiteralExpr(lit=150)]
    )
    where = BinOpExpr(op="and", args=[inner_left, inner_right])
    op = FilterRowsOp(kind="filter_rows", out="big_east", src="sales", where=where)
    handle_filter_rows(op, ctx)
    df = ctx.get("big_east")
    assert len(df) == 1
    assert df.iloc[0]["amount"] == 200
