"""Output ops — render the final answer.

`to_table` and `to_chart` don't transform data; they tag a register
slot as "this is the user-facing answer in this format". The executor
uses the resulting register entry to build the API response.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import OpResult, ToChartOp, ToTableOp


def handle_to_table(op: ToTableOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"to_table expects DataFrame at {op.src!r}, got {type(src).__name__}")
    payload: dict[str, Any] = {
        "type": "table",
        "title": op.title,
        # Stringify column labels so they line up with the str-keyed row dicts
        # produced by `_df_to_records`. Without this a tuple/int label would
        # appear in `columns` but never in `rows`, breaking client renderers.
        "columns": [str(c) for c in src.columns],
        "rows": _df_to_records(src),
    }
    ctx.put(op.out, payload)
    return OpResult(out=op.out, kind="to_table", rows=len(src), cols=len(src.columns))


def handle_to_chart(op: ToChartOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(f"to_chart expects DataFrame at {op.src!r}, got {type(src).__name__}")
    y_cols = [op.y] if isinstance(op.y, str) else list(op.y)
    if not y_cols:
        raise ValueError("to_chart: `y` must reference at least one column")
    needed = [op.x, *y_cols]
    missing = [c for c in needed if c not in src.columns]
    if missing:
        raise KeyError(f"to_chart: missing columns {missing}")
    payload: dict[str, Any] = {
        "type": "chart",
        "chart": op.chart,
        "title": op.title,
        "x": op.x,
        "y": y_cols,
        "rows": _df_to_records(src[[op.x, *y_cols]]),
    }
    ctx.put(op.out, payload)
    return OpResult(out=op.out, kind="to_chart", rows=len(src), cols=len(needed))


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """JSON-safe records — coerce numpy scalars and NaN to plain Python.

    `orient="records"` keeps numpy scalar types; FastAPI's encoder copes
    with most of them but NaN turns into invalid JSON. Replace NaN with
    None first, then convert.
    """
    # `mask(cond, None)` flips NaN cells to None across mixed dtypes safely.
    cleaned = df.astype(object).mask(df.isna(), other=None)
    records = cleaned.to_dict(orient="records")
    # `to_dict` annotates keys as `Hashable`; in practice they are str column
    # names. Coerce so the response shape stays predictable.
    return [{str(k): v for k, v in row.items()} for row in records]
