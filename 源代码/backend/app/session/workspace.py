"""Persistent workspace directory resolution.

Mirrors the resolution strategy of `app.report.store._resolve_disk_dir`:
prefer an explicit env override, then auto-detect the k8s/compose PVC
mount, then fall back to a per-process tempdir for dev/tests.

Why a *persistent* workspace root: every parent `/v1/analyze` request
saves its uploaded CSV/Excel into a per-session directory. Follow-ups
re-read those files via `session.workspace_dir`. With the legacy
`tempfile.mkdtemp` path, those files lived in `/tmp` and were lost on
process restart — which means anyone refreshing the SPA after a
backend restart got a 404 on follow-up because the session's
`workspace_dir` no longer existed.

Selection rules (highest precedence first):
  1. `TABLETALKER_WORKSPACE_DIR` env var — explicit override.
  2. `/app/data/workspaces` — auto-detected k8s/compose PVC mount.
     (`/app/data` mirrors what `_resolve_disk_dir` uses for reports.)
  3. `None` — caller falls back to `tempfile.mkdtemp` so dev runs
     and unit tests don't need a writable persistent volume.

Per-session subdir naming: callers pass the response_id (the parent
turn's id, e.g. `eval_analysis_<32-hex>`). The workspace is then
`<root>/<response_id>/`. Choosing the response_id keeps the on-disk
layout grep-able from log lines and avoids carrying a separate
mapping table.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# Allow ASCII alphanumerics, dashes, underscores, dots. Anything else
# would risk path traversal (`..`) or weird shell behaviour. Response
# ids the handler emits match this charset; we still validate
# defensively because workspace paths come from user-controlled
# request_id arguments in some code paths.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def resolve_workspace_root() -> Path | None:
    """Return the persistent workspace root, or `None` for tempdir mode."""

    explicit = os.environ.get("TABLETALKER_WORKSPACE_DIR", "").strip()
    if explicit:
        return Path(explicit)
    pvc_mount = Path("/app/data")
    if pvc_mount.is_dir():
        return pvc_mount / "workspaces"
    return None


def make_workspace(session_id: str) -> Path:
    """Create and return the workspace dir for `session_id`.

    Persistent path when `resolve_workspace_root()` returns non-None;
    a per-process tempdir otherwise (dev / tests). The directory
    always exists when this returns; parents are created with
    `parents=True`. Re-creating a workspace for the same id is fine —
    `mkdir(exist_ok=True)` keeps the existing files in place, which
    is what we want for a session that's resumed after a backend
    restart (files are already on disk).
    """

    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"unsafe session_id for workspace path: {session_id!r}")

    root = resolve_workspace_root()
    if root is None:
        # tempdir mode — same as the legacy behaviour, just keyed on
        # the session id so a concurrent test or local dev run doesn't
        # collide.
        return Path(
            tempfile.mkdtemp(
                prefix="tabletalker-analyze-",
                suffix=f"-{session_id}",
            )
        )

    target = root / session_id
    target.mkdir(parents=True, exist_ok=True)
    return target
