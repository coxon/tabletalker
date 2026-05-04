# TableTalker

A data analysis agent. Give it a CSV or Excel file and a plain-English
question; get back an interactive HTML report with follow-up Q&A grounded
in the data.

> 🚧 In active development — see [`docs/roadmap.md`](docs/roadmap.md) for the
> shipping plan.

## Project layout

```
src/backend/      FastAPI service (Python 3.11+, managed by uv)
src/frontend/     Next.js 15 + React 19 app (managed by pnpm)
src/templates/    Jinja templates for HTML reports (filled in PR #4)
架构文档/          architecture docs (organizer-required)
运行脚本/          run scripts (organizer-required)
演示视频/          demo video (organizer-required)
自测报告/          self-evaluation report (organizer-required)
docs/             internal engineering docs (roadmap, agent design)
tests/            cross-cutting tests
```

`PRODUCT.md` is the product brief. `CLAUDE.md` is the per-repo guidance for
Claude Code.

## Local development

Prereqs: [`uv`](https://docs.astral.sh/uv/), Node 20+, `pnpm` (via
`corepack enable`), GNU `make`.

```bash
make install   # backend (uv sync) + frontend (pnpm install)
make dev       # backend on :8000, frontend on :3000, Ctrl+C stops both
make check     # lint + typecheck + test (the pre-PR gate)
```

Quick smoke check once `make dev` is up:

```bash
curl localhost:8000/health           # → {"ok": true}
curl localhost:3000/api/health       # → {"ok": true, "backend": "..."}
open  http://localhost:3000          # → "Hello, TableTalker"
```

Containerization is deferred to a later PR — local-first dev loop comes first.

## License

[Apache 2.0](LICENSE).
