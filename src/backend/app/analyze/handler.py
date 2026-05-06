"""Analyze handler — assemble the public `/v1/analyze` response.

Pipeline:

  1. Profile the uploaded table (no LLM).
  2. Run a cheap refusal check against the profile.
  3. Ask the planner for a typed `Plan` over the file.
  4. Execute the plan in the spreadsheet sandbox.
  5. Build `Evidence` rows from the executed plan.
  6. Ask the LLM for a `summary / title / detail / recommendations`
     "finalisation" pass given the executed answer.
  7. Assemble an `AnalyzeResponse` and return.

The handler is deliberately the *only* module that imports both
`app.analyze.*` and `app.spreadsheet.*`. Everything below it (profiler,
evidence) is independent and unit-testable; everything above it (the
HTTP route) only sees `AnalyzeResponse`.

The LLM is injected as a `ChatClient` so tests can stub it deterministically.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from app.analyze.evidence import EvidenceContext, build_evidence
from app.analyze.profiler import (
    HIGH_CARDINALITY_THRESHOLD,
    ProfilerError,
    TableProfile,
    profile_table,
)
from app.analyze.schema import AnalyzeResponse, Evidence, Finding
from app.analyze.stages import record as _stage
from app.analyze.stages import record_ops as _stage_ops
from app.report import REPORT_STORE, render_report
from app.spreadsheet.executor import (
    ExecutionReport,
    OpExecutionError,
    PlanValidationError,
    execute,
)
from app.spreadsheet.llm import ChatClient, LLMError
from app.spreadsheet.planner import PlannerError, PlanRequest, make_plan
from app.spreadsheet.schema import Plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configurable knobs (env-driven so the handler stays library-callable)
# ---------------------------------------------------------------------------


def _public_base_url() -> str:
    """The absolute origin for `report_html_url`. Defaults to localhost
    so dev runs without `.env` still produce a valid (if local) URL."""

    return os.environ.get("APP_PUBLIC_URL", "http://localhost:8000").rstrip("/")


# Plain Chinese refusal narrative when the question can't be answered
# from the available columns. Wording matches `docs/refusal-policy.md`.
_REFUSAL_CONFIDENCE = 1.0
_REFUSAL_TEMPLATE = (
    "数据集中不包含「{column}」字段，无法基于现有字段对该维度进行分析。"
    "建议补充该字段后重试，或换一个可基于现有列回答的问题。"
)


# Trap-question keywords that map to columns we *expect* to be missing.
# This is intentionally a small, hand-curated list — PR #6 promotes it
# into a real refusal classifier; here we just want one obvious trap to
# surface so the canonical refusal phrasing is exercised end-to-end.
_TRAP_KEYWORDS: dict[str, str] = {
    "race": "种族",
    "ethnicity": "种族",
    "种族": "种族",
    "民族": "种族",
}


# ---------------------------------------------------------------------------
# Inputs / errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyzeRequest:
    """Everything the handler needs once the upload is on disk.

    Optional fields:
      - `prelude`: a system-prompt prefix the planner should see *before*
        its canonical instructions. The follow-up route fills this in
        with `app.session.prompt.render_followup_system_prompt` so the
        LLM gets the parent's findings, cohorts, and prior answer. A
        first-turn analyze leaves it `None` and the planner is unchanged.
      - `request_id`: caller-supplied id. Follow-ups need
        `eval_follow_<parent>_q<n>` per contract §1; the default
        generates a fresh `eval_analysis_<32-hex>` for first turns.
      - `is_followup`: treats refusal-detection differently — follow-ups
        of refused parents always refuse without re-running the trap
        keyword check, since the prelude already encodes that.
    """

    workspace: Path
    filename: str  # already-sanitised
    dataset: str  # display name for evidence; defaults to filename stem
    question: str
    prelude: str | None = None
    request_id: str | None = None
    is_followup: bool = False


class AnalyzeFailure(Exception):
    """Wraps a downstream failure with a stable HTTP-status hint.

    The route layer reads `.status_code` and emits a JSON error. We
    don't return `AnalyzeResponse(is_refusal=True)` for engine failures
    because refusal has a *semantic* meaning ("we could read the data
    but chose not to answer") that a 502/422 doesn't share.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def handle_analyze(
    request: AnalyzeRequest, *, chat_client: ChatClient
) -> AnalyzeResponse:
    """Run the full pipeline and return a contract-shape response."""

    request_id = request.request_id or _new_request_id()
    report_url = f"{_public_base_url()}/reports/{request_id}.html"

    # 1. Profile
    try:
        profile = profile_table(request.workspace / request.filename)
    except ProfilerError as exc:
        raise AnalyzeFailure(str(exc), status_code=422) from exc
    _stage("profile")

    # 2. Refusal heuristic — follow-ups of refused parents skip this and
    #    use the route-level refusal carry-through instead, since the
    #    prelude already commits to the canonical refusal narrative.
    if not request.is_followup:
        refusal_column = _detect_refusal(request.question, profile)
        if refusal_column is not None:
            return _refusal_response(
                request_id=request_id,
                report_url=report_url,
                refusal_column=refusal_column,
            )

    # 3. Plan
    try:
        preview = _preview_for_planner(request.workspace / request.filename)
    except AnalyzeFailure:
        raise
    except (
        ValueError,
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
        # Missing openpyxl/xlrd at runtime → ImportError; permission /
        # disk problems → OSError. Both should map to a clean 422 rather
        # than leaking out as a 500 from the deeper pandas stack.
        ImportError,
        OSError,
    ) as exc:
        logger.warning("preview parse failed for %s: %s", request.filename, exc)
        raise AnalyzeFailure(
            "uploaded file could not be parsed; check format and encoding",
            status_code=422,
        ) from exc
    plan_req = PlanRequest(
        question=request.question,
        table_preview=preview,
        workspace_filename=request.filename,
        prelude=request.prelude,
    )
    _stage("preview_plan_req")
    try:
        plan = await make_plan(chat_client, plan_req)
    except PlannerError as exc:
        logger.warning("planner rejected request: %s", exc)
        raise AnalyzeFailure("planner failed to produce a valid plan", status_code=502) from exc
    except LLMError as exc:
        logger.warning("LLM call failed during planning: %s", exc)
        raise AnalyzeFailure("LLM gateway error", status_code=502) from exc
    _stage("plan_llm")

    # 4. Execute
    try:
        report = execute(plan, request.workspace)
    except PlanValidationError as exc:
        logger.info("plan validation failed: %s", exc)
        raise AnalyzeFailure("generated plan failed validation", status_code=422) from exc
    except OpExecutionError as exc:
        logger.warning(
            "op execution failed at #%d (%s): %s", exc.op_index, exc.op.kind, exc.cause
        )
        # `op_index` is 0-based internally; verses are 1-based for users.
        raise AnalyzeFailure(
            f"op execution failed at step {exc.op_index + 1} ({exc.op.kind})",
            status_code=422,
        ) from exc
    _stage("execute")
    # Surface per-op timings alongside the umbrella `execute` stage so the
    # eval renderer can show "which op in a complex plan was slow". Each
    # entry mirrors the op's `kind`/`out`/`ms` (already wall-clocked inside
    # the executor) — purely diagnostic, doesn't affect total_s.
    _stage_ops(
        [
            {"kind": r.kind, "out": r.out, "ms": r.ms}
            for r in report.op_results
        ]
    )

    # 5. Evidence
    evidence_rows = build_evidence(
        plan,
        report.answer,
        report.op_results,
        EvidenceContext(dataset=request.dataset, table=request.filename),
    )
    _stage("evidence")

    # 6. Finalise (LLM-authored Chinese narrative)
    try:
        narrative = await _finalize(chat_client, request.question, plan, report)
    except LLMError as exc:
        logger.warning("LLM call failed during finalise: %s", exc)
        raise AnalyzeFailure("LLM gateway error", status_code=502) from exc
    except FinalizeError as exc:
        logger.warning("finalise output rejected: %s", exc)
        raise AnalyzeFailure(
            "model did not produce a valid summary", status_code=502
        ) from exc
    _stage("finalize_llm")

    # 7. Assemble
    finding = Finding(
        title=narrative.title,
        detail=narrative.detail,
        evidence=evidence_rows,
    )

    # 8. Render the HTML report and stash it under `request_id` so the
    #    `GET /reports/{id}.html` route can serve it on demand. We render
    #    *after* finalisation so the report carries the LLM's narrative
    #    rather than a placeholder.
    rendered = render_report(
        report_id=request_id,
        title=narrative.title,
        summary=narrative.summary,
        findings=[finding],
        recommendations=narrative.recommendations,
        is_refusal=False,
        answer=report.answer,
    )
    REPORT_STORE.put(request_id, rendered.html)

    _stage("render")
    return AnalyzeResponse(
        id=request_id,
        report_html_url=report_url,
        summary=narrative.summary,
        findings=[finding],
        charts=rendered.charts,
        recommendations=narrative.recommendations,
        is_refusal=False,
        confidence=narrative.confidence,
    )


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


