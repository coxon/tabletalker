"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.spreadsheet.context import SpreadsheetContext


@pytest.fixture
def sales_df() -> pd.DataFrame:
    """Tiny fixture that exercises filter, group, sort, join paths."""
    return pd.DataFrame(
        {
            "region": ["华东", "华东", "华南", "华南", "华北"],
            "quarter": ["Q1", "Q2", "Q1", "Q2", "Q1"],
            "amount": [100, 200, 50, 150, 75],
            "orders": [10, 20, 5, 15, 7],
        }
    )


@pytest.fixture
def regions_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["华东", "华南", "华北"],
            "manager": ["Alice", "Bob", "Carol"],
        }
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def ctx(workspace: Path, sales_df: pd.DataFrame) -> SpreadsheetContext:
    """Context pre-populated with a `sales` register slot."""
    c = SpreadsheetContext(workspace=workspace)
    c.put("sales", sales_df)
    return c
