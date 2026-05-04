"""FastAPI entrypoint.

This is the skeleton service used by `make dev`. Real endpoints land in
later PRs (planner, executor, report, follow-up).
"""

from fastapi import FastAPI

from app import __version__

app = FastAPI(title="TableTalker Backend", version=__version__)


@app.get("/health")
def health() -> dict[str, bool]:
    """Liveness probe used by the frontend and by container orchestrators."""
    return {"ok": True}


@app.get("/version")
def version() -> dict[str, str]:
    """Service name and version, for diagnostics."""
    return {"name": "tabletalker-backend", "version": __version__}
