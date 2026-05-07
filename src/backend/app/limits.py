"""Shared numeric limits used across multiple modules.

Keeping a single source for these constants prevents drift between
the HTTP route (which 413s on the way in) and the deeper layers (the
profiler / engine, which have their own size guards). Without this,
nudging one cap and forgetting the other produces inconsistent
behaviour: the route accepts a file the profiler then refuses, or
vice versa.

Add new shared limits here only when at least two modules need them;
otherwise keep them module-local.
"""

from __future__ import annotations

# Maximum upload size accepted by `/v1/analyze` and `/spreadsheet/analyze`.
# Mirrored by `app.analyze.profiler` so off-line callers also enforce it.
UPLOAD_MAX_BYTES: int = 20 * 1024 * 1024  # 20 MiB

# Aggregate cap for one `/v1/analyze` request (primary + extra_files
# combined). Without this, a caller could attach an unbounded number of
# `extra_files` each up to `UPLOAD_MAX_BYTES` and pin all of `/tmp`
# until the session TTL evicts the workspace. 100 MiB lets a typical
# multi-table join (e.g. 1 fact table + 4 dimension tables ≈ 80 MiB)
# through while keeping the per-session disk footprint bounded.
UPLOAD_MAX_TOTAL_BYTES: int = 100 * 1024 * 1024  # 100 MiB

# Hard ceiling on the *total* number of files in one upload (primary +
# all auxiliaries combined). Independent of the byte cap so a flood of
# tiny files can't exhaust inodes or the planner's table-list token
# budget. 8 = primary + up to 7 auxiliaries; the planner's prompt only
# enumerates table names, so even 8 stays well within the context window.
#
# Enforcement contract (CodeRabbit #15 round-2): callers MUST count the
# primary file when checking — i.e. `1 + len(extra_files) > UPLOAD_MAX_FILES`,
# never `len(extra_files) > UPLOAD_MAX_FILES` (the latter would silently
# allow 8 auxiliaries + 1 primary = 9 total). The single live caller is
# `app.api.analyze`; verify any new enforcement site does the same.
UPLOAD_MAX_FILES: int = 8

