"""Profiler — fast, deterministic table profile. No LLM in the loop.

The spreadsheet planner is given a 5-row preview today (see
`app.spreadsheet.planner._user_message`). That's enough to write a
plan, but the *analyze* handler needs more:

- Total row count → goes into every `Evidence.row_count` we emit.
- Column dtype kind (`numeric`/`categorical`/`datetime`/`text`/`bool`) →
  lets the handler decide whether a refusal is warranted (e.g. the
  question asks for `mean(City)`).
- NA fraction → flags columns the planner shouldn't aggregate naïvely.
- Distinct counts and top values for low-cardinality columns → useful
  for refusal heuristics ("filter by Race" but Race isn't here).

We deliberately produce a typed Pydantic object, not a free-form dict,
so downstream code (`evidence.py`, `handler.py`) can rely on attribute
access and `extra="forbid"` keeps schema drift loud.

This module is also where a future PR adds basic semantic guesses
(e.g. "this column looks like an ISO date") — keeping that logic out of
the planner means the LLM only sees the resulting *labels*, not our
heuristic spaghetti.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

# Files larger than this on disk get rejected up-front rather than
# silently profiled with a slow `read_csv`. The upload cap in
# `app.api.spreadsheet` is 20 MiB; we mirror that here so this module
# is honest when called outside the HTTP path (tests, scripts).
MAX_PROFILE_BYTES = 20 * 1024 * 1024

# Cap on how many distinct values we enumerate per column. Anything
# above this gets reported as "high cardinality" without a sample, both
# to keep responses small and to avoid leaking PII-ish full enumerations
# into prompts.
TOP_VALUES_LIMIT = 10
HIGH_CARDINALITY_THRESHOLD = 50


DtypeKind = Literal["numeric", "categorical", "datetime", "boolean", "text"]


class _StrictModel(BaseModel):
    """Reject unknown fields — the profile is consumed by code, not free text."""

    model_config = {"extra": "forbid"}


class ValueCount(_StrictModel):
    """One (value, count) pair for top-values enumeration."""

    value: str  # stringified — JSON-safe and prompt-safe
    count: int


class ColumnProfile(_StrictModel):
    """Per-column shape + a small sample of values.

    `name` is verbatim from the file header (with whatever spaces /
    parens / mixed-language characters the source used) — that's the
    string the auto-grader expects in `Evidence.columns`, so we never
    munge it.
    """

    name: str
    dtype_kind: DtypeKind
    pandas_dtype: str = Field(..., description="The raw pandas dtype string, for diagnostics.")
    non_null: int
    na_count: int
    na_fraction: float = Field(..., ge=0.0, le=1.0)
    distinct: int = Field(..., ge=0)
    high_cardinality: bool = Field(
        ...,
        description=(
            f"True when distinct > {HIGH_CARDINALITY_THRESHOLD}; "
            "downstream code should treat this column as identifier-like."
        ),
    )
    top_values: list[ValueCount] = Field(
        default_factory=list,
        description=(
            "Up to TOP_VALUES_LIMIT most-frequent values. "
            "Empty for high-cardinality or numeric-continuous columns."
        ),
    )
    minimum: float | None = Field(
        default=None, description="Only set for numeric columns."
    )
    maximum: float | None = Field(
        default=None, description="Only set for numeric columns."
    )


class TableProfile(_StrictModel):
    """Whole-file profile: shape + per-column profiles."""

    filename: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]


class ProfilerError(Exception):
    """Raised when the file can't be profiled (too big, unreadable, etc.)."""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def profile_table(path: Path) -> TableProfile:
    """Read a CSV / Excel file and produce a `TableProfile`.

    Reads the file fully (subject to MAX_PROFILE_BYTES). The upload path
    has already capped the size; profiling a 20 MiB CSV is well under a
    second on a laptop and gives us exact row counts for evidence.
    """

    if not path.exists():
        raise ProfilerError(f"file not found: {path}")
    size = path.stat().st_size
    if size > MAX_PROFILE_BYTES:
        raise ProfilerError(
            f"file too large to profile: {size} bytes > {MAX_PROFILE_BYTES}"
        )

    df = _read_full(path)
    return _profile_dataframe(df, filename=path.name)


