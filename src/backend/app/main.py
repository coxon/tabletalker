"""FastAPI entrypoint.

This is the skeleton service used by `make dev`. Real endpoints are
mounted from `app.api.*`:

- `/spreadsheet/*` — internal typed-plan engine (PR #3.5). Used by the
  analyze pipeline below as an audit/trace layer; **not** the
  submission contract.
- `/v1/analyze` + `/v1/follow-up` — the frozen public contract from
  `docs/submission-contract.md`. Lands in PR #4.
"""

from fastapi import FastAPI

from app import __version__
from app.api.spreadsheet import router as spreadsheet_router

app = FastAPI(title="TableTalker Backend", version=__version__)
app.include_router(spreadsheet_router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Liveness probe used by the frontend and by container orchestrators."""
    return {"ok": True}


@app.get("/version")
def version() -> dict[str, str]:
    """Service name and version, for diagnostics."""
    return {"name": "tabletalker-backend", "version": __version__}
