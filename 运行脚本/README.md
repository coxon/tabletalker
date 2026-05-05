# 运行脚本

`start.sh` boots TableTalker from a clean clone:

```bash
bash 运行脚本/start.sh
```

Requirements on the host:

- Python 3.11+ with [`uv`](https://docs.astral.sh/uv/)
- Node 20+ with `pnpm`
- A reachable `LLM_BASE_URL` + `LLM_API_KEY` (see `.env.example`)

While the script is running (it blocks on `wait` after launching both
servers), the following endpoints are reachable:

- Backend: http://localhost:8000
  - `/health` — liveness probe (PR #2, available now)
  - `/v1/analyze` and `/v1/follow-up` — submission contract endpoints,
    land in PR #4 (see `docs/submission-contract.md`)
- Frontend: http://localhost:3000

Press `Ctrl+C` to stop both servers cleanly.

This script is the contract surface the organizer will run. Keep it
idempotent and zero-question.
