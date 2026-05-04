"""Spreadsheet — TableTalker's Route A typed-plan engine.

The user asks a natural-language question; the LLM emits a typed `Plan`
(a DAG of `Op`s); the `Executor` runs it against pandas DataFrames.

Internal naming uses `Spreadsheet*`; the user-facing trace is rendered as
`TableVerse`s — see `verse.py`.

Inspired by Claude's internal `spreadsheet` tool.
"""

from app.spreadsheet.schema import Op, OpResult, Plan
from app.spreadsheet.verse import TableVerse

__all__ = ["Op", "OpResult", "Plan", "TableVerse"]
