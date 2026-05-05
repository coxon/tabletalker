"""Spreadsheet — TableTalker's internal typed-plan engine.

The user asks a natural-language question; the LLM emits a typed `Plan`
(a DAG of `Op`s); the `Executor` runs it against pandas DataFrames and
captures a `Trace` (per-op timing + result shape).

This module is **not** the submission-contract endpoint (`/v1/analyze`,
defined in `docs/submission-contract.md`). It is the internal audit
layer: PR #4's analyze pipeline calls into the executor so every
evidence tuple `(filters, aggregation, value, row_count)` reaches the
contract response with structured provenance, not regex-extracted from
raw pandas source. See `docs/architecture.md` §4 ("Why both ReAct and
a typed plan?") for the full design rationale.

Internal naming uses `Spreadsheet*`; the user-facing trace is rendered
as `TableVerse`s — see `verse.py`.
"""

from app.spreadsheet.schema import Op, OpResult, Plan
from app.spreadsheet.verse import TableVerse

__all__ = ["Op", "OpResult", "Plan", "TableVerse"]
