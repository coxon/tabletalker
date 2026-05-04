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

echo "==> Backend: installing deps"
( cd src/backend && uv sync )

echo "==> Frontend: installing deps"
( cd src/frontend && pnpm install --frozen-lockfile )

echo "==> Launching backend on :8000 and frontend on :3000"
( cd src/backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 ) &
BACK_PID=$!
( cd src/frontend && pnpm dev --port 3000 ) &
FRONT_PID=$!

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null || true' EXIT
wait
