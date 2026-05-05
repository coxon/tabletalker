"""Derived columns via the tiny expression DSL."""

from __future__ import annotations

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.expr import evaluate
from app.spreadsheet.schema import AddColumnOp, OpResult


def handle_add_column(op: AddColumnOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"add_column expects DataFrame at {op.src!r}, got {type(src).__name__}")
    if op.name in src.columns:
        raise ValueError(
            f"add_column would overwrite existing column {op.name!r}; "
            "rename the new column or drop the original first"
        )
    value = evaluate(op.expr, src)
    df = src.copy()
    df[op.name] = value
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="add_column", rows=len(df), cols=len(df.columns))
