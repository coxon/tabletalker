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
