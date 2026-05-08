"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from app.spreadsheet.context import SpreadsheetContext


@pytest.fixture(autouse=True)
def _isolated_session_recorder(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Redirect the durable session recorder to a per-test tmp DB.

    Without this, every analyze/follow-up test would fall through to
    the module-level singleton, which resolves `./data/sessions.db`
    relative to CWD — i.e. `src/backend/data/sessions.db` when pytest
    is invoked from the package root. That:

      * leaks state across runs (a prior test's row would show up in
        `list_sessions` for a later test),
      * litters the working tree with a generated artifact,
      * occasionally fails on CI when two parallel jobs race the file.

    We swap in a fresh `SessionRecorder` per test, then restore `None`
    so the next test gets its own. Tests that need the singleton can
    still call `set_session_recorder()` themselves to override.
    """

    # Lazy import: keeps `app.persistence` out of the critical path of
    # tests that don't touch routes (they'd otherwise pay the import
    # cost and create an empty sqlite file just to stand the fixture up).
    from app.persistence import SessionRecorder, set_session_recorder

    db_path = tmp_path_factory.mktemp("session-rec") / "sessions.db"
    rec = SessionRecorder(db_path=db_path)
    set_session_recorder(rec)
    try:
        yield
    finally:
        set_session_recorder(None)


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
