"""Select / filter ops."""

from __future__ import annotations

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.expr import evaluate
from app.spreadsheet.schema import FilterRowsOp, OpResult, SelectColumnsOp


def handle_select_columns(op: SelectColumnsOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"select_columns expects DataFrame at {op.src!r}, got {type(src).__name__}")
    missing = [c for c in op.columns if c not in src.columns]
    if missing:
        raise KeyError(f"select_columns: missing columns {missing}")
    df = src[op.columns].copy()
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="select_columns", rows=len(df), cols=len(df.columns))


def handle_filter_rows(op: FilterRowsOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"filter_rows expects DataFrame at {op.src!r}, got {type(src).__name__}")
    mask = evaluate(op.where, src)
    if not isinstance(mask, pd.Series):
        raise TypeError(f"filter_rows: `where` must produce a Series, got {type(mask).__name__}")
    if len(mask) != len(src):
        raise ValueError(
            f"filter_rows: `where` produced length {len(mask)}, expected {len(src)}"
        )
    # Coerce nullable boolean / float masks to a strict bool (NA → False).
    # Without this, a column with NaN compared to a literal returns Boolean
    # dtype with <NA> entries that pandas refuses to use for indexing.
    bool_mask = mask.fillna(False).astype(bool)
    df = src[bool_mask].reset_index(drop=True)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="filter_rows", rows=len(df), cols=len(df.columns))
