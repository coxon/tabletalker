"""Execution context — the named DataFrame register.

Ops produce DataFrames keyed by `out`. Downstream ops reference them by
name (`src` / `left` / `right`). This decouples plan order from data
flow and lets join/pivot take multiple inputs cleanly.

The register also stores `GroupBy` objects so `group_by` → `aggregate`
can be split into two ops without losing the grouping state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SpreadsheetContext:
    """Per-request execution context.

    `workspace` is the directory that op `path` arguments are resolved
    against. The executor MUST refuse paths that escape it — see
    `resolve_path` below.
    """

    workspace: Path
    register: dict[str, Any] = field(default_factory=dict)

    def put(self, name: str, value: Any) -> None:
        if name in self.register:
            raise SpreadsheetContextError(f"register slot {name!r} already populated")
        self.register[name] = value

    def get(self, name: str) -> Any:
        if name not in self.register:
            raise SpreadsheetContextError(f"no register slot named {name!r}")
        return self.register[name]

    def resolve_path(self, raw: str) -> Path:
        """Resolve an op-supplied path against the workspace, refusing escapes."""

        candidate = (self.workspace / raw).resolve()
        try:
            candidate.relative_to(self.workspace.resolve())
        except ValueError as exc:
            raise SpreadsheetContextError(
                f"path {raw!r} escapes workspace {self.workspace}"
            ) from exc
        return candidate


class SpreadsheetContextError(Exception):
    """Register lookup or workspace path violation."""
