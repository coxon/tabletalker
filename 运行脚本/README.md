# 运行脚本

`start.sh` boots TableTalker from a clean clone:

```bash
bash 运行脚本/start.sh
```

Requirements on the host:

- Python 3.11+ with [`uv`](https://docs.astral.sh/uv/)
- Node 20+ with `pnpm`
- A reachable `LLM_BASE_URL` + `LLM_API_KEY` (see `.env.example`)

After the script returns:

- Backend: http://localhost:8000 (`/healthz`, `/v1/analyze`)
- Frontend: http://localhost:3000

This script is the contract surface the organizer will run. Keep it
idempotent and zero-question.