def _detect_refusal(question: str, profile: TableProfile) -> str | None:
    """Return the missing-but-asked-about column label, or None.

    Uses whole-token matching, not raw substring `in`: "trace monthly
    sales" must NOT match the `race` trap, and a real `customer_race`
    column must satisfy availability (substring not exact equality).
    """

    # `\w` includes Chinese characters under the default `re.UNICODE`
    # flag, so 种族/民族 tokenise the same way `race` does.
    tokens = {t.lower() for t in re.findall(r"\w+", question)}
    available = [c.name.lower() for c in profile.columns]
    for keyword_term, label in _TRAP_KEYWORDS.items():
        kw = keyword_term.lower()
        if kw not in tokens:
            continue
        # The trap fires only when no available column even *contains*
        # the keyword (so `customer_race` would still let us proceed).
        if any(kw in name for name in available):
            continue
        return label
    return None


def _refusal_response(
    *, request_id: str, report_url: str, refusal_column: str
) -> AnalyzeResponse:
    summary = _REFUSAL_TEMPLATE.format(column=refusal_column)
    # Refusals still get a rendered HTML report — `docs/refusal-policy.md`
    # promises the user "what data WAS available" and the contract §5
    # requires `report_html_url` to resolve. The report is chart-less.
    rendered = render_report(
        report_id=request_id,
        title="无法基于当前数据回答",
        summary=summary,
        findings=[],
        recommendations=[],
        is_refusal=True,
        answer=None,
    )
    REPORT_STORE.put(request_id, rendered.html)
    return AnalyzeResponse(
        id=request_id,
        report_html_url=report_url,
        summary=summary,
        findings=[],
        charts=rendered.charts,  # always empty for refusals — see _select_and_build_charts
        recommendations=[],
        is_refusal=True,
        confidence=_REFUSAL_CONFIDENCE,
    )


