"""add_column with the expression DSL."""

from __future__ import annotations

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.ops.derive import handle_add_column
from app.spreadsheet.schema import AddColumnOp, BinOpExpr, CallExpr, ColRefExpr, LiteralExpr


def test_add_column_arithmetic(ctx: SpreadsheetContext) -> None:
    expr = BinOpExpr(
        op="*", args=[ColRefExpr(col="amount"), LiteralExpr(lit=2)]
    )
    handle_add_column(
        AddColumnOp(kind="add_column", out="x2", src="sales", name="amount_x2", expr=expr),
        ctx,
    )
    df = ctx.get("x2")
    assert "amount_x2" in df.columns
    assert df["amount_x2"].tolist() == [200, 400, 100, 300, 150]


def test_add_column_call_round(ctx: SpreadsheetContext) -> None:
    avg_per_order = BinOpExpr(
        op="/", args=[ColRefExpr(col="amount"), ColRefExpr(col="orders")]
    )
    rounded = CallExpr(fn="round", args=[avg_per_order, LiteralExpr(lit=2)])
    handle_add_column(
        AddColumnOp(
            kind="add_column", out="apo", src="sales", name="avg_per_order", expr=rounded
        ),
        ctx,
    )
    df = ctx.get("apo")
    assert df["avg_per_order"].iloc[0] == 10.0