def _read_full(path: Path) -> pd.DataFrame:
    """Read the whole file — encoding/sheet defaults match the engine."""

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(path)
    except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ProfilerError(f"could not parse {path.name}: {exc}") from exc
    raise ProfilerError(
        f"unsupported file extension {suffix!r}; need .csv / .xlsx / .xls"
    )


def _profile_dataframe(df: pd.DataFrame, *, filename: str) -> TableProfile:
    columns = [_profile_column(df, str(name)) for name in df.columns]
    return TableProfile(
        filename=filename,
        row_count=len(df),
        column_count=int(df.shape[1]),
        columns=columns,
    )


# ---------------------------------------------------------------------------
# Per-column logic
# ---------------------------------------------------------------------------


def _profile_column(df: pd.DataFrame, name: str) -> ColumnProfile:
    series = df[name]
    pandas_dtype = str(series.dtype)
    kind = _classify_dtype(series)

    total = len(series)
    na_count = int(series.isna().sum())
    non_null = total - na_count
    # `total == 0` happens for empty CSVs; reporting a nonzero NA fraction
    # there would be a lie. Profile the empty file honestly instead.
    na_fraction = (na_count / total) if total else 0.0
    distinct = int(series.nunique(dropna=True))

    high_card = distinct > HIGH_CARDINALITY_THRESHOLD

    top_values = _top_values(series, kind, high_card)
    minimum, maximum = _numeric_extents(series, kind)

    return ColumnProfile(
        name=name,
        dtype_kind=kind,
        pandas_dtype=pandas_dtype,
        non_null=non_null,
        na_count=na_count,
        na_fraction=na_fraction,
        distinct=distinct,
        high_cardinality=high_card,
        top_values=top_values,
        minimum=minimum,
        maximum=maximum,
    )


def _classify_dtype(series: pd.Series) -> DtypeKind:
    """Bucket a pandas dtype into one of our five label kinds.

    The labels are deliberately coarse — the planner doesn't need to
    distinguish int32 from int64, but it *does* need to know "this is a
    number" vs "this is a category" vs "this is free text".
    """

    dtype = series.dtype
    # `bool` first because it's a subclass of integer in numpy and would
    # otherwise be misclassified as numeric.
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_numeric_dtype(dtype):
        return "numeric"
    if isinstance(dtype, pd.CategoricalDtype):
        return "categorical"

    # For string-ish columns we use distinct count as a proxy: low
    # cardinality → categorical, high cardinality → free text. We accept
    # both legacy `object` dtype (default for `pd.read_csv` on older
    # pandas) and the Arrow-backed `string` / `StringDtype` newer pandas
    # produces so the classification is stable across pandas builds.
    # The threshold matches our top-values cutoff so the planner sees
    # consistent signals.
    if pd.api.types.is_object_dtype(dtype) or pd.api.types.is_string_dtype(dtype):
        non_null = series.dropna()
        if non_null.empty:
            return "text"
        distinct = int(non_null.nunique())
        return "categorical" if distinct <= HIGH_CARDINALITY_THRESHOLD else "text"

    # Anything else (timedelta, complex, …) — we don't pretend to know.
    return "text"


def _top_values(
    series: pd.Series, kind: DtypeKind, high_cardinality: bool
) -> list[ValueCount]:
    """Most-frequent values for low-cardinality categorical/boolean columns."""

    if high_cardinality:
        return []
    if kind not in ("categorical", "boolean"):
        # Numeric / datetime / text top-values would be misleading: the
        # mode of a continuous numeric column says nothing useful, and
        # text columns are by definition high-cardinality (or were
        # already reclassified as categorical above).
        return []
    counts = series.dropna().value_counts().head(TOP_VALUES_LIMIT)
    return [ValueCount(value=str(idx), count=int(cnt)) for idx, cnt in counts.items()]


def _numeric_extents(
    series: pd.Series, kind: DtypeKind
) -> tuple[float | None, float | None]:
    """min / max for numeric columns; (None, None) otherwise."""

    if kind != "numeric":
        return None, None
    non_null = series.dropna()
    if non_null.empty:
        return None, None
    mn = float(non_null.min())
    mx = float(non_null.max())
    # Guard against NaN/Inf from pathological CSVs — emit None rather
    # than letting non-JSON-safe floats reach the response.
    if not math.isfinite(mn) or not math.isfinite(mx):
        return None, None
    return mn, mx
