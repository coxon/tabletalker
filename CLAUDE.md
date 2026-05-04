# CLAUDE.md — TableTalker

A data analysis agent: takes structured data (CSV/Excel) and a natural-language
request, produces an interactive HTML report, supports follow-up questions.

## Rules

1. **Required submission directories** (per organizer spec):
   `src/` · `架构文档/` · `运行脚本/` · `演示视频/` · `自测报告/`.
   `docs/` and `tests/` are kept for project completeness.

2. **Refuse > hallucinate.** If a finding can't be reproduced from the input
   data, the report says so. Enforced by `tests/test_refusal.py`.

## Skills

- **impeccable** for frontend craft (needs `PRODUCT.md` ≥200 chars).
- **emil-style** for the default aesthetic (quiet, refined).
- **mempalace** for cross-session memory; diary tag `tabletalker`.

## Pointers

`README.md` · `PRODUCT.md` · `docs/hackathon-brief.md` · `.env.example`
