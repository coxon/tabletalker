"""Submission-contract response models — the frozen public shape.

Every field here is dictated by `docs/submission-contract.md`. Renames or
type changes go through that doc first; never silently here.

Why a fresh module instead of reusing `app.spreadsheet.schema`:

- The spreadsheet schema is the *internal* plan IR (Op kinds, register
  references). The auto-grader never sees it.
- The submission contract is what the grader keys on. Mixing the two
  would tempt us to leak engine-internal field names into the response.

This module deliberately keeps `extra="forbid"` so any drift from the
contract is caught at response-construction time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class _StrictModel(BaseModel):
    """Common base — reject unknown fields so we never silently drift."""

    model_config = {"extra": "forbid"}


class Evidence(_StrictModel):
    """One reproducible data point underpinning a finding.

    Auto-grader replays `(dataset, table, filters, aggregation)` against
    the source CSV and compares `value` / `row_count`. Mismatch scores
    that finding zero. So every field has to be exactly as it would
    appear in a fresh pandas run — verbatim column names, English ops.
    """

    dataset: str = Field(..., description="Directory name under data/public_datasets/.")
    table: str = Field(..., description="CSV/XLSX filename inside the dataset.")
    columns: list[str] = Field(
        ...,
        description=(
            "Verbatim column names from the file header — spaces, parens, "
            "mixed languages preserved."
        ),
    )
    filters: str = Field(
        "",
        description=(
            "SQL-WHERE-style or pandas-style predicate. Reproducible: "
            "`Age >= 55` not `年龄≥55`. Empty when no filter applied."
        ),
    )
    aggregation: str = Field(
        ...,
        description="Function-call form, e.g. `mean(Purchase Amount (USD))`, `count(*)`.",
    )
    value: float | int | str = Field(
        ..., description="Actual aggregation result captured from the sandbox run. Never inferred."
    )
    row_count: int | None = Field(
        default=None, description="Post-filter row count. Required for any sampled analysis."
    )
    sampling_rate: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "Fraction of the source rows actually analyzed (1.0 = full data, "
            "0.25 = 25% sample). Required by README §3.3 雷7 / §7.2 #7 whenever "
            "the system did not run on the full dataset — without it, the "
            "auto-grader compares row_count to the full source and judges "
            "the evidence as fabricated."
        ),
    )
    sampling_note: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Human-readable note explaining the sampling, e.g. "
            "'Sampled 25k of 100k rows for tractability; deterministic "
            "seed=42'. Surfaced verbatim in the HTML report. Capped at "
            "500 chars so a buggy planner can't bloat the response or "
            "the rendered report (CodeRabbit #15 round-2)."
        ),
    )


class Finding(_StrictModel):
    """One headline + supporting paragraph + one-or-more evidence rows."""

    title: str = Field(..., description="One-line headline; ≤30 Chinese chars preferred.")
    detail: str = Field(..., description="Single paragraph including the actual numbers.")
    evidence: list[Evidence] = Field(..., min_length=1)


class Chart(_StrictModel):
    """Pointer into the rendered HTML report — type label + anchor."""

    type: Literal["柱状图", "折线图", "饼图", "散点图", "热力图", "箱线图"]
    title: str
    html_anchor: str = Field(
        ...,
        description="Fragment id present in the HTML report, e.g. `#chart-age-bar`.",
    )


class AnalyzeResponse(_StrictModel):
    """The exact shape POST /v1/analyze returns.

    Refusal payloads share this shape — see `docs/refusal-policy.md`:
      - `is_refusal=true`
      - `summary` carries the canonical refusal narrative
      - `findings` / `charts` / `recommendations` are empty
    """

    id: str = Field(
        ...,
        description=(
            "Stable per-request id, format `eval_analysis_<8-hex>` or "
            "`eval_follow_<parent>_q<n>`."
        ),
    )
    report_html_url: str = Field(
        ...,
        description="Absolute URL to the rendered HTML report (PR #5).",
    )
    summary: str = Field(
        ...,
        description="300–500 char Chinese narrative; opens with the single most important finding.",
    )
    findings: list[Finding] = Field(default_factory=list)
    charts: list[Chart] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    is_refusal: bool = False
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence; not graded but emitted for observability.",
    )
