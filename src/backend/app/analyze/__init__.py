"""Analyze pipeline — owns the public submission contract.

The pipeline is a small orchestrator that turns one (file, question)
upload into the JSON shape `docs/submission-contract.md` mandates.

Boundary of responsibility:

- `schema.py` — Pydantic models that *are* the contract. Field names,
  optionality, refusal payload — all frozen.
- `profiler.py` — quick, no-LLM table profile. Column dtypes, NA stats,
  small samples. Feeds the planner so it doesn't ask the LLM to guess
  schema.
- `evidence.py` — turns each plan run into an `Evidence` row with
  reproducible (dataset, table, columns, filters, aggregation, value)
  fields the auto-grader can replay.
- `handler.py` — the orchestrator. Single-shot for now; PR #4 follow-ups
  add a ReAct loop and refusal classification on top.

The internal `/spreadsheet/*` engine (PR #3.5) does all the heavy
lifting — this package wraps it in the contract shape and adds the
audit trail (`evidence`) the grader needs.
"""
