"""Evidence builder — turn an executed Plan into reproducible Evidence rows.

The auto-grader replays each `Evidence` row independently:

  1. Open `dataset/table` as a fresh DataFrame.
  2. Apply `filters` as a pandas predicate.
  3. Run `aggregation` (e.g. `mean(Purchase Amount (USD))`).
  4. Compare the result to `value` and the post-filter row count to
     `row_count`. Mismatch → that finding scored 0.

So every field in `Evidence` has to mirror what would happen in a vanilla
pandas script. This module's job is to walk the typed `Plan` we already
ran and reconstruct that script's worth of bookkeeping: which filters
fired, which aggregations were computed, and what the actual numeric
answers were.

Boundary: this module **never** touches the DataFrames themselves — it
reads `Plan` (structured ops) and the rendered `answer` dict (already
JSON-shape) plus `op_results` (the per-op metadata from the executor).
That keeps it deterministic and trivial to unit-test without a sandbox.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass
from typing import Any

from app.analyze.schema import Evidence
from app.spreadsheet.schema import (
    AggregateOp,
    AggSpec,
    BinOpExpr,
    CallExpr,
    ColRefExpr,
    Expr,
    FilterRowsOp,
    GroupByOp,
    LiteralExpr,
    LoadCsvOp,
    LoadExcelOp,
    OpResult,
    Plan,
)


@dataclass(frozen=True)
class EvidenceContext:
    """Per-request inputs the evidence builder needs but the Plan doesn't carry.

    The submission contract requires `dataset` to equal the directory
    name under `data/public_datasets/`. For free-form uploads (which is
    what `/v1/analyze` accepts) we use the supplied display name — the
    handler decides what that is.

    `sampling_rate` and `sampling_note` are optional and stamped on
    every emitted Evidence row. README §3.3 雷7 / §7.2 #7 makes this
    mandatory whenever the system ran on a downsample — without it the
    auto-grader compares post-filter row_count to the full source and
    judges every Evidence as fabricated. We propagate at the context
    level (not per-Evidence) because a single analyze request runs
    against one DataFrame, so the sampling decision is per-request.
    """

    dataset: str
    table: str
    sampling_rate: float | None = None
    sampling_note: str | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_evidence(
    plan: Plan,
    answer: dict[str, Any],
    op_results: list[OpResult],
    context: EvidenceContext,
) -> list[Evidence]:
    """Build the evidence array for one finding.

    Strategy:
      - Always emit one `count(*)` evidence at the post-filter level so
        the grader can verify the filter itself replays.
      - If the plan also contains an `aggregate` op, emit one Evidence
        per (answer-row x AggSpec). Each evidence's `filters` is the
        AND of the plan's filter clauses with the per-row group-by
        equality clauses; `value` is read straight from the answer cell.
    """

    filter_clause = _render_filters(plan)
    group_keys = _group_keys(plan)
    agg_specs = _aggregations(plan)

    rows: list[Evidence] = []

    filter_total = _post_filter_rows(plan, op_results)
    rows.append(
        Evidence(
            dataset=context.dataset,
            table=context.table,
            columns=_filter_column_names(plan) or _result_columns(answer),
            filters=filter_clause,
            aggregation="count(*)",
            value=filter_total,
            row_count=filter_total,
            sampling_rate=context.sampling_rate,
            sampling_note=context.sampling_note,
        )
    )

    if not agg_specs:
        return rows

    answer_rows = answer.get("rows", []) if answer.get("type") == "table" else []
    for answer_row in answer_rows:
        per_row_clause = _and(
            filter_clause,
            _group_equality_clause(answer_row, group_keys),
        )
        for spec in agg_specs:
            value = answer_row.get(spec.as_)
            if value is None:
                # Skip rows where the LLM dropped the alias column —
                # we can't claim a value we don't have.
                continue
            rows.append(
                Evidence(
                    dataset=context.dataset,
                    table=context.table,
                    columns=_dedupe([spec.column, *group_keys, *_filter_column_names(plan)]),
                    filters=per_row_clause,
                    aggregation=f"{spec.fn}({spec.column})",
                    value=_jsonable(value),
                    row_count=None,  # per-group row count not currently tracked
                    sampling_rate=context.sampling_rate,
                    sampling_note=context.sampling_note,
                )
            )

    return rows


# ---------------------------------------------------------------------------
# Plan walkers
# ---------------------------------------------------------------------------


def _aggregations(plan: Plan) -> list[AggSpec]:
    """Flatten all `AggSpec`s across every aggregate op in the plan."""
    out: list[AggSpec] = []
    for op in plan.ops:
        if isinstance(op, AggregateOp):
            out.extend(op.aggs)
    return out


def _group_keys(plan: Plan) -> list[str]:
    """Concatenated `by` keys from every group_by op (usually one)."""
    keys: list[str] = []
    for op in plan.ops:
        if isinstance(op, GroupByOp):
            keys.extend(op.by)
    return _dedupe(keys)


def _render_filters(plan: Plan) -> str:
    """AND-join every `filter_rows.where` rendered to pandas-style text."""
    clauses = [_render_expr(op.where) for op in plan.ops if isinstance(op, FilterRowsOp)]
    return _and_join(clauses)


def _filter_column_names(plan: Plan) -> list[str]:
    """Verbatim columns referenced inside any filter expression."""
    cols: list[str] = []
    for op in plan.ops:
        if isinstance(op, FilterRowsOp):
            _collect_columns(op.where, cols)
    return _dedupe(cols)


def _post_filter_rows(plan: Plan, op_results: list[OpResult]) -> int:
    """Row count after the *last* filter (or the load, if no filter)."""

    by_out = {r.out: r for r in op_results}

    last_filter_out: str | None = None
    last_load_out: str | None = None
    for op in plan.ops:
        if isinstance(op, FilterRowsOp):
            last_filter_out = op.out
        elif isinstance(op, (LoadCsvOp, LoadExcelOp)):
            last_load_out = op.out

    target = last_filter_out or last_load_out
    if target is None:
        # No filter and no load — extremely degenerate plan. Return zero
        # so we still emit a reproducible Evidence row instead of crashing.
        return 0
    result = by_out.get(target)
    if result is None or result.rows is None:
        return 0
    return int(result.rows)


# ---------------------------------------------------------------------------
# Expression rendering — produce pandas-style predicates the grader can run
# ---------------------------------------------------------------------------


# Map our DSL ops to pandas equivalents. Most are identical; `and`/`or`
# render as `&` / `|` because pandas's vectorised predicates need the
# bitwise form (Python `and`/`or` short-circuits on a Series).
_BINOP_RENDER = {
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "==": "==",
    "!=": "!=",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
    "and": "&",
    "or": "|",
}


# Functions `pandas.eval` / `DataFrame.query` accept directly during
# grader replay — these go through verbatim in the rendered evidence
# string. Other DSL-allowed functions (`lower`, `upper`, `len`, `if`)
# are tolerated by the executor but pandas.eval can't run them as-is;
# the renderer downgrades them to a safe "fn(...)" string form so the
# evidence row stays human-readable without crashing the response.
_CALL_RENDER_ALLOWED = frozenset({"abs", "round", "min", "max"})
# Allowed by the DSL but rendered as best-effort labels rather than
# pandas.eval-replay text. A grader that strictly replays will note the
# function is unrunnable but the surrounding `(dataset, columns,
# filters, aggregation, value, row_count)` tuple still documents what
# the system computed — and the `value` itself is the typed-op result,
# not a re-evaluation of this string. Mirrors the DSL function set in
# `app/spreadsheet/expr.py::_FUNCTIONS`.
_CALL_RENDER_FALLBACK = frozenset({"lower", "upper", "len", "if"})


def _render_expr(expr: Expr) -> str:
    if isinstance(expr, LiteralExpr):
        return _render_literal(expr.lit)
    if isinstance(expr, ColRefExpr):
        return _quote_column(expr.col)
    if isinstance(expr, BinOpExpr):
        left = _render_expr(expr.args[0])
        right = _render_expr(expr.args[1])
        op = _BINOP_RENDER.get(expr.op, expr.op)
        return f"({left} {op} {right})"
    if isinstance(expr, CallExpr):
        rendered = ", ".join(_render_expr(a) for a in expr.args)
        if expr.fn in _CALL_RENDER_ALLOWED:
            return f"{expr.fn}({rendered})"
        if expr.fn in _CALL_RENDER_FALLBACK:
            # DSL-allowed but pandas.eval can't run as-is. Render with a
            # leading `~` marker so it's visually distinct from a
            # replay-faithful call. The Evidence's `value` is still the
            # typed-op result; this string only documents the operation.
            return f"~{expr.fn}({rendered})"
        # Unknown function — DSL validator should have caught it, but
        # if a future op kind grows new function names this defensive
        # branch keeps the response from 500-ing on an unreachable cell.
        return f"~{expr.fn}({rendered})"
    # Closed union — defensive fallback in case Expr grows a new branch
    # and someone forgets to update us.
    raise TypeError(f"unrenderable expression: {type(expr).__name__}")


def _render_literal(value: Any) -> str:
    """SQL-style rendering: bool / number / string. Strings are
    single-quoted with internal apostrophes doubled, matching the form
    most likely to round-trip through the grader."""

    if value is None:
        return "null"
    # Python booleans — `pandas.eval` requires capitalised `True` / `False`,
    # not the lowercased SQL form. Check before `int` because `bool` is
    # an `int` subclass.
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _quote_column(name: str) -> str:
    """Backtick-quote columns that aren't bare identifiers.

    Identifier names render plain (`Age >= 55`); anything containing
    spaces, parens, or non-ASCII gets backtick-quoted to match the spec
    example `mean(Purchase Amount (USD))`. Python keywords (`class`,
    `for`, …) also need quoting so `pandas.eval` doesn't choke on the
    reserved word.
    """

    if name.isidentifier() and not keyword.iskeyword(name):
        return name
    return f"`{name}`"


def _collect_columns(expr: Expr, out: list[str]) -> None:
    if isinstance(expr, ColRefExpr):
        out.append(expr.col)
    elif isinstance(expr, (BinOpExpr, CallExpr)):
        for a in expr.args:
            _collect_columns(a, out)


# ---------------------------------------------------------------------------
# Per-row group equality clauses
# ---------------------------------------------------------------------------


def _group_equality_clause(answer_row: dict[str, Any], group_keys: list[str]) -> str:
    """`(region == '华东') & (quarter == 'Q1')` for one answer row."""

    parts: list[str] = []
    for key in group_keys:
        if key not in answer_row:
            continue
        rendered = _render_literal(answer_row[key])
        parts.append(f"({_quote_column(key)} == {rendered})")
    return " & ".join(parts)


# ---------------------------------------------------------------------------
# Tiny utilities
# ---------------------------------------------------------------------------


def _and(left: str, right: str) -> str:
    return _and_join([s for s in (left, right) if s])


def _and_join(clauses: list[str]) -> str:
    return " & ".join(clauses)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _result_columns(answer: dict[str, Any]) -> list[str]:
    cols = answer.get("columns") or []
    return [str(c) for c in cols]


def _jsonable(value: Any) -> float | int | str:
    """Coerce a numpy / pandas scalar into the (float | int | str) the
    Evidence schema accepts. Booleans are stringified deliberately —
    they're not numeric in any meaningful "value" sense."""

    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return value
    return str(value)
