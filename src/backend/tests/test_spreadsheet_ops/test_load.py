"""Load ops — CSV/Excel ingestion + path-escape rejection."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from app.spreadsheet.context import SpreadsheetContext, SpreadsheetContextError
from app.spreadsheet.ops.load import handle_load_csv, handle_load_excel
from app.spreadsheet.schema import LoadCsvOp, LoadExcelOp


def test_load_csv_reads_file(workspace: Path) -> None:
    csv = workspace / "data.csv"
    csv.write_text("a,b\n1,2\n3,4\n")
    ctx = SpreadsheetContext(workspace=workspace)

    result = handle_load_csv(LoadCsvOp(kind="load_csv", out="df", path="data.csv"), ctx)

    assert result.rows == 2
    assert result.cols == 2
    assert isinstance(ctx.get("df"), pd.DataFrame)


def test_load_csv_rejects_path_escape(workspace: Path) -> None:
    ctx = SpreadsheetContext(workspace=workspace)
    op = LoadCsvOp(kind="load_csv", out="df", path="../../../etc/passwd")
    with pytest.raises(SpreadsheetContextError, match="escapes workspace"):
        handle_load_csv(op, ctx)


def test_load_excel_reads_first_sheet(workspace: Path) -> None:
    xlsx = workspace / "data.xlsx"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_excel(xlsx, index=False)
    ctx = SpreadsheetContext(workspace=workspace)

    result = handle_load_excel(
        LoadExcelOp(kind="load_excel", out="df", path="data.xlsx"), ctx
    )

    assert result.rows == 2
    assert result.cols == 2


def test_legacy_xls_engine_is_installed() -> None:
    """The upload path accepts .xls, so pandas must have the legacy engine."""

    pytest.importorskip("xlrd")
