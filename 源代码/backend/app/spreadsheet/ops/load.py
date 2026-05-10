"""Load ops — CSV and Excel ingestion.

These are the only ops that touch the filesystem. All paths are
resolved through `SpreadsheetContext.resolve_path()` which refuses
escapes from the workspace dir.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import LoadCsvOp, LoadExcelOp, OpResult


def handle_load_csv(op: LoadCsvOp, ctx: SpreadsheetContext) -> OpResult:
    path = ctx.resolve_path(op.path)
    df = pd.read_csv(path)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="load_csv", rows=len(df), cols=len(df.columns))


def handle_load_excel(op: LoadExcelOp, ctx: SpreadsheetContext) -> OpResult:
    path = ctx.resolve_path(op.path)
    # `read_excel` can return DataFrame | dict[Hashable, DataFrame] | np.ndarray
    # depending on the `sheet_name` value. We always pass a single sheet
    # so the dict variant only fires when the user passes `None` (we
    # don't expose that today). Force the result back to DataFrame.
    raw: Any = pd.read_excel(path, sheet_name=op.sheet)
    if isinstance(raw, dict):
        df = cast(pd.DataFrame, next(iter(raw.values())))
    else:
        df = cast(pd.DataFrame, raw)
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="load_excel", rows=len(df), cols=len(df.columns))
