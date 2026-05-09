"""Plan schema — the contract between the LLM planner and the executor.

A `Plan` is a DAG of `Op`s. Each Op has a unique `out` name; downstream
Ops reference upstream outputs by name. This avoids implicit pipelining
and lets join/pivot take multiple inputs cleanly.

Op kinds in this PR (PR #3.5 — first 15 of 30):
  load_csv, load_excel, select_columns, filter_rows, add_column,
  group_by, aggregate, sort, head, tail, join, pivot, melt,
  to_table, to_chart

Future ops (PR #4/#5) will be added by extending the `Op` discriminated
union — older plans stay valid.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

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

# Per-function arity. A tuple `(min, max)` covers variadic / optional cases:
#   - `round(x)` and `round(x, 2)` both valid → (1, 2)
#   - `min` / `max` accept ≥1 args → (1, None) where `None` means unbounded
# Single-arity fns use `(n, n)` for clarity.
# Mirrors the runtime `_check_arity` calls in `app.spreadsheet.expr` so a
# bad call count fails at plan validation, not partway through execution.
_FN_ARITY: dict[str, tuple[int, int | None]] = {
    "abs": (1, 1),
    "round": (1, 2),
    "min": (1, None),
    "max": (1, None),
    "lower": (1, 1),
    "upper": (1, 1),
    "len": (1, 1),
    "if": (3, 3),
}


class _StrictModel(BaseModel):
    """Schema base — reject unknown fields at the planner boundary.

    The planner is an LLM; unfamiliar keys it might invent (typos like
    `colum` instead of `column`, or hallucinated extras like `fmt`) must
    fail loudly at validation, not silently slip through and confuse the
    executor. `extra="forbid"` is the cheapest way to enforce that.
    """

    model_config = {"extra": "forbid"}


class LiteralExpr(_StrictModel):
    lit: float | int | str | bool | None


class ColRefExpr(_StrictModel):
    col: str


class BinOpExpr(_StrictModel):
    op: str
    args: list[Expr]

    @field_validator("op")
    @classmethod
    def _check_op(cls, v: str) -> str:
        if v not in ALLOWED_BINOPS:
            raise ValueError(f"unknown binop {v!r}; allowed: {sorted(ALLOWED_BINOPS)}")
        return v

    @field_validator("args")
    @classmethod
    def _check_arity(cls, v: list[Expr]) -> list[Expr]:
        if len(v) != 2:
            raise ValueError(f"binop expects exactly 2 args, got {len(v)}")
        return v


class CallExpr(_StrictModel):
    fn: str
    args: list[Expr]

    @field_validator("fn")
    @classmethod
    def _check_fn(cls, v: str) -> str:
        if v not in ALLOWED_FNS:
            raise ValueError(f"unknown fn {v!r}; allowed: {sorted(ALLOWED_FNS)}")
        return v

    @field_validator("args")
    @classmethod
    def _check_arity(cls, v: list[Expr], info: ValidationInfo) -> list[Expr]:
        # `fn` was already validated above; if it's missing here that means
        # validation already failed elsewhere, so skip arity to avoid masking
        # the more useful "unknown fn" error.
        fn = info.data.get("fn")
        if not isinstance(fn, str) or fn not in _FN_ARITY:
            return v
        lo, hi = _FN_ARITY[fn]
        n = len(v)
        if n < lo or (hi is not None and n > hi):
            expected = f"{lo}" if lo == hi else (
                f"{lo}–{hi}" if hi is not None else f"≥{lo}"
            )
            raise ValueError(
                f"fn {fn!r} expects {expected} arg(s), got {n}"
            )
        return v


Expr = LiteralExpr | ColRefExpr | BinOpExpr | CallExpr


# ---------------------------------------------------------------------------
# Op discriminated union
# ---------------------------------------------------------------------------

class _OpBase(_StrictModel):
    """Common fields for every op."""

    out: str = Field(..., description="Name of this op's output in the register.")

    # Names of fields on this op that reference upstream register slots.
    # The executor walks these via `_input_fields(op)` to validate the DAG
    # without a hardcoded `kind` switch — new ops just override this tuple.
    # `()` means a producer op (e.g. `load_csv`) with no inputs.
    op_inputs: ClassVar[tuple[str, ...]] = ("src",)


class LoadCsvOp(_OpBase):
    kind: Literal["load_csv"]
    path: str
    # Encoding/delimiter omitted — autodetect in PR #3.5, expose later if needed.

    op_inputs: ClassVar[tuple[str, ...]] = ()


class LoadExcelOp(_OpBase):
    kind: Literal["load_excel"]
    path: str
    sheet: str | int = 0

    op_inputs: ClassVar[tuple[str, ...]] = ()


class SelectColumnsOp(_OpBase):
    kind: Literal["select_columns"]
    src: str
    columns: list[str]

    @field_validator("columns")
    @classmethod
    def _non_empty_columns(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("select_columns.columns must contain at least one column")
        return v


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

    @field_validator("by")
    @classmethod
    def _non_empty_by(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("group_by.by must contain at least one column")
        return v


class AggSpec(_StrictModel):
    """One aggregation: which column, which function, what to call the result."""

    column: str
    fn: Literal["sum", "mean", "count", "min", "max", "median", "nunique"]
    as_: str = Field(..., alias="as")

    # Need both: forbid extras (from _StrictModel) AND let callers use the
    # python attr name `as_` instead of the JSON alias `as` (a python keyword).
    model_config = {"extra": "forbid", "populate_by_name": True}


class AggregateOp(_OpBase):
    kind: Literal["aggregate"]
    src: str  # must reference a group_by output
    aggs: list[AggSpec]

    @field_validator("aggs")
    @classmethod
    def _non_empty_aggs(cls, v: list[AggSpec]) -> list[AggSpec]:
        if not v:
            raise ValueError("aggregate.aggs must contain at least one spec")
        return v


class SortOp(_OpBase):
    kind: Literal["sort"]
    src: str
    by: list[str]
    desc: list[bool] | None = None

    @field_validator("by")
    @classmethod
    def _non_empty_by(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("sort.by must contain at least one column")
        return v

    @field_validator("desc")
    @classmethod
    def _desc_matches_by(cls, v: list[bool] | None, info: ValidationInfo) -> list[bool] | None:
        if v is None:
            return None
        by: list[str] = info.data.get("by", []) or []
        if len(v) != len(by):
            raise ValueError(
                f"sort.desc length ({len(v)}) must match sort.by length ({len(by)}); "
                "omit `desc` for all-ascending"
            )
        return v


class HeadOp(_OpBase):
    kind: Literal["head"]
    src: str
    # `ge=0` because pandas treats negatives as "all but the last N rows" — a
    # surprising semantic for the LLM to accidentally trigger. Zero is fine
    # (returns an empty frame) and stays predictable.
    n: int = Field(default=10, ge=0)


class TailOp(_OpBase):
    kind: Literal["tail"]
    src: str
    n: int = Field(default=10, ge=0)


class JoinOp(_OpBase):
    kind: Literal["join"]
    left: str
    right: str
    # Either symmetric `on` (same key name on both sides) or asymmetric
    # `left_on` + `right_on` (e.g. `id` on left, `movie_id` on right — the
    # TMDB shape). The validator enforces exactly one mode is supplied so
    # the executor doesn't have to guess.
    on: list[str] = Field(default_factory=list)
    left_on: list[str] = Field(default_factory=list)
    right_on: list[str] = Field(default_factory=list)
    how: Literal["inner", "left", "right", "outer"] = "inner"

    op_inputs: ClassVar[tuple[str, ...]] = ("left", "right")

    @model_validator(mode="after")
    def _validate_join_keys(self) -> JoinOp:
        symmetric = bool(self.on)
        asymmetric = bool(self.left_on) or bool(self.right_on)
        if symmetric and asymmetric:
            raise ValueError(
                "join: use either `on` (symmetric) OR `left_on`/`right_on` "
                "(asymmetric), not both"
            )
        if not symmetric and not asymmetric:
            raise ValueError(
                "join must specify keys: provide `on=[...]` for shared key "
                "names, or `left_on=[...]` + `right_on=[...]` when key names "
                "differ between the two tables (e.g. left.id ↔ right.movie_id)"
            )
        if asymmetric:
            if not self.left_on or not self.right_on:
                raise ValueError(
                    "join: when using asymmetric keys, both `left_on` and "
                    "`right_on` must be non-empty"
                )
            if len(self.left_on) != len(self.right_on):
                raise ValueError(
                    f"join: `left_on` ({len(self.left_on)} keys) must align "
                    f"with `right_on` ({len(self.right_on)} keys) by position"
                )
        return self


class PivotOp(_OpBase):
    kind: Literal["pivot"]
    src: str
    index: list[str]
    columns: str
    values: str
    aggfn: Literal["sum", "mean", "count", "min", "max"] = "sum"

    @field_validator("index")
    @classmethod
    def _non_empty_index(cls, v: list[str]) -> list[str]:
        # Mirrors `group_by.by`: an empty `index` produces a single-row pivot
        # which is almost never what the LLM meant — reject at schema time.
        if not v:
            raise ValueError("pivot.index must contain at least one column")
        return v


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


class ExplodeJsonOp(_OpBase):
    """Parse + unroll a JSON-string column (TMDB genres / cast / crew).

    `column` names a column whose cells hold JSON-encoded lists or dicts.
    `extract` (optional) names a field to pluck from each parsed dict —
    use it to reduce `[{"name":"Action"},{"name":"Comedy"}]` to
    `["Action", "Comedy"]` before the explode unrolls those into rows.
    """

    kind: Literal["explode_json"]
    src: str
    column: str
    extract: str | None = None

    @field_validator("column")
    @classmethod
    def _column_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("explode_json.column must be a non-empty column name")
        return v


class ToChartOp(_OpBase):
    kind: Literal["to_chart"]
    src: str
    chart: Literal["bar", "line", "pie", "scatter"]
    x: str
    y: str | list[str]
    title: str | None = None

    @field_validator("y")
    @classmethod
    def _non_empty_y(cls, v: str | list[str]) -> str | list[str]:
        # `y` may be a single column name (str) or a list of column names.
        # Reject empty / whitespace-only entries so `["", "amount"]` or `"  "`
        # don't slip through to runtime as silently broken charts.
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("to_chart.y must be a non-empty string or list of strings")
            return v
        if not v:
            raise ValueError("to_chart.y must be a non-empty string or list of strings")
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "to_chart.y entries must all be non-empty strings; "
                    f"found {item!r}"
                )
        return v


class RefuseOp(_OpBase):
    """Planner-side refusal — short-circuit the pipeline for trap questions.

    Issued by the planner LLM when it judges the user's request matches one
    of the four trap categories from `docs/refusal-policy.md`:
      1. Field missing — the question references a column the data doesn't
         have (e.g. analyse by 种族 when no Race column exists).
      2. Dimension mismatch — the question is about an entirely different
         data domain than what was uploaded.
      3. Hallucination bait — the user asserts a specific statistic and
         asks for explanation; the system should compute first and correct,
         NOT confirm the false claim. (`is_refusal=False` for this category
         per refusal-policy §1; the response carries a Cat 3 narrative.)
      4. Out-of-scope — prompt-leak attempts, file-system access, network
         requests, anything that isn't analyse-the-uploaded-data.

    The handler short-circuits to a refusal response when the plan starts
    with this op, skipping execute / evidence / finalize. The narrative
    travels straight into `AnalyzeResponse.summary`. Categories 1 / 2 / 4
    set `is_refusal=True`; Cat 3 keeps `is_refusal=False` because we ARE
    answering, just correcting the premise first.

    Why a typed op rather than a sentinel string in the plan: keeps the
    surface area auditable (Pydantic rejects malformed refusals before
    they reach the handler) and lets the planner emit refuse alongside
    other ops in principle (e.g. compute then refuse), even though today
    we only handle the refuse-only case.
    """

    kind: Literal["refuse"]
    category: Literal[1, 2, 3, 4]
    narrative: str
    op_inputs: ClassVar[tuple[str, ...]] = ()

    @field_validator("narrative")
    @classmethod
    def _narrative_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "refuse.narrative must be a non-empty Chinese sentence "
                "matching the canonical phrasing for the chosen category "
                "(see docs/refusal-policy.md §2)"
            )
        return v


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
    | ExplodeJsonOp
    | RefuseOp
    | ToTableOp
    | ToChartOp
)
Op = Annotated[_OpUnion, Field(discriminator="kind")]


class Plan(_StrictModel):
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

# Note: OpResult is internal trace metadata, not a planner input — it doesn't
# need `extra="forbid"` since handlers construct it directly.
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
