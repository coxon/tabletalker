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
src/templates/    Jinja templates for HTML reports (filled in PR #5)
架构文档/          architecture docs (organizer-required)
运行脚本/          `start.sh` — boots from a clean clone
演示视频/          demo video (filled in PR #9)
自测报告/          `latest_evaluation_metrics.md` — read directly by
                   the organizer's auto-grader; numbers are measured,
                   never estimated
docs/             internal engineering docs — `roadmap.md`,
                   `architecture.md`, `submission-contract.md`,
                   `scoring-map.md`, `refusal-policy.md`,
                   `session-state.md`
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
curl localhost:3000/api/health       # dev → {"ok": true, "backend": "..."}; prod → {"ok": true}
# Open http://localhost:3000 in your browser → "Hello, TableTalker"
# (mac: `open URL` · linux: `xdg-open URL` · windows: `start URL`)
```

Containerization is deferred to a later PR — local-first dev loop comes first.

## Submission (organizer view)

The organizer's grader pulls the repo (default → master → main, in that
order), then:

1. Reads `自测报告/latest_evaluation_metrics.md` for self-reported metrics.
2. Runs `bash 运行脚本/start.sh` to bring the system up.
3. Hits `POST /v1/analyze` with the JSON contract frozen in
   [`docs/submission-contract.md`](docs/submission-contract.md).
4. Opens `report_html_url` and the `演示视频/` recording.

See [`docs/scoring-map.md`](docs/scoring-map.md) for how each rubric line
maps to a module and PR, and [`docs/refusal-policy.md`](docs/refusal-policy.md)
for the four trap categories and their canonical phrasings.

## License

[Apache 2.0](LICENSE).
