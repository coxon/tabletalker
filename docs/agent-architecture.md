# Agent Architecture

Skeleton placeholder. The full design lands in PR #7 (`docs/architecture`).
This file exists from PR #2 so later PRs have a stable target to append into.

## Anchor points (to be filled)

- **Planner** — turns the user's question + dataset profile into a typed plan.
- **Executor** — runs each plan step in a pandas sandbox, capturing dataframes
  and figures.
- **InsightAgent** — narrates the executed steps into a Jinja-rendered HTML
  report with embedded Plotly charts.
- **Critic** — re-reads the report against the data, flags unsupported claims.
- **Session memory** — keeps the dataset and prior turns in context for
  follow-up questions.

See [`PRODUCT.md`](../PRODUCT.md) for product framing and
[`docs/roadmap.md`](roadmap.md) for the shipping plan.
