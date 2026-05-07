# Roadmap

TableTalker is built through narrow PRs targeting `main`. This file tracks them.

Shipping target: 2026-05-10 18:00 CST (China Standard Time, UTC+08:00).

## Sequence

| # | Branch | Target | Scope | Status |
|---|---|---|---|---|
| 1 | `docs/bootstrap` | 5/4 | README, this roadmap, CodeRabbit config | ✅ |
| 2 | `chore/skeleton` | 5/5 | Next.js + FastAPI hello, Makefile, CI workflow | ✅ |
| 3 | `feat/spec-alignment` | 5/5 | Submission-contract docs, refusal policy, scoring map, evaluation-report v0, dataset placement | ✅ |
| 3.5 | `feat/spreadsheet` | 5/6 | Internal typed-plan engine (15 ops, full LLM-planner path); used by PR #4 as the structured audit/trace layer for evidence extraction | ✅ |
| 4 | `feat/analyze-pipeline` | 5/7 | Profiler → single-shot typed-plan planner/executor → evidence extraction → JSON contract response (ReAct deferred) | ✅ |
| 5 | `feat/report-render` | 5/8 | Jinja HTML report with ≥3 chart types (bar/line/pie/scatter/heatmap/box), `report_html_url` hosting | ✅ |
| 6 | `feat/followup-session` | 5/8 | Session state, follow-up routing, refusal classifier, multi-turn UI | ✅ |
| 7 | `feat/web-ui` | 5/9 | File upload, question input, progress states (analyzing / done / refused), report iframe | ✅ |
| 8 | `chore/evaluation` | 5/9 | Run on 15 public datasets, fill `自测报告/latest_evaluation_metrics.md`, perf measurement & report (P50/P95 still above SLO — see §4.1) | ✅ |
| 9 | `chore/submission` | 5/10 am | Demo video, deployment, public URL, final submission | ☐ |

## Rules

- Each PR is narrow and reviewable on its own.
- Open a PR only when its exit criteria pass locally (`make check`).
- CodeRabbit comments are resolved before merge.
- A PR that completes a row updates its status to ✅ in the same commit.
- After every merge, `自测报告/latest_evaluation_metrics.md` is re-checked
  and updated to reflect what the system can actually do today (the file is
  consumed by the official auto-grader; lying there is not allowed —
  see `docs/refusal-policy.md` §"why we don't fake metrics").

## Submission gate (must all be true before final tag)

- [ ] Live URL is publicly reachable, no login required
- [ ] `自测报告/latest_evaluation_metrics.md` reflects real measured numbers
- [ ] `架构文档/design_doc.md` is the 4–8 page final cut
- [ ] `演示视频/` contains the demo recording
- [ ] `运行脚本/start.sh` boots the system from a clean clone
- [ ] Default branch is the one the organizer clones (default > master > main)
- [ ] Minimum 3 chart types implemented end-to-end
- [ ] Refusal flow returns the canonical phrasing for trap questions
- [ ] Multi-turn follow-up keeps session state across turns
