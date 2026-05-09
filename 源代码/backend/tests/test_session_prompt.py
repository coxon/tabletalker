"""Follow-up prompt assembly tests.

The prompt is the LLM's only window into the parent turn — we lock the
section ordering and the named-cohort framing so a regression here is
caught before it confuses the planner.
"""

from __future__ import annotations

from pathlib import Path

from app.analyze.schema import Evidence, Finding
from app.session import (
    CohortDef,
    Session,
    render_followup_system_prompt,
)


def _session(
    *,
    refused: bool = False,
    findings: list[Finding] | None = None,
    cohorts: list[CohortDef] | None = None,
    chart_anchors: list[str] | None = None,
) -> Session:
    return Session(
        id="eval_analysis_abc",
        workspace_dir=Path("/tmp/x"),
        filename="data.csv",
        dataset="sales",
        original_question="各地区的销售额？",
        findings=findings or [],
        parent_summary="parent summary verbatim",
        cohorts=cohorts or [],
        chart_anchors=chart_anchors or [],
        refused=refused,
    )


def test_prompt_for_happy_session_includes_all_sections() -> None:
    findings = [
        Finding(
            title="华东销售领先",
            detail="华东总额 300，华南总额 50。",
            evidence=[
                Evidence(
                    dataset="sales",
                    table="sales.csv",
                    columns=["region", "amount"],
                    filters="region == '华东'",
                    aggregation="sum(amount)",
                    value=300,
                    row_count=2,
                )
            ],
        )
    ]
    cohorts = [
        CohortDef(
            name="华东高值",
            filters="region == '华东'",
            columns_used=["region"],
            row_count=2,
        )
    ]
    chart_anchors = ["#chart-amount-bar"]
    session = _session(findings=findings, cohorts=cohorts, chart_anchors=chart_anchors)
    prompt = render_followup_system_prompt(session, "他们的环比增长是？")

    # Section headers locked to the doc spec.
    assert "原始问题" in prompt
    assert "已确认的发现" in prompt
    assert "已命名的群体" in prompt
    assert "已渲染的图表" in prompt
    assert "追问" in prompt

    # Content surfacing.
    assert "华东销售领先" in prompt
    assert "华东高值" in prompt
    assert "region == '华东'" in prompt
    assert "#chart-amount-bar" in prompt
    assert "他们的环比增长" in prompt


def test_prompt_binds_ambiguous_followup_to_prior_top_entity() -> None:
    findings = [
        Finding(
            title="美国产量占据绝对主导",
            detail="美国以3956部电影产量位列第一。",
            evidence=[
                Evidence(
                    dataset="movies",
                    table="tmdb.csv",
                    columns=["production_countries"],
                    filters="production_countries == 'United States of America'",
                    aggregation="count(production_countries)",
                    value=3956,
                    row_count=3956,
                )
            ],
        )
    ]
    cohorts = [
        CohortDef(
            name="美国产量占据绝对主导",
            filters="production_countries == 'United States of America'",
            columns_used=["production_countries"],
            row_count=3956,
        )
    ]
    session = _session(findings=findings, cohorts=cohorts)

    prompt = render_followup_system_prompt(session, "其中哪部影片最受欢迎？")

    assert "其中" in prompt
    assert "该地区" in prompt
    assert "Top1" in prompt
    assert "必须先沿用该实体过滤" in prompt
    assert "当前追问默认作用域" in prompt
    assert "必须在加载数据后先应用以下过滤条件" in prompt
    assert "production_countries == 'United States of America'" in prompt


def test_prompt_does_not_force_scope_when_followup_requests_whole_dataset() -> None:
    cohorts = [
        CohortDef(
            name="美国产量占据绝对主导",
            filters="production_countries == 'United States of America'",
            columns_used=["production_countries"],
            row_count=3956,
        )
    ]
    session = _session(cohorts=cohorts)

    prompt = render_followup_system_prompt(session, "全量数据里哪部影片最受欢迎？")

    assert "当前追问默认作用域" not in prompt
    assert "production_countries == 'United States of America'" in prompt


def test_prompt_default_scope_uses_latest_turn_cohort() -> None:
    cohorts = [
        CohortDef(
            name="父轮美国",
            filters="production_countries == 'United States of America'",
            columns_used=["production_countries"],
            row_count=3956,
            introduced_in_turn=0,
        ),
        CohortDef(
            name="追问动画片",
            filters="genre == 'Animation'",
            columns_used=["genre"],
            row_count=234,
            introduced_in_turn=1,
        ),
    ]
    session = _session(cohorts=cohorts)

    prompt = render_followup_system_prompt(session, "其中评分最高的是？")

    scope_section = prompt.split("**当前追问默认作用域（强约束）**：", 1)[1]
    assert "genre == 'Animation'" in scope_section
    assert "production_countries == 'United States of America'" not in scope_section


def test_prompt_omits_optional_sections_when_empty() -> None:
    """No findings → no findings header, etc. We don't want the LLM
    inventing content to fill empty bullet lists."""

    session = _session()
    prompt = render_followup_system_prompt(session, "x")
    assert "已确认的发现" not in prompt
    assert "已命名的群体" not in prompt
    assert "已渲染的图表" not in prompt
    assert "原始问题" in prompt  # original question is always present


def test_prompt_for_refused_parent_uses_static_prelude() -> None:
    """Refusal carry-through commits the planner to the canonical narrative;
    no findings/cohorts/charts get exposed even if accidentally populated."""

    session = _session(refused=True)
    prompt = render_followup_system_prompt(session, "再试试看")
    assert "拒答" in prompt
    assert "再试试看" in prompt
    # The "happy" sections must never leak into the refusal prelude.
    assert "已命名的群体" not in prompt
    assert "已渲染的图表" not in prompt


def test_prompt_truncates_long_finding_details() -> None:
    """Compactness matters — the planner only needs the gist."""

    long_detail = "细节" * 200
    findings = [
        Finding(
            title="t",
            detail=long_detail,
            evidence=[
                Evidence(
                    dataset="d",
                    table="t.csv",
                    columns=["a"],
                    filters="a > 0",
                    aggregation="count(*)",
                    value=1,
                    row_count=2,
                )
            ],
        )
    ]
    session = _session(findings=findings)
    prompt = render_followup_system_prompt(session, "x")
    # Output line is bounded by the trim length plus ellipsis.
    assert "…" in prompt
    assert long_detail not in prompt
