"""Join — DataFrame ⋈ DataFrame on shared keys."""

from __future__ import annotations

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import JoinOp, OpResult


def handle_join(op: JoinOp, ctx: SpreadsheetContext) -> OpResult:
    left = ctx.get(op.left)
    right = ctx.get(op.right)
    if not isinstance(left, pd.DataFrame):
        raise TypeError(f"join.left expects DataFrame at {op.left!r}, got {type(left).__name__}")
    if not isinstance(right, pd.DataFrame):
        raise TypeError(f"join.right expects DataFrame at {op.right!r}, got {type(right).__name__}")

    missing_left = [c for c in op.on if c not in left.columns]
    missing_right = [c for c in op.on if c not in right.columns]
    if missing_left or missing_right:
        raise KeyError(
            f"join: missing keys {missing_left} on left, {missing_right} on right"
        )

    df = left.merge(right, on=op.on, how=op.how)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="join", rows=len(df), cols=len(df.columns))
