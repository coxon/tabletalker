"""Pivot / melt — wide ↔ long reshapes."""

from __future__ import annotations

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import MeltOp, OpResult, PivotOp


def handle_pivot(op: PivotOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"pivot expects DataFrame at {op.src!r}, got {type(src).__name__}")

    needed = set(op.index) | {op.columns, op.values}
    missing = [c for c in needed if c not in src.columns]
    if missing:
        raise KeyError(f"pivot: missing columns {missing}")

    df = src.pivot_table(
        index=op.index, columns=op.columns, values=op.values, aggfunc=op.aggfn
    ).reset_index()
    # Flatten any MultiIndex columns the pivot produced. We iterate
    # `list(df.columns)` rather than `to_flat_index()` because
    # pandas-stubs types the latter narrowly when the index is plain.
    flattened: list[str] = []
    for c in list(df.columns):
        if isinstance(c, tuple):
            flattened.append("_".join(str(part) for part in c if part != ""))
        else:
            flattened.append(str(c))
    df.columns = pd.Index(flattened)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="pivot", rows=len(df), cols=len(df.columns))


def handle_melt(op: MeltOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"melt expects DataFrame at {op.src!r}, got {type(src).__name__}")
    df = src.melt(
        id_vars=op.id_vars,
        value_vars=op.value_vars,
        var_name=op.var_name,
        value_name=op.value_name,
    )
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="melt", rows=len(df), cols=len(df.columns))
