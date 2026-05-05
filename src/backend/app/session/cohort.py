"""Cohort extraction — promote findings into reusable named subsets.

`docs/session-state.md` §2 says any finding whose evidence is filtered
to >1 row becomes a candidate cohort. The follow-up planner gets these
names in scope so pronouns ("they", "those") resolve cleanly.

This module is the entry point that walks an `AnalyzeResponse`'s
`findings.evidence` and returns one `CohortDef` per qualifying group.
The extractor is deterministic — naming uses the finding title plus the
filter clause as a stable shorthand, never a fresh LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analyze.schema import Evidence, Finding


@dataclass(frozen=True)
class CohortDef:
    """A named subset the follow-up planner can refer to by short name.

    `filters` is the *pandas-eval predicate* the original Evidence row
    carried — replayable verbatim. `row_count` is the post-filter total
    so the planner can sanity-check before re-running.
    """

    name: str
    filters: str
    columns_used: list[str] = field(default_factory=list)
    row_count: int = 0
    introduced_in_turn: int = 0


def extract_cohorts(
    findings: list[Finding], *, turn_index: int = 0
) -> list[CohortDef]:
    """Pull cohort definitions out of one turn's findings.

    Rules:
      - Only the *first* Evidence row per finding is considered the
        finding's defining filter — that's the `count(*)` row our
        evidence builder always emits.
      - Skip findings whose filter is empty (the whole table) or whose
        row count is zero/None.
      - De-duplicate by `(filters, name)` so re-runs of the same parent
        analysis don't double-count.
    """

    out: list[CohortDef] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        if not finding.evidence:
            continue
        primary = _primary_evidence(finding.evidence)
        if primary is None:
            continue
        if not primary.filters:
            continue
        if primary.row_count is None or primary.row_count <= 1:
            continue

        name = _cohort_name(finding, primary)
        key = (primary.filters, name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            CohortDef(
                name=name,
                filters=primary.filters,
                columns_used=list(primary.columns),
                row_count=primary.row_count,
                introduced_in_turn=turn_index,
            )
        )
    return out


def _primary_evidence(evidence: list[Evidence]) -> Evidence | None:
    """Return the count(*) evidence row; falls back to the first row.

    The evidence builder (`app.analyze.evidence`) emits one count(*) row
    per finding before the per-group rows, so it's almost always at
    index 0 — but defending against future changes here is cheap.
    """

    for ev in evidence:
        if ev.aggregation == "count(*)":
            return ev
    return evidence[0] if evidence else None


def _cohort_name(finding: Finding, primary: Evidence) -> str:
    """Stable, human-readable shorthand.

    The finding title is already a Chinese phrase the user can re-use
    ("华东销售领先") so we use it as the cohort name — no LLM round-trip
    needed. If two findings share a title, the filter disambiguates them
    via the de-dupe set in `extract_cohorts`.
    """

    return finding.title.strip() or _fallback_name(primary)


def _fallback_name(primary: Evidence) -> str:
    """Filter-only name used when the finding has no title.

    Worst case the user-visible name is something like ``cohort: Age >= 55``,
    which is at least obviously identifying.
    """

    return f"cohort: {primary.filters}"
