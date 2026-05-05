"""Profiler unit tests — no LLM, no network."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.analyze.profiler import (
    HIGH_CARDINALITY_THRESHOLD,
    MAX_PROFILE_BYTES,
    ProfilerError,
    TableProfile,
    profile_table,
)


def _write_csv(workspace: Path, df: pd.DataFrame, name: str = "data.csv") -> Path:
    path = workspace / name
    df.to_csv(path, index=False)
    return path


def test_profile_classifies_kinds_for_typical_table(workspace: Path) -> None:
    """One row each: numeric / categorical / boolean — covers the dispatch."""

    path = _write_csv(
        workspace,
        pd.DataFrame(
            {
                "Age": [25, 30, 55, 60, 65],
                "City": ["Beijing", "Beijing", "Shanghai", "Shanghai", "Shanghai"],
                "Active": [True, False, True, True, False],
            }
        ),
    )
    profile = profile_table(path)

    assert isinstance(profile, TableProfile)
    assert profile.row_count == 5
    assert profile.column_count == 3
    by_name = {c.name: c for c in profile.columns}

    assert by_name["Age"].dtype_kind == "numeric"
    assert by_name["Age"].minimum == 25.0
    assert by_name["Age"].maximum == 65.0
    # numeric columns intentionally don't enumerate top values — the mode
    # of a continuous variable is rarely informative for the planner.
    assert by_name["Age"].top_values == []

    assert by_name["City"].dtype_kind == "categorical"
    top = {(v.value, v.count) for v in by_name["City"].top_values}
    assert top == {("Beijing", 2), ("Shanghai", 3)}

    assert by_name["Active"].dtype_kind == "boolean"
    # bool dtype gets numeric-ish min/max in numpy land — we explicitly
    # don't expose those: the contract says min/max is for numerics.
    assert by_name["Active"].minimum is None
    assert by_name["Active"].maximum is None


def test_profile_preserves_verbatim_chinese_header(workspace: Path) -> None:
    """Auto-grader compares column names byte-for-byte; the profile must
    not normalise / strip Chinese, parentheses, or spaces."""

    path = _write_csv(
        workspace,
        pd.DataFrame({"客单价 (USD)": [10.0, 20.5, 30.25]}),
    )
    profile = profile_table(path)
    assert profile.columns[0].name == "客单价 (USD)"


def test_profile_reports_na_count_and_fraction(workspace: Path) -> None:
    path = _write_csv(
        workspace,
        pd.DataFrame({"score": [1.0, None, 3.0, None, 5.0]}),
    )
    profile = profile_table(path)
    score = profile.columns[0]
    assert score.na_count == 2
    assert score.non_null == 3
    assert score.na_fraction == pytest.approx(0.4)


def test_profile_marks_high_cardinality(workspace: Path) -> None:
    """A unique-id column is high-cardinality → no top_values."""

    n = HIGH_CARDINALITY_THRESHOLD + 5
    path = _write_csv(
        workspace,
        pd.DataFrame({"id": [f"u{i:04d}" for i in range(n)]}),
    )
    profile = profile_table(path)
    col = profile.columns[0]
    assert col.dtype_kind == "text"
    assert col.high_cardinality is True
    assert col.top_values == []
    assert col.distinct == n


def test_profile_rejects_oversize_file(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Oversize files fail before pandas reads them — protects callers
    that bypass the HTTP upload cap (tests, scripts)."""

    # Shrink the cap rather than synthesising a huge file: same code path,
    # 0.001s instead of writing 20 MiB.
    monkeypatch.setattr("app.analyze.profiler.MAX_PROFILE_BYTES", 5)
    path = _write_csv(workspace, pd.DataFrame({"x": [1, 2, 3]}))
    assert path.stat().st_size > 5  # sanity: the trimmed cap is actually exceeded
    with pytest.raises(ProfilerError, match="too large"):
        profile_table(path)


def test_profile_rejects_unsupported_extension(workspace: Path) -> None:
    bad = workspace / "data.parquet"
    bad.write_bytes(b"PAR1")  # any bytes — we never reach the parser
    with pytest.raises(ProfilerError, match="unsupported"):
        profile_table(bad)


def test_profile_rejects_missing_file(workspace: Path) -> None:
    with pytest.raises(ProfilerError, match="not found"):
        profile_table(workspace / "no-such.csv")


def test_profile_handles_empty_csv(workspace: Path) -> None:
    """Pandas raises EmptyDataError on a header-less empty file; we map
    it to a clean ProfilerError so the API path can return a 422."""

    empty = workspace / "empty.csv"
    empty.write_text("")  # zero bytes
    with pytest.raises(ProfilerError):
        profile_table(empty)


def test_profile_caps_top_values(workspace: Path) -> None:
    """Even a low-cardinality column shouldn't dump dozens of values into
    the prompt — TOP_VALUES_LIMIT bounds the list at 10."""

    # 12 distinct values (still ≤ HIGH_CARDINALITY_THRESHOLD) so the
    # high-cardinality short-circuit doesn't fire.
    values = [f"cat{i}" for i in range(12)] * 2
    path = _write_csv(workspace, pd.DataFrame({"category": values}))
    profile = profile_table(path)
    col = profile.columns[0]
    assert col.dtype_kind == "categorical"
    assert col.high_cardinality is False
    assert len(col.top_values) == 10


def test_max_profile_bytes_matches_upload_cap() -> None:
    """If the upload cap moves but the profile cap doesn't (or vice
    versa) the API path could ingest a file the profiler then refuses.
    Lock the two together with an explicit assertion."""

    from app.api.spreadsheet import MAX_UPLOAD_BYTES

    assert MAX_PROFILE_BYTES == MAX_UPLOAD_BYTES
