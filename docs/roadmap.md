# Roadmap

TableTalker is built through narrow PRs targeting `main`. This file tracks them.

Shipping target: 2026-05-10 18:00 CST (China Standard Time, UTC+08:00).

| # | Branch | Target | Scope | Status |
|---|---|---|---|---|
| 1 | `docs/bootstrap` | 5/4 | README, this roadmap, CodeRabbit config | ✅ |
| 2 | `chore/skeleton` | 5/5 | Next.js + FastAPI hello, Makefile, CI workflow | 🚧 |
| 3 | `feat/planner-executor` | 5/6 | Planner, executor, pandas sandbox | ☐ |
| 4 | `feat/insight-report` | 5/7 | Profiler, InsightAgent, 3+ charts, Jinja report | ☐ |
| 5 | `feat/followup-batch` | 5/8 | Session memory, Critic, follow-up, batch eval UI | ☐ |
| 6 | `chore/evaluation` | 5/9 | Run on 15 datasets, evaluation report, Docker, bug fixes | ☐ |
| 7 | `docs/architecture` | 5/9 | Architecture diagrams, design doc, README finalize | ☐ |
| 8 | `chore/submission` | 5/10 am | Demo video, submission package, form submit | ☐ |

## Rules

- Each PR is narrow and reviewable on its own.
- Open a PR only when its exit criteria pass locally.
- CodeRabbit comments are resolved before merge.
- A PR that completes a row updates its status to ✅ in the same commit;
  the next PR flips any still-🚧 row from the previous one if needed.
