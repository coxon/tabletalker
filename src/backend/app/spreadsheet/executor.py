"""Plan executor — runs a typed `Plan` against a workspace.

Execution is **sequential** and follows the order of `plan.ops`.
Because every op references its inputs by name (`src` / `left` /
`right`), the order in the list IS the topological order — the LLM is
responsible for emitting ops in dependency order. We validate this up
front (`_validate_dag`) so a bad plan fails fast with a clear error
rather than a `KeyError` mid-execution.

If we ever want parallel branch execution, the register and topological
check are already in place.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.spreadsheet.context import SpreadsheetContext
from app.spreadsheet.ops import HANDLERS
from app.spreadsheet.schema import Op, OpResult, Plan
from app.spreadsheet.verse import TableVerse, to_verse


class PlanValidationError(Exception):
    """Plan is structurally invalid before execution starts."""


class OpExecutionError(Exception):
    """An op handler raised. Wraps the underlying error with op context."""

    def __init__(self, op_index: int, op: Op, cause: BaseException) -> None:
        super().__init__(f"op #{op_index} ({op.kind} → {op.out}) failed: {cause}")
        self.op_index = op_index
        self.op = op
        self.cause = cause


@dataclass
class ExecutionReport:
    answer: Any  # the payload produced by the answer op (table/chart dict)
    op_results: list[OpResult]
    verses: list[TableVerse]


def execute(plan: Plan, workspace: Path) -> ExecutionReport:
    """Run a plan. Raises `PlanValidationError` or `OpExecutionError`."""

    if not plan.ops:
        # Schema-level validator should have caught this; treat any leak as
        # a hard plan error (not an IndexError) so the API maps to 422.
        raise PlanValidationError("plan must contain at least one op")

    _validate_dag(plan)
    ctx = SpreadsheetContext(workspace=workspace)
    op_results: list[OpResult] = []
    verses: list[TableVerse] = []

    for index, op in enumerate(plan.ops):
        handler = HANDLERS.get(op.kind)
        if handler is None:  # should be unreachable thanks to schema discriminator
            raise PlanValidationError(f"no handler for op kind {op.kind!r}")

        started = time.perf_counter()
        try:
            result = handler(op, ctx)  # type: ignore[arg-type]
        except Exception as exc:
            raise OpExecutionError(index, op, exc) from exc
        result.ms = (time.perf_counter() - started) * 1000

        op_results.append(result)
        verses.append(to_verse(index + 1, op, result))

    answer_name = plan.answer or plan.ops[-1].out
    if answer_name not in ctx.register:
        raise PlanValidationError(f"answer references unknown register slot {answer_name!r}")

    answer = ctx.register[answer_name]
    # The user-facing answer must be a render payload from `to_table` /
    # `to_chart` (a dict with a `type` discriminator). Anything else means
    # the LLM forgot the terminal render op — fail loudly here so the API
    # returns a clean 422 instead of returning a raw DataFrame / GroupBy
    # that would then fail downstream JSON serialisation.
    if not isinstance(answer, dict) or answer.get("type") not in ("table", "chart"):
        kind = type(answer).__name__
        raise PlanValidationError(
            f"answer slot {answer_name!r} is not a render payload "
            f"(got {kind}); plan must end with `to_table` or `to_chart`"
        )

    return ExecutionReport(
        answer=answer,
        op_results=op_results,
        verses=verses,
    )


# ---------------------------------------------------------------------------
# DAG validation
# ---------------------------------------------------------------------------

def _validate_dag(plan: Plan) -> None:
    """Verify outputs are unique and inputs reference earlier outputs.

    We don't allow forward references — the executor runs ops in list
    order, and tolerating forward refs would require topological sort
    that the LLM rarely needs anyway.
    """

    seen: set[str] = set()
    for index, op in enumerate(plan.ops):
        for input_field in _input_fields(op):
            ref = getattr(op, input_field)
            if ref not in seen:
                raise PlanValidationError(
                    f"op #{index} ({op.kind}) references undefined input "
                    f"{input_field}={ref!r}; either it's a typo, or the producing "
                    "op comes later in the list (forward refs not allowed)"
                )
        if op.out in seen:
            raise PlanValidationError(
                f"op #{index} ({op.kind}) reuses output name {op.out!r}; "
                "every op must produce a unique register slot"
            )
        seen.add(op.out)


def _input_fields(op: Op) -> list[str]:
    """Names of register-reference fields for this op kind."""

    if op.kind == "join":
        return ["left", "right"]
    if op.kind in ("load_csv", "load_excel"):
        return []
    return ["src"]
