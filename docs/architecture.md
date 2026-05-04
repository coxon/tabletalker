# Architecture

> Living document. Updated each PR. The Chinese-language equivalent for
> the organizer (`架构文档/design_doc.md`) tracks this file but is held
> stable until PR #9.

## 1. What we are building

A web-deployed agent that:

1. Accepts a natural-language analysis request together with a CSV/Excel
   file (or files), through a public, login-free Web UI.
2. Profiles the data, plans an analysis, runs real pandas code in a
   sandbox, extracts numeric evidence from those runs, and assembles an
   interactive HTML report with ≥3 chart types.
3. Responds to multi-turn follow-up questions while preserving session
   state (already-identified cohorts, applied filters, generated chart
   IDs).
4. **Refuses** trap questions with a canonical phrasing whenever the
   data cannot support the analysis (missing field, dimension mismatch,
   inducement to hallucinate, out-of-scope request).

The submission contract (the JSON shape we return) lives in
[`submission-contract.md`](submission-contract.md). The auto-grader
reads `自测报告/latest_evaluation_metrics.md` to compute the objective
score; how that file is maintained is in
[`scoring-map.md`](scoring-map.md).

## 2. Top-level topology

```
                         ┌──────────────────────┐
   Browser  ─── HTTP ──▶ │  Next.js frontend    │
                         │  (file picker, chat) │
                         └──────────┬───────────┘
                                    │ POST /spreadsheet/analyze
                                    │ POST /spreadsheet/follow-up
                                    │ GET  /reports/{id}.html
                                    ▼
                         ┌──────────────────────┐
                         │  FastAPI backend     │
                         │  ┌────────────────┐  │
                         │  │ Profiler       │  │  describe schema, types,
                         │  │                │  │  missing rates, JSON cols
                         │  ├────────────────┤  │
                         │  │ Planner (LLM)  │──┼──▶ AsiaInfo LLM gateway
                         │  │ ReAct loop     │  │  (OpenAI-compat HTTP)
                         │  ├────────────────┤  │
                         │  │ Sandbox runner │  │  pandas in subprocess,
                         │  │  (run code +   │  │  walltime + memory caps,
                         │  │   capture df)  │  │  data/ read-only
                         │  ├────────────────┤  │
                         │  │ Evidence build │  │  filters, aggregation,
                         │  │ Refusal class. │  │  value, row_count
                         │  ├────────────────┤  │
                         │  │ Report render  │  │  Jinja + Plotly JSON
                         │  │ (HTML + JSON)  │  │  → /reports/{id}.html
                         │  ├────────────────┤  │
                         │  │ Session store  │  │  in-memory keyed by
                         │  │  (per-session) │  │  parent_id
                         │  └────────────────┘  │
                         └──────────────────────┘
```

