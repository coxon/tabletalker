# Scoring map

The official rubric (赛题4 §6) splits 100 points into objective (50%)
and subjective (50%). This file maps every line item to (a) the module
that owns it, (b) the PR that lands it, and (c) where we'll measure
ourselves before submission.

> Final score = objective × 0.5 + subjective × 0.5
> Both sub-scores are out of 100.

## 1. Objective (100) — auto-graded from `自测报告/latest_evaluation_metrics.md`

| Item | Pts | Owner module | Lands in | Self-measure rubric |
|---|---:|---|---|---|
| **Data ingestion** | **20** | `app/upload/`, `app/profiler/` | PR #4, #7 | |
|   single-file CSV or Excel | 6 | upload | #4 | upload one of each, profiler reports schema |
|   single + multi-file | 14 | upload | #7 | TMDB two-file dataset round-trip |
|   both CSV and Excel | 20 | upload | #7 | each format produces identical profile |
| **Interaction** | **20** | `app/api/`, `app/session/` | PR #4, #6 | |
|   single-turn | 5 | analyze handler | #4 | one question → contract response |
|   multi-turn | 15 | follow-up + session | #6 | pronouns resolve, cohort persists |
|   both | 20 | combined | #6 | end-to-end conversation script |
| **Statistical analysis** | **16** | planner + sandbox | PR #4 | runs sample size, distributions, Top N, group-by; correctness checked against pandas reference |
| **Trend analysis** | **18** | planner + sandbox | PR #4 | uses time / ordered category fields; produces direction + magnitude with evidence |
| **Root-cause analysis** | **26** | planner | PR #4, #6 | identifies factors, explains why, closes loop with recommendations |

### Where the objective score actually comes from

The auto-grader reads `自测报告/latest_evaluation_metrics.md` and tallies the
numbers we put there. It does **not** re-run our system. The implication:

1. The numbers in that file must be **truthful** — see organizer §7.4
   anti-cheat rules. We never inflate.
2. We update the file at the end of every PR that changes capabilities.
3. The file is created with all-zero / "not yet implemented" entries
   in PR #3 (this PR) and refined incrementally.

The file format is fixed by the organizer template. See the file
itself for section structure.

## 2. Subjective (100) — human review

| Item | Pts | What reviewers look at | Lands in | Self-measure |
|---|---:|---|---|---|
| **Architecture** | **40** | `架构文档/design_doc.md`, `docs/architecture.md`, code structure | PR #3, #9 | self-review checklist below |
|   layering | 12 | clear module boundaries, interfaces | all PRs | each PR adds at most one module per directory |
|   extensibility | 12 | plugin points, room to add chart types / tools | PR #4, #5 | new tool addable without touching planner core |
|   performance | 8 | caching, async, fallbacks | PR #4, #8 | latency target in `architecture.md` §6 |
|   security | 8 | sandbox, no path escape, no SQL injection | PR #4 | sandbox tests in `tests/test_sandbox/` |
| **Innovation** | **40** | what makes it not generic | PR #4–#7, #9 | |
|   interaction paradigm | 8 | UI×CLI, multimodal | PR #7 | UX walkthrough in design doc |
|   data processing | 8 | pipeline cleverness | PR #4 | profiler heuristics + sampling annotation |
|   algorithm | 15 | LLM use, prompt design, refusal classifier | PR #4, #6 | prompt registry + ablation table |
|   report design | 5 | aesthetic, drill-down, narrative | PR #5 | side-by-side vs vanilla pandas-profiling |
| **Output completeness** | **20** | the four mandatory deliverables | PR #3, #8, #9 | |
|   architecture doc | 5 | topology + sequence + dictionary | PR #3 (start), #9 (final) | follows organizer's design_doc_template structure |
|   demo video | 5 | clear narration, ≤5 min | PR #9 | recorded against the live URL |
|   self-test report | 5 | edge cases + perf data, not just "tests passed" | PR #8 | populated `latest_evaluation_metrics.md` + load-test entries |
|   git quality | 5 | LICENSE, README, structure, no dead code | every PR | LICENSE present ✓, README detailed ✓, no `//TODO: figure out` left at submission |

## 3. Forbidden under §7.4 (instant DQ)

We don't do these and we don't get clever about them:

1. Stash hidden test datasets / questions for later use. We never see
   them outside the eval window; if we did we wouldn't keep them.
2. Pre-hash datasets to skip analysis. Every request walks the full
   pipeline.
3. Outbound network calls during eval other than the declared LLM
   gateway. Sandbox enforces this; we audit `httpx`/`urllib` usage in
   `tests/test_no_egress.py` (PR #4).
4. Read files outside `data/` (or the per-request workspace). Sandbox
   path-resolver refuses; tested in `tests/test_sandbox_isolation.py`.
5. Call any LLM that wasn't declared in the design doc.

## 4. Big risks per category (organizer §7.2)

| Risk | Where we mitigate | Test |
|---|---|---|
| Refuse a real question by mistake | refusal classifier is **conservative** — only refuses on hard signals | `tests/test_refusal_negatives.py` (PR #6): a battery of valid questions must NOT be refused |
| Hallucinated evidence numbers | evidence builder reads from sandbox stdout only; planner forbidden from emitting bare numbers | `tests/test_evidence_replay.py` (PR #4): replay each evidence and bit-compare |
| JSON-nested fields not parsed | profiler detects JSON-string columns and the planner is prompted to `json.loads + explode` | TMDB-specific test in PR #4 |
| Boilerplate intro / verbose summary | planner's system prompt forbids it; renderer truncates summary >500 chars | `tests/test_summary_shape.py` (PR #5) |
| Charts < 3 types | renderer asserts ≥3 distinct types before allowing the response to ship | `tests/test_chart_diversity.py` (PR #5) |
| Sampling not annotated | sandbox auto-attaches `sampling_rate` when row count exceeds the cap; evidence builder includes it | `tests/test_sampling_annotation.py` (PR #4) |
| Follow-up loses context | session store + planner prompt template; pronoun-resolution test set | `tests/test_followup_context.py` (PR #6) |
