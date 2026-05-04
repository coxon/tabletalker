"""Expression evaluator for the tiny `add_column` / `filter_rows` DSL.

The DSL is defined in `schema.py`. This module turns an `Expr` tree into
a vectorised pandas `Series` (or scalar). We deliberately do NOT use
`DataFrame.eval` / `pd.eval` — those parse strings, which is exactly the
attack surface we're avoiding.

Supported nodes: Literal, ColRef, BinOp, Call. Whitelists for ops and
fns are enforced in `schema.py`; this module assumes a validated tree
and only enforces *runtime* shape (e.g. column existence, arity).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.spreadsheet.schema import (
    BinOpExpr,
    CallExpr,
    ColRefExpr,
    Expr,
    LiteralExpr,
)


class ExprError(Exception):
    """Runtime expression problem (unknown column, bad arity, etc.)."""


def evaluate(expr: Expr, df: pd.DataFrame) -> Any:
    """Evaluate `expr` over `df`. Returns a Series (vector) or a scalar.

    The caller decides what to do with the result — `add_column` assigns
    it as a new column, `filter_rows` uses it as a boolean mask.
    """

    if isinstance(expr, LiteralExpr):
        return expr.lit

    if isinstance(expr, ColRefExpr):
        if expr.col not in df.columns:
            raise ExprError(f"column {expr.col!r} not found; have {list(df.columns)}")
        return df[expr.col]

    if isinstance(expr, BinOpExpr):
        if len(expr.args) != 2:
            raise ExprError(f"binop {expr.op!r} requires 2 args, got {len(expr.args)}")
        left = evaluate(expr.args[0], df)
        right = evaluate(expr.args[1], df)
        return _apply_binop(expr.op, left, right)

    if isinstance(expr, CallExpr):
        args = [evaluate(a, df) for a in expr.args]
        return _apply_fn(expr.fn, args)

    raise ExprError(f"unknown expression node: {type(expr).__name__}")


def _apply_binop(op: str, left: Any, right: Any) -> Any:
    # pandas Series operators are vectorised — works for both Series×Series
    # and Series×scalar.
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        return left / right
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "and":
        return left & right
    if op == "or":
        return left | right
    raise ExprError(f"unhandled binop {op!r}")  # schema should have caught this


def _apply_fn(fn: str, args: list[Any]) -> Any:
    if fn == "abs":
        _check_arity(fn, args, 1)
        return _series_or_scalar(args[0], lambda x: x.abs(), abs)
    if fn == "round":
        _check_arity(fn, args, (1, 2))
        ndigits = int(args[1]) if len(args) == 2 else 0
        return _series_or_scalar(args[0], lambda x: x.round(ndigits), lambda x: round(x, ndigits))
    if fn == "min":
        return _reduce_args(args, "min")
    if fn == "max":
        return _reduce_args(args, "max")
    if fn == "lower":
        _check_arity(fn, args, 1)
        return _str_method(args[0], "lower")
    if fn == "upper":
        _check_arity(fn, args, 1)
        return _str_method(args[0], "upper")
    if fn == "len":
        _check_arity(fn, args, 1)
        return _str_method(args[0], "len")
    if fn == "if":
        _check_arity(fn, args, 3)
        cond, then_, else_ = args
        if isinstance(cond, pd.Series):
            return cond.where(cond.astype(bool), other=else_).where(~cond.astype(bool), other=then_)
        return then_ if cond else else_
    raise ExprError(f"unhandled fn {fn!r}")  # schema should have caught this


def _check_arity(fn: str, args: list[Any], expected: int | tuple[int, ...]) -> None:
    n = len(args)
    if isinstance(expected, int):
        if n != expected:
            raise ExprError(f"fn {fn!r} expects {expected} args, got {n}")
    elif n not in expected:
        raise ExprError(f"fn {fn!r} expects {expected} args, got {n}")


def _series_or_scalar(value: Any, on_series: Any, on_scalar: Any) -> Any:
    if isinstance(value, pd.Series):
        return on_series(value)
    return on_scalar(value)


def _reduce_args(args: list[Any], how: str) -> Any:
    if not args:
        raise ExprError(f"fn {how!r} needs at least one arg")
    # Element-wise min/max across columns/scalars.
    series = [a for a in args if isinstance(a, pd.Series)]
    if not series:
        return min(args) if how == "min" else max(args)
    frame = pd.concat(series, axis=1)
    scalars = [a for a in args if not isinstance(a, pd.Series)]
    for s in scalars:
        frame[f"_lit_{id(s)}"] = s
    return frame.min(axis=1) if how == "min" else frame.max(axis=1)


def _str_method(value: Any, method: str) -> Any:
    if isinstance(value, pd.Series):
        accessor = value.astype(str).str
        if method == "lower":
            return accessor.lower()
        if method == "upper":
            return accessor.upper()
        if method == "len":
            return accessor.len()
    if method == "lower":
        return str(value).lower()
    if method == "upper":
        return str(value).upper()
    if method == "len":
        return len(str(value))
    raise ExprError(f"unhandled str method {method!r}")
