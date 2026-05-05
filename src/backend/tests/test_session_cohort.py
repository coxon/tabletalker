"""Cohort-extraction unit tests.

`extract_cohorts` is the deterministic bridge between a parent
`AnalyzeResponse` and the named subsets the follow-up planner sees in
its system prelude. The rules under test mirror `docs/session-state.md`
§2: skip empty filters, skip row_count ≤ 1, dedupe by (filters, name).
"""

from __future__ import annotations

from app.analyze.schema import Evidence, Finding
from app.session import extract_cohorts


def _ev(
    *,
    filters: str = "",
    row_count: int | None = 100,
    aggregation: str = "count(*)",
    columns: list[str] | None = None,
) -> Evidence:
    return Evidence(
        dataset="sales",
        table="sales.csv",
        columns=columns or ["region"],
        filters=filters,
        aggregation=aggregation,
        value=row_count if row_count is not None else 0,
        row_count=row_count,
    )


def _finding(title: str, evidence: list[Evidence]) -> Finding:
    return Finding(title=title, detail=f"detail for {title}", evidence=evidence)


def test_extract_cohorts_picks_count_evidence_with_filter() -> None:
    findings = [
        _finding(
            "华东高价值客群",
            [
                _ev(filters="region == '华东' and amount >= 100", row_count=500),
                _ev(filters="region == '华东'", row_count=500, aggregation="mean(amount)"),
            ],
        )
    ]
    cohorts = extract_cohorts(findings, turn_index=0)
    assert len(cohorts) == 1
    cohort = cohorts[0]
    assert cohort.name == "华东高价值客群"
    assert cohort.filters == "region == '华东' and amount >= 100"
    assert cohort.row_count == 500
    assert cohort.introduced_in_turn == 0


def test_extract_cohorts_skips_empty_filter() -> None:
    """A finding over the whole table is not a 'cohort' worth naming."""

    findings = [_finding("整体概览", [_ev(filters="", row_count=10_000)])]
    assert extract_cohorts(findings) == []


def test_extract_cohorts_skips_singleton_groups() -> None:
    """Cohorts of size 1 are uninteresting — pronoun resolution doesn't help."""

    findings = [_finding("唯一记录", [_ev(filters="id == 7", row_count=1)])]
    assert extract_cohorts(findings) == []


def test_extract_cohorts_skips_missing_row_count() -> None:
    """`row_count` is optional in the schema; a None value can't be sized."""

    findings = [_finding("未知规模", [_ev(filters="region == '华南'", row_count=None)])]
    assert extract_cohorts(findings) == []


def test_extract_cohorts_dedupes_identical_filters() -> None:
    """Re-runs of the same parent shouldn't double-count cohorts."""

    findings = [
        _finding("A", [_ev(filters="region == '华东'", row_count=100)]),
        _finding("A", [_ev(filters="region == '华东'", row_count=100)]),
    ]
    cohorts = extract_cohorts(findings)
    assert len(cohorts) == 1


def test_extract_cohorts_keeps_distinct_names_with_same_filter() -> None:
    """Different finding titles with the same filter ARE different cohorts."""

    findings = [
        _finding("销售视角", [_ev(filters="region == '华东'", row_count=100)]),
        _finding("利润视角", [_ev(filters="region == '华东'", row_count=100)]),
    ]
    cohorts = extract_cohorts(findings)
    assert {c.name for c in cohorts} == {"销售视角", "利润视角"}


def test_extract_cohorts_uses_turn_index() -> None:
    findings = [_finding("追问群体", [_ev(filters="age >= 60", row_count=42)])]
    cohorts = extract_cohorts(findings, turn_index=3)
    assert cohorts[0].introduced_in_turn == 3


def test_extract_cohorts_handles_no_count_evidence() -> None:
    """If no `count(*)` row exists, the first row stands in."""

    findings = [
        _finding(
            "替补主行",
            [_ev(filters="age >= 60", row_count=42, aggregation="mean(amount)")],
        )
    ]
    cohorts = extract_cohorts(findings)
    assert len(cohorts) == 1
    assert cohorts[0].name == "替补主行"