# ---------------------------------------------------------------------------
# Preview for planner
# ---------------------------------------------------------------------------


def _preview_for_planner(path: Path, rows: int = 5) -> pd.DataFrame:
    """Tiny preview the planner sees in the user prompt.

    We re-read the file rather than re-using a slice of the profiler's
    DataFrame because the profiler intentionally returns only typed
    metadata, not the rows. Reading 5 rows costs nothing.
    """

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=rows)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, nrows=rows)
    # The profiler already filtered unsupported extensions before this
    # line is reached, so this branch is defensive only.
    raise AnalyzeFailure(
        f"unsupported file extension {suffix!r}", status_code=415
    )


# ---------------------------------------------------------------------------
# Finalise — second LLM call to produce the user-facing narrative
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Narrative:
    summary: str
    title: str
    detail: str
    recommendations: list[str]
    confidence: float


class FinalizeError(Exception):
    """Finalise step produced no valid JSON after retries."""


_FINALIZE_PROMPT = """\
你是数据分析报告撰写助手。给定用户问题与一次结构化查询的结果（已由确定性引擎计算完成），
你的任务是用中文产出符合赛题提交格式的简洁结论。不要捏造数字 —
只用结果表里实际出现的值。

请输出**严格的 JSON**，结构如下，不要包裹 markdown，不要解释：

{
  "summary": "<300-500 个汉字的中文摘要，开篇直接给出最重要的发现，包含具体数字>",
  "title": "<不超过 30 字的中文标题，可作为图表/段落标题>",
  "detail": "<一段中文，1-3 句话，引用结果表中的关键数字>",
  "recommendations": ["<一条中文行动建议>", "..."],
  "confidence": <0 到 1 之间的浮点数>
}
"""


