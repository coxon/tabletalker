"""Join — DataFrame ⋈ DataFrame on shared keys.

Supports both symmetric joins (`on=[...]`) and asymmetric joins
(`left_on=[...]` + `right_on=[...]`). The asymmetric path is the one TMDB
needs: `movies.csv` keys on `id`, `credits.csv` keys on `movie_id`. When
either path can't find a referenced key, the error message lists the
available column names plus a fuzzy-similarity hint so the planner (or
debugger) sees the rename target.
"""

from __future__ import annotations

import difflib

import pandas as pd

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.schema import JoinOp, OpResult


def handle_join(op: JoinOp, ctx: SpreadsheetContext) -> OpResult:
    left = ctx.get(op.left)
    right = ctx.get(op.right)
    if not isinstance(left, pd.DataFrame):
        raise TypeError(f"join.left expects DataFrame at {op.left!r}, got {type(left).__name__}")
    if not isinstance(right, pd.DataFrame):
        raise TypeError(f"join.right expects DataFrame at {op.right!r}, got {type(right).__name__}")

    # Schema validator already guarantees exactly one of (on) or
    # (left_on, right_on) is supplied; resolve to the merge() kwargs here.
    if op.on:
        left_keys = right_keys = list(op.on)
    else:
        left_keys = list(op.left_on)
        right_keys = list(op.right_on)

    missing_left = [c for c in left_keys if c not in left.columns]
    missing_right = [c for c in right_keys if c not in right.columns]
    if missing_left or missing_right:
        hints: list[str] = []
        for col in missing_left:
            suggestion = _suggest(col, list(left.columns))
            if suggestion:
                hints.append(f"left.{col!r} → did you mean {suggestion!r}?")
        for col in missing_right:
            suggestion = _suggest(col, list(right.columns))
            if suggestion:
                hints.append(f"right.{col!r} → did you mean {suggestion!r}?")
        hint_str = ("; " + "; ".join(hints)) if hints else ""
        raise KeyError(
            f"join: missing keys {missing_left} on left "
            f"(have: {list(left.columns)[:8]}...), "
            f"{missing_right} on right "
            f"(have: {list(right.columns)[:8]}...). "
            f"If left and right name the same concept differently, use "
            f"`left_on` + `right_on` instead of `on`{hint_str}"
        )

    # Keep left-hand column names stable. Pandas' default `_x`/`_y` suffixes
    # make later planner steps brittle when both sides share a measure name.
    if op.on:
        df = left.merge(right, on=left_keys, how=op.how, suffixes=("", "_right"))
    else:
        df = left.merge(
            right,
            left_on=left_keys,
            right_on=right_keys,
            how=op.how,
            suffixes=("", "_right"),
        )
    ctx.put(op.out, df)
    return OpResult(out=op.out, kind="join", rows=len(df), cols=len(df.columns))


def _suggest(missing: str, available: list[str]) -> str | None:
    """Best fuzzy match for `missing` among `available` (or None).

    Used to nudge the planner toward the correct key name when it asks for
    `id` on a table that only has `movie_id`. Cutoff 0.6 is permissive
    enough to catch substring matches like that without falsely matching
    unrelated columns ("budget" → "revenue" is below threshold).
    """

    matches = difflib.get_close_matches(missing, available, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    # Substring fallback: catches `id` ↔ `movie_id` which difflib rates
    # too low (one is a prefix of the other but very short). Only fire when
    # the missing key length is ≥2 to avoid matching arbitrary `i` / `o`.
    if len(missing) >= 2:
        for col in available:
            if missing in col or col in missing:
                return col
    return None
