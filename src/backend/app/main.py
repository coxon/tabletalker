"""FastAPI entrypoint.

This is the skeleton service used by `make dev`. Real endpoints are
mounted from `app.api.*`:

- `/spreadsheet/*` — internal typed-plan engine (PR #3.5). Used by the
  analyze pipeline below as an audit/trace layer; **not** the
  submission contract.
- `/v1/analyze` + `/v1/follow-up` — the frozen public contract from
  `docs/submission-contract.md`. `analyze` ships in PR #4; `follow-up`
  in PR #6.
"""

from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import __version__
from app.api.analyze import router as analyze_router
from app.api.follow_up import router as follow_up_router
from app.api.reports import router as reports_router
from app.api.spreadsheet import router as spreadsheet_router

app = FastAPI(title="TableTalker Backend", version=__version__)
# Trust `X-Forwarded-Proto` / `X-Forwarded-Host` / `X-Forwarded-For`
# from the reverse proxy in front of uvicorn. We mount the middleware
# at the app level (rather than relying solely on `uvicorn --proxy-headers`)
# so behaviour is consistent across launchers (uvicorn CLI, gunicorn,
# TestClient) and so tests can exercise the proxy path. The handler
# uses `request.base_url` to construct `report_html_url`; if proxy
# headers aren't honoured, deploys behind nginx/Caddy emit URLs
# pointing at `localhost:8000` even when accessed via `https://...`.
# `*` is the standard "trust whatever proxy is in front" setting; it's
# safe here because the binding (`0.0.0.0:8000`) is meant to sit behind
# trusted infra during the submission window.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.include_router(spreadsheet_router)
app.include_router(analyze_router)
app.include_router(follow_up_router)
app.include_router(reports_router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Liveness probe used by the frontend and by container orchestrators."""
    return {"ok": True}


@app.get("/version")
def version() -> dict[str, str]:
    """Service name and version, for diagnostics."""
    return {"name": "tabletalker-backend", "version": __version__}