The audit/trace layer (the `app.spreadsheet` typed-plan module landing
in PR #3.5) sits next to the sandbox runner — it doesn't replace
real code execution; instead it **types** the operations so the
evidence extractor can build a precise `(filters, aggregation, value)`
tuple from each run. See "Why both ReAct and a typed plan?" below.

## 3. Module responsibilities

### 3.1 Profiler — `app/profiler/`

- Inputs: a workspace directory containing one or more uploaded files.
- Outputs:
  - For each file: column dtype, null rate, distinct count, top values,
    detected nature (numeric / categorical / temporal / JSON-string / id).
  - Cross-file: detected join keys (column-name + value-overlap heuristic).
- Runs once per analysis request before the planner is consulted —
  this implements the organizer's "先探查后规划" recommendation and
  defuses the JSON-nested-field landmine (TMDB `genres` etc.).

### 3.2 Planner — `app/agent/planner.py`

- ReAct loop over the AsiaInfo LLM gateway (OpenAI-compatible HTTP).
- Tools the planner can call:
  - `run_pandas_code(code) → {stdout, dataframes_preview, error?}`
  - `make_chart(spec) → {chart_id, html_anchor}`
  - `refuse(reason_code, narrative) → terminal`
  - `finish(findings, charts, recommendations) → terminal`
- Each LLM turn: system prompt + dataset profile + conversation so far.
- Retries: on `error`, traceback is fed back; max 3 retries per code
  attempt (organizer's recommended cap).
- The planner is forbidden from emitting raw analytical numbers in its
  own message — every numeric claim must come from a successful
  `run_pandas_code` invocation. This is enforced post-hoc by the
  evidence builder.

### 3.3 Sandbox — `app/sandbox/`

- pandas executed in a child Python process (subprocess) with:
  - Walltime cap (default 30 s per cell, 120 s per request).
  - RSS cap (default 1 GiB).
  - File-read whitelist: only the request's workspace dir; no `/etc`,
    no network.
  - No outbound network: enforced via `httpx`-blocking shim and
    `subprocess` with cleared `HTTPS_PROXY`/`HTTP_PROXY`.
- DataFrames returned to the parent over pickle, capped at 50 k rows
  (the parent re-runs with sampling and an explicit `sampling_rate`
  annotation if larger).

### 3.4 Evidence builder — `app/evidence/`

- For every successful `run_pandas_code` call, extracts:
  `dataset / table / columns / filters / aggregation / value / row_count`.
- Heuristics:
  - `filters` extracted from the boolean mask AST (e.g. `df[df.Age >= 55]`
    → `"Age >= 55"`).
  - `aggregation` parsed from method calls (`.mean()`, `.sum()`,
    `groupby(...).agg(...)`).
  - `value` is the scalar or first cell of the result.
  - `row_count` is the post-filter mask sum, captured before the
    aggregation reduces to scalar.
- If filter or aggregation cannot be cleanly extracted, the builder
  refuses to attach evidence to that finding and the planner is
  prompted to re-do the cell. **No guessing.**

### 3.5 Refusal classifier — `app/refusal/`

- Pre-flight (before planner): runs against the user query + dataset
  profile.
  - Field presence check (entity → column-name fuzzy match).
  - Dataset×question coherence (question mentions concept clearly
    absent from any column).
- In-flight (during planner): triggered if the planner repeatedly
  fails to produce a non-zero-row aggregation.
- Output: structured refusal payload that maps onto the canonical
  phrasing in [`refusal-policy.md`](refusal-policy.md).

### 3.6 Report renderer — `app/report/`

- Jinja2 template + Plotly figures emitted as embedded JSON
  (`<div id="..."></div>` + `Plotly.newPlot(...)`).
- Output written to `reports/{id}.html` and served from the same
  FastAPI service at `GET /reports/{id}.html`.
- The report is a single self-contained HTML file — no live API calls
  on viewing.

### 3.7 Session store — `app/session/`

- Keyed by analysis `id`. Holds:
  - dataset profile, original question, generated findings, chart IDs,
    cohort definitions ("the high-value cohort = Age ≥ 55").
- Follow-up requests carry `parent_id`; the planner's system prompt
  includes the parent session's running summary plus a list of named
  cohorts so pronouns ("they") resolve unambiguously.

## 4. Why both ReAct (PR #4) and a typed plan (PR #3.5)?

The competition's anti-hallucination rule (no fabricated numbers) is
strict — every evidence value must trace back to actual code that ran.
The straightforward way to satisfy this is a ReAct loop where the LLM
writes pandas code and reads the output, which is what PR #4
implements.

The typed-plan module (the "spreadsheet engine" parked from earlier
exploration) doesn't replace ReAct — instead it gives us a **structured
audit log** for each step the planner emits. When the planner runs
`df.groupby("region")["amount"].sum()`, the typed-plan module records
this as a `group_by` op and an `aggregate` op, which makes the
evidence builder's job mechanical instead of regex-y.

PR #4 may also use the typed plan as an *alternative* path for simple
questions — if the LLM's first turn already emits a complete typed plan
that validates, we skip the ReAct loop and run it directly. This
fast-path will be measured for accuracy in PR #8 before we decide
whether to keep it on by default.

## 5. Data flow on a single analysis request

1. Browser uploads file(s) + question → `POST /spreadsheet/analyze`
   (multipart).
2. Backend creates `workspace/{request_id}/`, saves uploads, calls
   profiler.
3. Refusal classifier runs pre-flight; on refusal → return canonical
   refusal payload, skip planner.
4. Planner runs ReAct loop, calling sandbox tools. Each
   `run_pandas_code` result is captured into the trace.
5. After `finish` (or refusal mid-loop), the evidence builder enriches
   each finding with at least one `evidence` block.
6. Report renderer produces `reports/{request_id}.html` and embedded
   chart anchors.
7. Response shape (see `submission-contract.md`):
   ```
   { id, report_html_url, summary, findings, charts,
     recommendations, is_refusal, confidence }
   ```
8. Session store persists profile + findings + cohort names so the next
   `POST /spreadsheet/follow-up` can resolve pronouns.

## 6. Non-functional requirements

| NFR | Target | Source |
|---|---|---|
| Single-analysis end-to-end latency (≤10 MB file) | ≤ 60 s p95 | own SLO |
| Follow-up latency | ≤ 20 s p95 | own SLO |
| Sandbox isolation (file/network) | hard | organizer §7.4 |
| Public URL availability during eval window | 100 % | organizer §6.D |
| Concurrent analyses | ≥ 4 | own SLO |
| Result reproducibility | bit-exact within ±1 e-6 of stand-alone pandas | organizer §7.1 |

## 7. Things deliberately left out (until later)

- Persistent storage. All session state is in-memory, lost on restart.
  Acceptable for the eval window; flagged for post-hackathon follow-up.
- Authentication. The organizer requires login-free access (§6.D).
  Production deployment after the contest will add a token gate.
- Cross-process job queue. Single-process `asyncio` is sufficient at
  the expected concurrency. We monitor and document this in §6 above.
- Rate limiting. Same reasoning — eval-window assumption, not a
  production assumption.
