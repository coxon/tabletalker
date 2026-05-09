#!/usr/bin/env bash
# TableTalker boot-from-clean-clone entrypoint.
# Organizer expectation: this script brings the system up from a fresh clone.
# Until the full stack lands (PR #4–#7), this script prints status and starts
# whatever subset is currently functional.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> TableTalker start.sh"
echo "    repo root: $ROOT"
echo "    date:      $(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    echo "==> .env not found — copying from .env.example"
    cp .env.example .env
  fi
fi

# Fail fast if .env is missing required vars or still carries placeholder
# credentials. The grader will exercise /v1/analyze, which calls the LLM
# gateway — booting with `sk-replace-me` would produce a misleading
# "running" state and fail every request.
required_vars=(LLM_BASE_URL LLM_API_KEY LLM_MODEL APP_PUBLIC_URL)
missing=0
for var in "${required_vars[@]}"; do
  if ! grep -Eq "^${var}=.+" .env; then
    echo "ERROR: ${var} is missing or empty in .env" >&2
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo "        (set the missing variables in .env, then re-run start.sh)" >&2
  exit 1
fi
if grep -Eq '^LLM_API_KEY=sk-replace-me$' .env; then
  echo "ERROR: LLM_API_KEY in .env is still the placeholder 'sk-replace-me'." >&2
  echo "       Replace it with a real key issued by the AsiaInfo gateway." >&2
  exit 1
fi

echo "==> Backend: installing deps"
( cd 源代码/backend && uv sync )

echo "==> Frontend: installing deps"
( cd 源代码/frontend && pnpm install --frozen-lockfile )

echo "==> Launching backend on :8000 and frontend on :3000"
# Log file for the backend; tee preserves the tty stream for interactive
# starts while also persisting full stderr/stdout to disk so the eval
# runner can re-read failed-case context after the run finishes (the
# previous default lost stderr at terminal close, making 502 root-cause
# analysis on cases like 08_logistics_routes require a re-run).
# Override with TT_BACKEND_LOG=/path/to/file if you need a stable
# location for log shipping; default is /tmp so it doesn't pollute the
# repo.
TT_BACKEND_LOG="${TT_BACKEND_LOG:-/tmp/tt-backend.log}"
echo "    backend log: $TT_BACKEND_LOG"
# `--proxy-headers` lets uvicorn honour `X-Forwarded-Proto` /
# `X-Forwarded-Host` from a TLS-terminating reverse proxy. The backend
# uses the request URL to build absolute `report_html_url`s; without
# this, deploys behind nginx/Caddy/Cloudfront would emit URLs pointing
# at `http://localhost:8000` even when accessed via `https://demo.example.com`.
#
# We deliberately do NOT pass `--forwarded-allow-ips '*'`. uvicorn's
# default (`127.0.0.1`) means uvicorn only honours `X-Forwarded-*`
# from a same-host proxy, and from there the proxy-trust decision is
# delegated to the app-level `ProxyHeadersMiddleware`, which gates
# trust on the `APP_TRUSTED_PROXIES` env var (see
# `源代码/backend/app/main.py`). Wildcarding the uvicorn allowlist here
# would let an arbitrary client (e.g. someone hitting :8000 directly)
# spoof headers and override `report_html_url` — defeating
# APP_TRUSTED_PROXIES entirely.
( cd 源代码/backend && uv run uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers 2>&1 | tee "$TT_BACKEND_LOG" ) &
BACK_PID=$!
( cd 源代码/frontend && pnpm dev --port 3000 ) &
FRONT_PID=$!

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null || true' EXIT
wait
