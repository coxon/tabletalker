"""Plan schema — the contract between the LLM planner and the executor.

A `Plan` is a DAG of `Op`s. Each Op has a unique `out` name; downstream
Ops reference upstream outputs by name. This avoids implicit pipelining
and lets join/pivot take multiple inputs cleanly.

Op kinds in this PR (PR #3 — first 15 of 30):
  load_csv, load_excel, select_columns, filter_rows, add_column,
  group_by, aggregate, sort, head, tail, join, pivot, melt,
  to_table, to_chart

Future ops (PR #4/#5) will be added by extending the `Op` discriminated
union — older plans stay valid.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Tiny expression DSL for `add_column`
# ---------------------------------------------------------------------------
# Why a DSL and not pandas.eval / Python? Two reasons:
#   1. Auditable — every expression is a tree we can walk and reject.
#   2. Consistent — the LLM already emits structured JSON; mixing raw
#      strings here would mean two parsers and two attack surfaces.
#
# Grammar:
#   Expr := Literal | ColRef | BinOp | Call
#   Literal = {"lit": <number|string|bool|null>}
#   ColRef  = {"col": "<name>"}
#   BinOp   = {"op": "+|-|*|/|==|!=|<|<=|>|>=|and|or", "args": [Expr, Expr]}
#   Call    = {"fn": "<name>", "args": [Expr, ...]}        # whitelisted fns only
#
# The executor enforces the function whitelist; schema only validates shape.

ALLOWED_BINOPS = frozenset({"+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">=", "and", "or"})
ALLOWED_FNS = frozenset({"abs", "round", "min", "max", "lower", "upper", "len", "if"})


class LiteralExpr(BaseModel):
    lit: float | int | str | bool | None


class ColRefExpr(BaseModel):
    col: str


class BinOpExpr(BaseModel):
    op: str
    args: list[Expr]

    @field_validator("op")
    @classmethod
    def _check_op(cls, v: str) -> str:
        if v not in ALLOWED_BINOPS:
            raise ValueError(f"unknown binop {v!r}; allowed: {sorted(ALLOWED_BINOPS)}")
        return v


class CallExpr(BaseModel):
    fn: str
    args: list[Expr]

    @field_validator("fn")
    @classmethod
    def _check_fn(cls, v: str) -> str:
        if v not in ALLOWED_FNS:
            raise ValueError(f"unknown fn {v!r}; allowed: {sorted(ALLOWED_FNS)}")
        return v


Expr = LiteralExpr | ColRefExpr | BinOpExpr | CallExpr


# ---------------------------------------------------------------------------
# Op discriminated union
# ---------------------------------------------------------------------------

class _OpBase(BaseModel):
    """Common fields for every op."""

    out: str = Field(..., description="Name of this op's output in the register.")


class LoadCsvOp(_OpBase):
    kind: Literal["load_csv"]
    path: str
    # Encoding/delimiter omitted — autodetect in PR #3, expose later if needed.


class LoadExcelOp(_OpBase):
    kind: Literal["load_excel"]
    path: str
    sheet: str | int = 0


class SelectColumnsOp(_OpBase):
    kind: Literal["select_columns"]
    src: str
    columns: list[str]


class FilterRowsOp(_OpBase):
    kind: Literal["filter_rows"]
    src: str
    where: Expr  # must evaluate to bool per row


class AddColumnOp(_OpBase):
    kind: Literal["add_column"]
    src: str
    name: str
    expr: Expr


class GroupByOp(_OpBase):
    kind: Literal["group_by"]
    src: str
    by: list[str]


class AggSpec(BaseModel):
    """One aggregation: which column, which function, what to call the result."""

    column: str
    fn: Literal["sum", "mean", "count", "min", "max", "median", "nunique"]
    as_: str = Field(..., alias="as")

    model_config = {"populate_by_name": True}


class AggregateOp(_OpBase):
    kind: Literal["aggregate"]
    src: str  # must reference a group_by output
    aggs: list[AggSpec]


class SortOp(_OpBase):
    kind: Literal["sort"]
    src: str
    by: list[str]
    desc: list[bool] | None = None


class HeadOp(_OpBase):
    kind: Literal["head"]
    src: str
    n: int = 10


class TailOp(_OpBase):
    kind: Literal["tail"]
    src: str
    n: int = 10


class JoinOp(_OpBase):
    kind: Literal["join"]
    left: str
    right: str
    on: list[str]
    how: Literal["inner", "left", "right", "outer"] = "inner"


class PivotOp(_OpBase):
    kind: Literal["pivot"]
    src: str
    index: list[str]
    columns: str
    values: str
    aggfn: Literal["sum", "mean", "count", "min", "max"] = "sum"


class MeltOp(_OpBase):
    kind: Literal["melt"]
    src: str
    id_vars: list[str]
    value_vars: list[str] | None = None
    var_name: str = "variable"
    value_name: str = "value"


class ToTableOp(_OpBase):
    kind: Literal["to_table"]
    src: str
    title: str | None = None


class ToChartOp(_OpBase):
    kind: Literal["to_chart"]
    src: str
    chart: Literal["bar", "line", "pie", "scatter"]
    x: str
    y: str | list[str]
    title: str | None = None


_OpUnion = (
    LoadCsvOp
    | LoadExcelOp
    | SelectColumnsOp
    | FilterRowsOp
    | AddColumnOp
    | GroupByOp
    | AggregateOp
    | SortOp
    | HeadOp
    | TailOp
    | JoinOp
    | PivotOp
    | MeltOp
    | ToTableOp
    | ToChartOp
)
Op = Annotated[_OpUnion, Field(discriminator="kind")]


class Plan(BaseModel):
    """A DAG of typed ops. The last op's output is the user-facing answer."""

    ops: list[Op]
    answer: str = Field(
        default="",
        description="Name of the op whose output is the final answer. "
        "Defaults to the last op if empty.",
    )

    @field_validator("ops")
    @classmethod
    def _non_empty(cls, v: list[Op]) -> list[Op]:
        if not v:
            raise ValueError("plan must contain at least one op")
        return v


# ---------------------------------------------------------------------------
# Op execution result (per-op metadata for the trace)
# ---------------------------------------------------------------------------

class OpResult(BaseModel):
    """Metadata captured per op during execution. Not the data itself."""

    out: str
    kind: str
    rows: int | None = None
    cols: int | None = None
    ms: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)


# Resolve forward refs for recursive Expr
BinOpExpr.model_rebuild()
CallExpr.model_rebuild()
