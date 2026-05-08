# AGENTS.md — TableTalker

A data analysis agent: takes structured data (CSV/Excel) and a natural-language
request, produces an interactive HTML report, supports follow-up questions.

## Rules

1. **Required submission directories** (per organizer spec):
   `src/` · `架构文档/` · `运行脚本/` · `演示视频/` · `自测报告/`.
   `docs/` and `tests/` are kept for project completeness.

2. **Self-test file is sacred.** `自测报告/latest_evaluation_metrics.md`
   must exist at the repo root path with that exact name — the organizer's
   auto-grader reads it directly. Missing file = 0 score. Numbers in it are
   measured, not estimated; see `docs/refusal-policy.md` §"why we don't
   fake metrics".

3. **Refuse > hallucinate.** If a finding can't be reproduced from the input
   data, the report says so. Enforced by `tests/test_refusal.py` and
   `docs/refusal-policy.md` (4 trap categories with canonical phrasings).

4. **Submission contract is frozen.** `/v1/analyze` returns the JSON shape
   defined in `docs/submission-contract.md` — every field, every key. Do
   not drift.

5. **Branch rule for organizer pull.** Their script clones `default > master
   > main` in that order. Whatever branch we want graded must be the
   default branch at submission time.

## Skills

- **impeccable** for frontend craft (needs `PRODUCT.md` ≥200 chars).
- **emil-style** for the default aesthetic (quiet, refined).
- **mempalace** for cross-session memory; diary tag `tabletalker`.

## Pointers

`README.md` · `PRODUCT.md` · `docs/roadmap.md` · `docs/architecture.md` ·
`docs/submission-contract.md` · `docs/scoring-map.md` ·
`docs/refusal-policy.md` · `docs/session-state.md` · `.env.example`