async def _finalize(
    client: ChatClient, question: str, plan: Plan, report: ExecutionReport
) -> _Narrative:
    user = (
        f"用户问题：{question}\n\n"
        f"执行的算子序列：{[op.kind for op in plan.ops]}\n"
        f"结果（JSON）：{json.dumps(report.answer, ensure_ascii=False)}\n"
        "请直接输出 JSON。"
    )
    raw = await client.chat(
        [
            {"role": "system", "content": _FINALIZE_PROMPT},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FinalizeError(f"non-JSON output: {exc}") from exc

    try:
        # Pydantic gives us cheap field-level validation here even
        # though `_Narrative` is a dataclass — wrap it in a one-off
        # model rather than copy-pasting field guards.
        return _coerce_narrative(data)
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise FinalizeError(f"narrative shape invalid: {exc}") from exc


def _coerce_narrative(data: dict) -> _Narrative:
    """Convert the LLM's JSON dict into a typed _Narrative.

    Defaults rather than hard-fail for *missing* optional fields:
    `recommendations` is allowed empty, `confidence` defaults to 0.7
    when the model omits it. Required fields (summary/title/detail) do
    raise — they're load-bearing for the contract.
    """

    summary = str(data["summary"]).strip()
    title = str(data["title"]).strip()
    detail = str(data["detail"]).strip()
    if not summary or not title or not detail:
        raise ValueError("summary/title/detail must all be non-empty")

    recs_raw = data.get("recommendations") or []
    if not isinstance(recs_raw, list):
        raise ValueError("recommendations must be a list")
    recommendations = [str(r).strip() for r in recs_raw if str(r).strip()]

    confidence_raw = data.get("confidence", 0.7)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"confidence not a number: {confidence_raw!r}") from exc
    # Pin into [0, 1] — the schema enforces it but a friendlier early
    # clamp keeps a slightly-out-of-range LLM output from failing the
    # whole request.
    confidence = max(0.0, min(1.0, confidence))

    return _Narrative(
        summary=summary,
        title=title,
        detail=detail,
        recommendations=recommendations,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# IDs
# ---------------------------------------------------------------------------


def _new_request_id() -> str:
    """`eval_analysis_<32-hex>` — high-entropy id used as the report key.

    The contract example uses a short suffix, but `request_id` doubles as
    the URL-visible primary key for `GET /reports/{id}.html` (see
    `app.api.reports`). 32 hex chars (128 bits of entropy) is the standard
    floor for unguessable URL tokens — short ids would let an attacker
    enumerate other users' reports inside a single eval window.
    """
    return f"eval_analysis_{secrets.token_hex(16)}"


def make_followup_id(parent_id: str, turn_index: int) -> str:
    """`eval_follow_<parent-suffix>_q<n>` per contract §1.

    `parent-suffix` is the parent's hex tail (the `eval_analysis_` prefix
    is dropped) so the follow-up id is short but still uniquely traceable
    back to its parent. `turn_index` is 1-based for the q-counter — the
    parent itself is turn 0 and follow-ups start at q1.
    """

    suffix = parent_id.removeprefix("eval_analysis_") or parent_id
    # Trim further to keep the id readable in logs/URLs; 16 hex chars
    # still leaves 64 bits of entropy in the path which is plenty for
    # the eval window.
    suffix = suffix[:16]
    return f"eval_follow_{suffix}_q{turn_index}"


def build_refusal_carry_through(
    *, request_id: str, parent_summary: str
) -> AnalyzeResponse:
    """Echo a parent refusal into a follow-up response.

    The contract (`docs/refusal-policy.md` §carry-through) requires the
    follow-up summary to match the parent verbatim — there's no path from
    "we couldn't analyze this" to a different narrative within the same
    session. We re-use the parent's `summary` directly and re-render the
    chart-less refusal HTML keyed under the follow-up's id.
    """

    rendered = render_report(
        report_id=request_id,
        title="无法基于当前数据回答",
        summary=parent_summary,
        findings=[],
        recommendations=[],
        is_refusal=True,
        answer=None,
    )
    REPORT_STORE.put(request_id, rendered.html)
    return AnalyzeResponse(
        id=request_id,
        report_html_url=f"{_public_base_url()}/reports/{request_id}.html",
        summary=parent_summary,
        findings=[],
        charts=rendered.charts,
        recommendations=[],
        is_refusal=True,
        confidence=_REFUSAL_CONFIDENCE,
    )


# Re-export internal helpers for tests; production code goes via
# `handle_analyze`. Listed explicitly so a future refactor can prune
# them without touching tests blindly.
__all__ = [
    "HIGH_CARDINALITY_THRESHOLD",
    "AnalyzeFailure",
    "AnalyzeRequest",
    "Evidence",
    "Finding",
    "handle_analyze",
]
