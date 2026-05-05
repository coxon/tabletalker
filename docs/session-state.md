# Session state and follow-up

The auto-grader's follow-up tests use pronouns and references like
"the high-value cohort we just identified", "those three categories",
"compared to before". A planner that re-derives everything on each
turn either disagrees with the previous turn's cohort definition or
takes too long. This document defines what the system remembers
between turns and how a follow-up prompt is assembled.

## 1. What is a "session"

One session = one parent analysis (`/v1/analyze`) plus zero
or more follow-ups (`/v1/follow-up`). Sessions are keyed by
the parent's `id`. Follow-ups carry `parent_id`.

Sessions are in-memory for the eval window — see
[`architecture.md`](architecture.md) §7.

## 2. What the session store keeps

```python
@dataclass
class Session:
    id: str                              # parent analysis id
    workspace_dir: Path                  # where the upload(s) live
    dataset_profile: DatasetProfile      # from PR #4 profiler
    original_question: str
    findings: list[Finding]              # all findings produced so far
    cohorts: dict[str, CohortDef]        # name → filter spec
    chart_ids: list[str]                 # already-rendered chart anchors
    refused: bool                        # if the parent was refused
    turns: list[Turn]                    # full Q-and-response history
```

### Cohort definition

```python
@dataclass
class CohortDef:
    name: str                            # human-friendly: "高价值客群"
    filters: str                         # the actual pandas filter
    columns_used: list[str]
    row_count: int                       # for pronoun-resolution sanity
    introduced_in_turn: int
```

Cohorts are extracted automatically from the parent's findings — any
finding whose evidence has a `filters` field that produced more than
one row becomes a candidate cohort. Names are LLM-generated during the
parent run and stored.

## 3. Follow-up prompt assembly

When a follow-up arrives, the planner's system prompt is rebuilt from
the parent session as:

```text
You are a data analysis agent. The user has already had this analysis:

Parent question: {original_question}

Findings established (with evidence available, do not re-derive):
1. {finding 1 title} — {finding 1 detail}
2. {finding 2 title} — ...

Named cohorts in this session (you can refer to them by name):
- 高价值客群 := {filters: "Age >= 55", n=847}
- 流失高发部门 := ...

Charts already rendered (do not duplicate; reference by html_anchor):
- #chart-age-bar (柱状图: 各年龄段平均客单价)
- ...

Now answer this follow-up:
{follow_up_question}
```

Pronoun resolution then becomes the LLM's job — but with the named
cohorts in scope, "they" / "those" / "the cohort" resolve cleanly
without the planner having to reason from scratch.

## 4. When does the follow-up reuse vs re-analyze?

The planner is instructed to:

- **Reuse** a finding's filter / aggregation when the follow-up asks
  for a slice of an already-named cohort.
- **Run new code** when the follow-up adds a new dimension (e.g. parent
  found "55+ has higher spend"; follow-up asks "across what
  categories?" — needs new groupby).
- **Run new code with the cohort filter** is the most common path.

The session store does not pre-compute these; it just provides the
context. The planner decides based on the system-prompt rules above.

## 5. What follow-ups CANNOT do

- Switch datasets. A follow-up against a different dataset is a new
  parent analysis; the planner refuses follow-ups whose `dataset` (if
  supplied) doesn't match the parent's.
- Resurrect refused parents. If the parent was refused, the follow-up
  is also refused with the canonical phrasing — there's no path from
  "we couldn't analyze this" to "let me try again with more
  information" within the same session.

## 6. Eviction / cleanup

The eval harness is the only client; it makes ≤ ~100 sessions per
window. Memory budget is generous, so we evict only:

- on backend restart (full clear);
- after 24 h of idle time (TTL);
- when total in-memory cohort count exceeds 10 k (LRU on parent id).

The eviction policy is implemented in PR #6.

## 7. Trace recording

Every turn writes a JSONL line to
`workspace/{parent_id}/trace.jsonl`:

```json
{"turn": 0, "kind": "parent", "question": "...", "tools": [...], "findings": [...]}
{"turn": 1, "kind": "follow-up", "question": "...", "reused_cohorts": ["高价值客群"], "new_findings": [...]}
```

This is the audit log used to populate the "可观测性" subsection in
`architecture.md` §3 and the demo-video script in PR #9.
