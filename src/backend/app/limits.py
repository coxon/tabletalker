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
