# tabletalker-backend

FastAPI service for TableTalker. Run from the repo root with `make dev`,
or directly:

```bash
uv sync --dev
uv run uvicorn app.main:app --reload --port 8000
```

Endpoints:

- `GET /health` — liveness probe
- `GET /version` — service name and version
