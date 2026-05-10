"""Group-by + aggregate.

We split into two ops (vs a single `group_agg`) because:
  - the LLM finds it easier to express grouping and aggregation
    separately ("group by region, then sum amount and count orders");
  - the register can hold a `GroupBy` object so a single grouping can
    feed into multiple aggregations without re-grouping.
"""

from __future__ import annotations

import pandas as pd

# `pandas.api.typing` is the public re-export of internal type aliases
# (since pandas 2.1). Avoid reaching into `pandas.core.*` — that's the
# private namespace and can move between minor versions.
from pandas.api.typing import DataFrameGroupBy

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import AggregateOp, GroupByOp, OpResult


def handle_group_by(op: GroupByOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"group_by expects DataFrame at {op.src!r}, got {type(src).__name__}")
    missing = [c for c in op.by if c not in src.columns]
    if missing:
        raise KeyError(f"group_by: missing columns {missing}")
    grouped = src.groupby(op.by, dropna=False)
    ctx.put(op.out, grouped)
    return OpResult(
        out=op.out,
        kind="group_by",
        rows=None,
        cols=None,
        extra={"by": op.by, "groups": grouped.ngroups},
    )


def handle_aggregate(op: AggregateOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if isinstance(src, DataFrameGroupBy):
        # Build a {output_name: (column, fn)} dict for `.agg(**kwargs)`.
        named_aggs = {a.as_: (a.column, a.fn) for a in op.aggs}
        df = src.agg(**named_aggs).reset_index()
    elif isinstance(src, pd.DataFrame):
        # Whole-frame aggregate. This covers common planner output such as:
        # filter rows -> aggregate count/mean -> to_table. Forcing the LLM
        # to invent a dummy group key is brittle and adds no analytical value.
        row = {a.as_: _aggregate_series(src[a.column], a.fn) for a in op.aggs}
        df = pd.DataFrame([row])
    else:
        raise TypeError(
            f"aggregate expects DataFrame or GroupBy at {op.src!r}, got "
            f"{type(src).__name__}"
        )
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="aggregate", rows=len(df), cols=len(df.columns))


def _aggregate_series(series: pd.Series, fn: str) -> object:
    if fn == "sum":
        return series.sum()
    if fn == "mean":
        return series.mean()
    if fn == "count":
        return series.count()
    if fn == "min":
        return series.min()
    if fn == "max":
        return series.max()
    if fn == "median":
        return series.median()
    if fn == "nunique":
        return series.nunique(dropna=True)
    raise ValueError(f"unsupported aggregate fn {fn!r}")
