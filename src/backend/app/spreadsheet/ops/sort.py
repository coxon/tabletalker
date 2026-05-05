"""Sort / head / tail."""

from __future__ import annotations

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import HeadOp, OpResult, SortOp, TailOp


def handle_sort(op: SortOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"sort expects DataFrame at {op.src!r}, got {type(src).__name__}")
    missing = [c for c in op.by if c not in src.columns]
    if missing:
        raise KeyError(f"sort: missing columns {missing}")
    # `desc is None` → all ascending. `desc is []` is rejected at schema
    # validation (see SortOp._desc_matches_by), so we don't fall back here.
    desc = [False] * len(op.by) if op.desc is None else op.desc
    if len(desc) != len(op.by):
        raise ValueError(f"sort: `desc` length {len(desc)} != `by` length {len(op.by)}")
    ascending = [not d for d in desc]
    df = src.sort_values(by=op.by, ascending=ascending).reset_index(drop=True)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="sort", rows=len(df), cols=len(df.columns))


def handle_head(op: HeadOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"head expects DataFrame at {op.src!r}, got {type(src).__name__}")
    df = src.head(op.n).reset_index(drop=True)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="head", rows=len(df), cols=len(df.columns))


def handle_tail(op: TailOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"tail expects DataFrame at {op.src!r}, got {type(src).__name__}")
    df = src.tail(op.n).reset_index(drop=True)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="tail", rows=len(df), cols=len(df.columns))
