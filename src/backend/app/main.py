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

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

# Load .env from repo root (two levels up from this file).
_env_file = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_env_file)
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import __version__
from app.api.analyze import router as analyze_router
from app.api.batch import router as batch_router
from app.api.follow_up import router as follow_up_router
from app.api.reports import router as reports_router
from app.api.sessions import router as sessions_router
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
#
# Round-9 (CodeRabbit #14): the previous default of `trusted_hosts="*"`
# blindly trusted X-Forwarded-* from any source — fine for the
# tested-behind-trusted-infra submission window, but a foot-gun if the
# image leaks onto a network where a hostile client can reach uvicorn
# directly. The `APP_TRUSTED_PROXIES` env var (comma-separated) lets
# operators pin exactly which sources are trusted, and we keep `"*"`
# as the explicit default with a doc-string so the choice is visible
# in the deploy log instead of buried in code. Empty string disables
# proxy-header trust entirely (useful for local dev without a proxy).
_trusted_proxies_env = os.environ.get("APP_TRUSTED_PROXIES", "*").strip()
if _trusted_proxies_env in ("", "*"):
    _trusted_hosts: str | list[str] = _trusted_proxies_env or []
else:
    _trusted_hosts = [
        host.strip() for host in _trusted_proxies_env.split(",") if host.strip()
    ]
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted_hosts)
app.include_router(spreadsheet_router)
app.include_router(analyze_router)
app.include_router(follow_up_router)
app.include_router(reports_router)
app.include_router(batch_router)
app.include_router(sessions_router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Liveness probe used by the frontend and by container orchestrators."""
    return {"ok": True}


@app.get("/version")
def version() -> dict[str, str]:
    """Service name and version, for diagnostics."""
    return {"name": "tabletalker-backend", "version": __version__}
