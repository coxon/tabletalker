"""JSON-column explode op — TMDB `genres` / `cast` / `crew` and similar.

The TMDB dataset (and many real-world CSV exports) stores nested data as
JSON-encoded strings in a single column. Aggregations against the raw
string yield nonsense ("each row is its own genre"); the contract calls
out this exact case in `docs/refusal-policy.md` / 赛题4 README §7.2 雷 4.

`explode_json` parses the JSON in `column` and unrolls it. Two modes:

  - With `extract` set: each parsed dict becomes a single scalar value
    (the named field from the JSON object). Useful for "list of names":
    `[{"name":"Action"},{"name":"Comedy"}]` + extract="name" → ["Action",
    "Comedy"], then exploded → 2 rows per movie.

  - Without `extract`: the column is exploded as-is. Each list element
    becomes its own row; if elements are dicts they are JSON-roundtripped
    so downstream string ops still work, but the typical use case pairs
    extract with this so the planner usually sets it.

Failure modes:

  - Non-JSON cells (`null`, empty string, malformed JSON) are dropped
    silently per row — the planner's intent is "look at the structured
    data when it's there"; raising on the first malformed row would 422
    the whole analysis.
  - If `column` doesn't exist on the input → KeyError (caught by the
    executor and surfaced as 422 with column suggestions).
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import ExplodeJsonOp, OpResult


def handle_explode_json(op: ExplodeJsonOp, ctx: SpreadsheetContext) -> OpResult:
    src = ctx.get(op.src)
    if not isinstance(src, pd.DataFrame):
        raise TypeError(
            f"explode_json expects DataFrame at {op.src!r}, got {type(src).__name__}"
        )
    if op.column not in src.columns:
        raise KeyError(
            f"explode_json: column {op.column!r} not in source "
            f"(have: {list(src.columns)[:8]}...)"
        )

    parsed = src[op.column].apply(_parse_cell)

    if op.extract is not None:
        # Extract a named field from each list element (or from a single
        # dict). Lists become lists-of-extracted-values; dicts collapse to
        # a single scalar; failures (missing key, wrong shape) become None
        # and are dropped on explode.
        # Bind to a local so pyright sees `extract_field: str` inside the
        # lambda — `op.extract` is `str | None` and the type narrowing
        # from the `is not None` check above doesn't follow the closure.
        extract_field: str = op.extract
        parsed = parsed.apply(lambda v: _extract_field(v, extract_field))

    df = src.copy()
    df[op.column] = parsed

    # explode() takes a list-shaped column and produces one row per element.
    # Scalars (dict cells without `extract`, or single dict from extract)
    # stay as a single row. Drop nulls so malformed rows don't pollute the
    # downstream aggregation.
    df = df.explode(op.column).reset_index(drop=True)
    df = df.dropna(subset=[op.column]).reset_index(drop=True)

    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="explode_json", rows=len(df), cols=len(df.columns))


def _parse_cell(value: Any) -> Any:
    """Parse a JSON-encoded cell.

    Returns:
      - list / dict on successful parse,
      - the original value if it's already list/dict (some sources read in
        as parsed Python literals when pandas is lenient),
      - `None` for empty / malformed / non-string inputs.
    """

    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text in ("null", "NaN"):
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _extract_field(value: Any, field: str) -> Any:
    """Pull `field` from each dict in `value`.

    Cases:
      - value is a list of dicts → list of `dict[field]` (skip dicts that
        lack the field rather than raising — partial lists are normal).
      - value is a dict → `dict.get(field)` (or None).
      - value is anything else → None.
    """

    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            if isinstance(item, dict) and field in item:
                out.append(item[field])
        return out if out else None
    if isinstance(value, dict):
        return value.get(field)
    return None
