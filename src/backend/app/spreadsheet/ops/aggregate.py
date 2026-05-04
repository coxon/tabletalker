"""Group-by + aggregate.

We split into two ops (vs a single `group_agg`) because:
  - the LLM finds it easier to express grouping and aggregation
    separately ("group by region, then sum amount and count orders");
  - the register can hold a `GroupBy` object so a single grouping can
    feed into multiple aggregations without re-grouping.
"""

from __future__ import annotations

import pandas as pd
from pandas.core.groupby.generic import DataFrameGroupBy

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
    grouped = ctx.get(op.src)
    if not isinstance(grouped, DataFrameGroupBy):
        raise TypeError(
            f"aggregate expects a GroupBy at {op.src!r}, got {type(grouped).__name__}; "
            "did you forget a `group_by` op upstream?"
        )

    # Build a {output_name: (column, fn)} dict for `.agg(**kwargs)`.
    named_aggs = {a.as_: (a.column, a.fn) for a in op.aggs}
    df = grouped.agg(**named_aggs).reset_index()
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="aggregate", rows=len(df), cols=len(df.columns))
