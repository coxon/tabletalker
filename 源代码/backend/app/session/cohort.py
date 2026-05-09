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
      - Prefer a count evidence row that already carries a filter. Top-N
        grouped reports often have a whole-table `count(*)` followed by
        the winning group's filtered count; the latter is the reusable
        follow-up scope.
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
        row_count = _evidence_row_count(primary)
        if row_count is None or row_count <= 1:
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
                row_count=row_count,
                introduced_in_turn=turn_index,
            )
        )
    return out


def _primary_evidence(evidence: list[Evidence]) -> Evidence | None:
    """Return the evidence row that best defines a reusable cohort.

    The evidence builder usually emits a whole-table `count(*)` before
    per-group rows. For follow-ups like "其中哪部影片最受欢迎", the per-group
    filtered count is the real antecedent, not the whole table.
    """

    for ev in evidence:
        if ev.filters and _is_count_aggregation(ev.aggregation):
            return ev
    for ev in evidence:
        if ev.filters:
            return ev
    for ev in evidence:
        if _is_count_aggregation(ev.aggregation):
            return ev
    return evidence[0] if evidence else None


def _is_count_aggregation(aggregation: str) -> bool:
    return aggregation.strip().lower().startswith("count(")


def _evidence_row_count(evidence: Evidence) -> int | None:
    if evidence.row_count is not None:
        return evidence.row_count
    if not _is_count_aggregation(evidence.aggregation):
        return None
    value = evidence.value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


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
