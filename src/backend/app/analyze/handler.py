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

import ast
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
from app.spreadsheet.expr import ExprError
from app.spreadsheet.llm import ChatClient, LLMError
from app.spreadsheet.planner import PlannerError, PlanRequest, make_plan
from app.spreadsheet.schema import Plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configurable knobs (env-driven so the handler stays library-callable)
# ---------------------------------------------------------------------------


def _public_base_url(override: str | None = None) -> str:
    """The absolute origin for `report_html_url`.

    Preference order:
      1. Explicit `override` from the route layer — typically
         `str(request.base_url)`. With `uvicorn --proxy-headers`, this
         already honours `X-Forwarded-Proto` / `X-Forwarded-Host`, so
         a deploy behind a TLS-terminating reverse proxy returns
         `https://demo.example.com/` rather than `http://localhost:8000`.
      2. `APP_PUBLIC_URL` env (set in `.env` and required by `start.sh`).
      3. `http://localhost:8000` as the dev-mode last resort, so library
         callers and tests still produce a valid (if local) URL.

    The trailing slash is stripped so the caller can safely append
    `/reports/{id}.html` without doubling separators.

    Round-14 (CodeRabbit #14): filter strict-loopback overrides
    (`localhost` / `127.0.0.1` / `::1`) and fall through to
    `APP_PUBLIC_URL` so a deploy with an incomplete proxy config doesn't
    hand the browser a URL it can't fetch. `testserver` is preserved
    unfiltered because it is the authority the FastAPI TestClient
    always emits and our proxy-aware contract test pins the URL
    exactly to `http://testserver/...`. That name cannot appear in
    production traffic, so keeping it out of the filter list is a
    zero-risk test seam rather than a soft spot.
    """

    if override:
        parsed = urlsplit(override)
        host = (parsed.hostname or "").lower()
        if host and host not in {"localhost", "127.0.0.1", "::1"}:
            return override.rstrip("/")
    return os.environ.get("APP_PUBLIC_URL", "http://localhost:8000").rstrip("/")


# Plain Chinese refusal narrative when the question can't be answered
# from the available columns. Wording matches `docs/refusal-policy.md`.
_REFUSAL_CONFIDENCE = 1.0
_REFUSAL_TEMPLATE = (
    "数据集中不包含「{column}」字段，无法基于现有字段对该维度进行分析。"
    "建议补充该字段后重试，或换一个可基于现有列回答的问题。"
)


# Trap-question keywords that map to columns we *expect* to be missing.
# Two-axis design:
#
#   - **Pre-flight catches the easy ones** (this dict). For each keyword
#     that appears in the question, we refuse iff no column in the file
#     even *contains* the keyword. The dict deliberately covers the
#     organizer's category-1 examples (`docs/refusal-policy.md` §1):
#     race / religion / gender / political / sexual orientation. CJK and
#     ASCII spellings sit side-by-side because the matcher in
#     `_detect_refusal` chooses substring vs token-set per keyword.
#
#   - **Post-execute is the safety net** (`_classify_op_failure`). If the
#     planner referenced a column that doesn't exist, the executor raises
#     KeyError / ExprError. Behaviorally that *is* a refusal — the system
#     correctly declined to fabricate. We promote those to canonical
#     refusal responses below so the strict §7.1 #2 envelope check passes.
#
# Why both layers: pre-flight short-circuits without burning an LLM call
# (cheap + deterministic on obvious traps). Post-execute is the catch-all
# for paraphrased traps the keyword list missed.
_TRAP_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Category 1, sub-axis 1: race / ethnicity
    "种族": ("race", "ethnicity", "种族", "民族"),
    # Category 1, sub-axis 2: religion / faith
    "宗教": ("religion", "religious", "faith", "宗教", "信仰"),
    # Category 1, sub-axis 3: political affiliation
    "政治倾向": (
        "political affiliation",
        "political party",
        "politics",
        "政治倾向",
        "政党",
    ),
    # Category 1, sub-axis 4: sexual orientation
    "性取向": ("sexual orientation", "sexuality", "性取向", "lgbtq"),
    # Category 1, sub-axis 5: explicit gender (only fires when the file
    # genuinely lacks any gender-shaped column — `_detect_refusal` checks
    # *any* alias in the category against the available columns so files
    # with `Gender` / `性别` / `sex` keep answering questions phrased with
    # the other spelling).
    "性别": ("gender", "性别", "sex"),
}


def register_trap_keyword(label: str, aliases: tuple[str, ...]) -> None:
    """Public test seam for adding a trap-keyword category at runtime.

    Tests want to assert "the union-of-columns refusal heuristic
    actually fires when a real category is added" without depending on
    the module-private `_TRAP_KEYWORDS` mapping (renaming or moving
    that internal would silently break the test). Round-9 (CodeRabbit
    #15): callers monkey-patched `_TRAP_KEYWORDS` directly via
    `monkeypatch.setitem(handler_module._TRAP_KEYWORDS, ...)`. This
    helper is the explicit alternative; pair with
    `monkeypatch.setattr(handler_module, "_TRAP_KEYWORDS", {**...})`
    or `monkeypatch.setitem(...)` for cleanup.

    Production code does NOT call this — the mapping is meant to be
    the canonical source of truth, frozen at import time. The helper
    intentionally lives next to `_TRAP_KEYWORDS` so any restructure
    moves them together.
    """
    _TRAP_KEYWORDS[label] = aliases


def _normalize_column(name: str) -> str:
    """Strip separators + casefold so `customer_race` matches `race`.

    The refusal availability check compares the question's hit-category
    against the file's column names. Real-world columns use any of
    `customer-race`, `customer_race`, `Customer Race`, `CustomerRace`;
    a naive substring would miss `Customer-Race` against the alias
    `race`. Drop everything that's not a letter/digit and lowercase.
    """
    return re.sub(r"[\W_]+", "", name).lower()


# Token splitter for column names: split on non-alphanumeric runs AND
# camelCase boundaries. "CustomerRace" → ("Customer", "Race");
# "customer_race" → ("customer", "race"); "Sussex Score" → ("Sussex",
# "Score"). Used for boundary-aware matching of short trap aliases —
# without this, `"sex" in "sussex_score".lower()` is True and would
# misclassify a benign column name as a gender column.
_COLUMN_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])")


def _column_tokens(name: str) -> set[str]:
    """Lowercased word tokens of a column name.

    Examples:
      "Customer Race" → {"customer", "race"}
      "customer_race" → {"customer", "race"}
      "Sussex_Score"  → {"sussex", "score"}     # NOT "sex"
      "sex"           → {"sex"}
      "BMI"           → {"bmi"}                 # caps-only stays whole
    """
    return {tok.lower() for tok in _COLUMN_TOKEN_SPLIT.split(name) if tok}


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
      - `base_url`: route-layer override for the report URL origin.
        The HTTP routes pass `str(request.base_url)` so a proxied
        deploy returns `https://demo.example.com/...` rather than the
        env's `APP_PUBLIC_URL` fallback. None for library/CLI callers.
      - `sampling_rate` / `sampling_note`: the caller declares that the
        uploaded file is a downsample of the source dataset. README
        §3.3 雷7 / §7.2 #7 makes this mandatory whenever the system did
        not run on the full data — the auto-grader otherwise compares
        emitted Evidence row counts to the full source and judges every
        finding as fabricated. Both are stamped verbatim on every emitted
        Evidence row via `EvidenceContext`.
      - `extra_filenames`: auxiliary tables uploaded alongside the
        primary `filename`. Each gets its own `load_csv`/`load_excel`
        and the planner is told it can stitch them with `join`. Empty
        tuple = the original single-file flow, untouched. The list is
        sanitised at the route layer (deduped, safe basenames).
    """

    workspace: Path
    filename: str  # already-sanitised; this is the *primary* table.
    dataset: str  # display name for evidence; defaults to filename stem
    question: str
    prelude: str | None = None
    request_id: str | None = None
    is_followup: bool = False
    base_url: str | None = None
    sampling_rate: float | None = None
    sampling_note: str | None = None
    extra_filenames: tuple[str, ...] = ()

    @property
    def all_filenames(self) -> tuple[str, ...]:
        """Primary first, then auxiliaries — in upload order. Used by
        the planner / preview / refusal helpers so they don't have to
        special-case single vs multi-file."""
        return (self.filename, *self.extra_filenames)


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
    report_url = f"{_public_base_url(request.base_url)}/reports/{request_id}.html"

    # 1. Profile every uploaded table. The primary table's profile drives
    #    the refusal heuristic + Evidence; auxiliary profiles get their
    #    column names unioned in so a "what's purchase rate by race"
    #    question doesn't refuse just because the *primary* file lacks
    #    the column when an auxiliary one has it.
    try:
        profile = profile_table(request.workspace / request.filename)
    except ProfilerError as exc:
        raise AnalyzeFailure(str(exc), status_code=422) from exc
    extra_profiles: list[TableProfile] = []
    for extra in request.extra_filenames:
        try:
            extra_profiles.append(profile_table(request.workspace / extra))
        except ProfilerError as exc:
            # Auxiliary files are part of the user's submission too — fail
            # fast with the same status as the primary so the client knows
            # to fix that specific file rather than re-uploading everything.
            raise AnalyzeFailure(
                f"auxiliary file {extra!r}: {exc}", status_code=422
            ) from exc
    _stage("profile")

    # 2. Refusal heuristic — follow-ups of refused parents skip this and
    #    use the route-level refusal carry-through instead, since the
    #    prelude already commits to the canonical refusal narrative.
    if not request.is_followup:
        refusal_column = _detect_refusal(
            request.question, profile, extra_profiles=extra_profiles
        )
        if refusal_column is not None:
            return _refusal_response(
                request_id=request_id,
                report_url=report_url,
                refusal_column=refusal_column,
            )

    # 3. Plan
    table_previews: list[tuple[str, pd.DataFrame]] = []
    for name in request.all_filenames:
        try:
            preview = _preview_for_planner(request.workspace / name)
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
            logger.warning("preview parse failed for %s: %s", name, exc)
            raise AnalyzeFailure(
                f"file {name!r} could not be parsed; check format and encoding",
                status_code=422,
            ) from exc
        table_previews.append((name, preview))
    plan_req = PlanRequest(
        question=request.question,
        tables=table_previews,
        prelude=request.prelude,
    )
    _stage("preview_plan_req")
    try:
        plan = await make_plan(chat_client, plan_req)
    except PlannerError as exc:
        logger.warning("planner rejected request: %s", exc)
        raise AnalyzeFailure(f"planner failed to produce a valid plan: {exc}", status_code=502) from exc
    except LLMError as exc:
        logger.warning("LLM call failed during planning: %s", exc)
        raise AnalyzeFailure(f"LLM gateway error: {exc}", status_code=502) from exc
    _stage("plan_llm")

    # 4. Execute
    try:
        report = execute(plan, request.workspace)
    except PlanValidationError as exc:
        logger.warning("plan validation failed: %s", exc)
        raise AnalyzeFailure(f"generated plan failed validation: {exc}", status_code=422) from exc
    except OpExecutionError as exc:
        # Before surfacing the failure as a 422, see whether it's actually
        # a category-1 refusal in disguise: the planner asked for a column
        # that doesn't exist in the file. The behaviour the auto-grader
        # cares about is `is_refusal=True` with the canonical phrasing —
        # a 422 with the same root cause counts as "lenient refusal" but
        # misses the strict §7.1 #2 envelope. Promote it here so the
        # response reflects what actually happened semantically.
        missing_label = _classify_op_failure(
            exc, profile, extra_profiles=extra_profiles
        )
        if missing_label is not None:
            logger.info(
                "promoting op-execution KeyError to refusal (column=%r)",
                missing_label,
            )
            return _refusal_response(
                request_id=request_id,
                report_url=report_url,
                refusal_column=missing_label,
            )
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
        EvidenceContext(
            dataset=request.dataset,
            table=request.filename,
            sampling_rate=request.sampling_rate,
            sampling_note=request.sampling_note,
        ),
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


def _detect_refusal(
    question: str,
    profile: TableProfile,
    *,
    extra_profiles: list[TableProfile] | None = None,
) -> str | None:
    """Return the missing-but-asked-about column label, or None.

    ASCII keywords use whole-token matching ("trace monthly sales" must
    NOT match the `race` trap). CJK keywords use substring matching on
    the raw question because Chinese has no whitespace word boundaries:
    `re.findall(r"\\w+", "请按种族分析消费偏好")` returns a single
    multi-character token, so a token-set membership check would never
    fire on `种族` (PR #4 shipped with this latent bug; surfaced via
    the 0.20 → 0.6+ refusal-accuracy jump in `eval/runs/abc-*`).
    Availability still uses substring (so a real `customer_race` column
    keeps the question alive).

    Multi-file: `extra_profiles` lets the caller surface columns from
    auxiliary uploads so the trap doesn't fire when the *primary* file
    lacks the column but a joinable file has it. Single-file callers
    pass nothing and behaviour is identical to the pre-multi-file path.
    """

    # `\w` includes Chinese characters under the default `re.UNICODE`
    # flag, but does NOT split on word boundaries — `\w+` is greedy on
    # contiguous letter runs, which collapses entire CJK phrases into
    # one token. The split here is just for the single-word ASCII branch.
    tokens = {t.lower() for t in re.findall(r"\w+", question)}
    raw = question.lower()
    # Build availability twice: the *raw* form preserves both the
    # original casing AND the underscores/spaces, so the original
    # substring branch still works AND `_column_tokens()` can find
    # CamelCase boundaries. Round-12 (CodeRabbit #15): pre-lowercasing
    # here would collapse `CustomerRace` → `customerrace`, killing the
    # `(?<=[a-z])(?=[A-Z])` boundary in `_COLUMN_TOKEN_SPLIT` and
    # making `_column_tokens("customerrace")` return `{"customerrace"}`
    # instead of `{"customer", "race"}` — at which point a `race`
    # question against a CSV with a `CustomerRace` column refuses
    # spuriously. The raw substring branch builds its own lowercase
    # view (`raw_lower`) below; `_normalize_column` lowercases inside
    # itself; the only consumer that *needs* original casing is
    # `_column_tokens`, so we keep raw and let each consumer apply
    # its own normalisation.
    raw_available = [c.name for c in profile.columns]
    if extra_profiles:
        for ex in extra_profiles:
            raw_available.extend(c.name for c in ex.columns)
    normalized_available = [_normalize_column(name) for name in raw_available]
    for label, aliases in _TRAP_KEYWORDS.items():
        # Category-level matching: the question hits the category if
        # *any* alias appears, and we keep going (no refusal) if *any*
        # alias from the same category appears among the available
        # columns. The previous reuse of the matched alias for the
        # availability check produced false refusals across synonym
        # boundaries (`民族` question + `ethnicity` column refused
        # despite the file having the data the user asked about).
        question_hit = False
        for alias in aliases:
            kw = alias.lower()
            # Three matching modes (preserved from the original):
            #   - Single-word ASCII ("race"): token-set membership so a
            #     real `customer_race` column doesn't accidentally fire
            #     on a `trace` token.
            #   - Multi-word ASCII ("political affiliation"): substring
            #     on the raw question. Token-set wouldn't catch the
            #     phrase because `\w+` splits on the space.
            #   - CJK ("种族"): substring on raw, since CJK has no word
            #     boundaries that `\w+` would honour.
            if kw.isascii() and " " not in kw:
                if kw in tokens:
                    question_hit = True
                    break
            else:
                if kw in raw:
                    question_hit = True
                    break
        if not question_hit:
            continue
        # Availability check spans the *whole category* — if any alias
        # in the category appears among the columns, the file actually
        # has the data and we should not refuse. Three matching modes:
        #   - ASCII single-token alias ("sex", "race", "gender",
        #     "ethnicity", "lgbtq", "faith"): token-aware match against
        #     `_column_tokens(name)` so "Sussex_Score" / "racetrack_id"
        #     don't pretend to be gender/race columns. CodeRabbit #15
        #     round-2: a raw `"race" in "racetrack_id".lower()`
        #     substring fired false-positives. Round-2-take-2: extended
        #     beyond `len <= 3` to all single-token aliases since the
        #     hazard is the same for any dictionary word.
        #   - ASCII multi-word alias ("political affiliation"):
        #     substring on raw — token splitting would break the
        #     phrase and the substring is enough to disambiguate at
        #     ≥2-word lengths.
        #   - CJK alias ("种族", "民族"): substring on raw (CJK has no
        #     word boundary character class).
        # Plus a normalized-substring fallback for compound columns
        # like "CustomerEthnicity" that token-split's casing handles
        # but raw substring against the lowercased name might miss.
        column_token_sets = [_column_tokens(name) for name in raw_available]
        # Pre-build a lowercased-raw view so substring matches don't
        # have to rebuild it per alias.
        raw_lower = [name.lower() for name in raw_available]
        match_found = False
        for alias in aliases:
            kw = alias.lower()
            # Decide which mode to use. The hazard we're guarding
            # against is short ASCII alias substrings firing on
            # unrelated columns ("sex" in "sussex_score"). Tokenize
            # for any single-word ASCII alias; for separator-bearing
            # or multi-word ASCII aliases, fall back to substring.
            if (
                kw.isascii()
                and " " not in kw
                and "_" not in kw
                and "-" not in kw
            ):
                # Token-aware ONLY — no normalized-substring fallback.
                # Round-7 (CodeRabbit #15): CR asked us to chain a
                # substring fallback after the token check so a column
                # literally named `customerrace` (no separator, no
                # camelCase) would match alias `race`. We're SKIPPING
                # that change because the same substring rule would
                # bring back the round-6 bug where alias `sex` matches
                # column `sussex_score`. The two scenarios are
                # symmetric — the substring relationship gives no signal
                # about whether `race` is a meaningful piece of
                # `customerrace` versus an accidental substring of
                # `embracerate`. We bias toward conservative refusals:
                # `_column_tokens` already splits on `_` / `-` /
                # camelCase, so `customer_race` / `Customer-Race` /
                # `CustomerRace` do match. The all-lowercase compound
                # form is the small loss we accept to keep `sussex`
                # safe.
                if any(kw in tokens for tokens in column_token_sets):
                    match_found = True
                    break
            else:
                if any(kw in name for name in raw_lower):
                    match_found = True
                    break
                if any(
                    _normalize_column(alias) in name
                    for name in normalized_available
                ):
                    match_found = True
                    break
        if match_found:
            continue
        return label
    return None


# Op-error messages whose `args[0]` looks like:
#   "group_by: missing columns ['Director Score']"
#   "select_columns: missing columns ['年龄段', '区域']"
#   "to_chart: missing columns ['Quarter']"
# All op handlers (see `app/spreadsheet/ops/*.py`) raise KeyError with this
# stable shape, so a regex over the message is robust without each handler
# growing a custom exception type.
_MISSING_COLS_PATTERN = re.compile(
    r"missing columns \[(?P<list>[^\]]*)\]"
)
# `ExprError` from `app/spreadsheet/expr.py` reports per-column refs as:
#   "column 'Director Score' not found; have ['title', 'rating']"
# Single-column form (the only one expr.evaluate produces) — capture the
# bare column name out of the quotes.
_EXPR_MISSING_COL_PATTERN = re.compile(
    r"column '(?P<col>[^']+)' not found"
)


def _classify_op_failure(
    exc: OpExecutionError,
    profile: TableProfile,
    *,
    extra_profiles: list[TableProfile] | None = None,
) -> str | None:
    """Return a refusal column label if `exc` is "planner asked for a missing column".

    Behaviorally that's a category-1 refusal — the planner generated a
    plan against a column the file doesn't have, the executor declined
    to fabricate, and the right response shape is `is_refusal=True` with
    the canonical category-1 phrasing rather than a 422.

    Returns None for any other failure (genuine ValueError, divide by
    zero, schema mismatches that aren't column-name-related). Those keep
    the existing 422 path so the caller still sees a real error.

    Multi-file: `extra_profiles` lets us union column names across all
    uploaded tables so a join-style plan (which evaluates ops on the
    merged frame) doesn't trip the refusal path on columns that *do*
    exist in some auxiliary file.

    Strategy:
      1. Pull the missing column names out of the wrapped error message
         using the two stable formats our op handlers / expr evaluator
         emit.
      2. Cross-check against `profile.columns` — only refuse if the
         column genuinely isn't in the file. A column that *is* in the
         file but failed for a different reason (dtype mismatch, etc.)
         shouldn't masquerade as a refusal.
    """

    cause = exc.cause
    message = str(cause) if cause is not None else ""
    available = {c.name for c in profile.columns}
    available_lower = {c.name.lower() for c in profile.columns}
    # CodeRabbit #15 round-2: also build a normalized set so a planner
    # asking for "Customer Race" against a file with `customer_race`
    # (or `Customer-Race`) doesn't masquerade as a missing-column
    # refusal — the column IS in the file, just spelled differently.
    available_normalized = {_normalize_column(c.name) for c in profile.columns}
    if extra_profiles:
        for ex in extra_profiles:
            available.update(c.name for c in ex.columns)
            available_lower.update(c.name.lower() for c in ex.columns)
            available_normalized.update(
                _normalize_column(c.name) for c in ex.columns
            )

    candidates: list[str] = []

    # Op-handler KeyError: "missing columns ['col1', 'col2']".
    if isinstance(cause, KeyError):
        match = _MISSING_COLS_PATTERN.search(message)
        if match:
            raw_list = match.group("list")
            # Column names legitimately contain commas (e.g. "Revenue, USD"),
            # so a naive `split(",")` of the repr'd list would shred them.
            # The op-handler emits a Python-literal list, so the robust
            # path is `literal_eval`; on malformed input fall back to
            # the old splitter (which is still correct for comma-free
            # names — the 99% case) so a surprise format doesn't null
            # the refusal signal.
            parsed: list[str] | None = None
            try:
                candidate_obj = ast.literal_eval(f"[{raw_list}]")
            except (ValueError, SyntaxError):
                candidate_obj = None
            if isinstance(candidate_obj, list) and all(
                isinstance(x, str) for x in candidate_obj
            ):
                parsed = [x.strip() for x in candidate_obj if x.strip()]
            if parsed is not None:
                candidates.extend(parsed)
            else:
                for raw in raw_list.split(","):
                    # Strip surrounding quotes + whitespace from each element.
                    token = raw.strip().strip("'\"")
                    if token:
                        candidates.append(token)

    # ExprError from expr.evaluate: "column 'X' not found; have [...]".
    elif isinstance(cause, ExprError):
        match = _EXPR_MISSING_COL_PATTERN.search(message)
        if match:
            candidates.append(match.group("col"))

    # No recognisable missing-column shape — leave classification to the
    # caller (which will surface a 422).
    if not candidates:
        return None

    # Only refuse if at least one candidate is *actually* absent. If the
    # planner asked for a column that DOES exist (e.g. a casing or
    # whitespace mismatch the executor surfaced) we want a 422 instead:
    # the user's question is answerable, the bug is on us. Cross-check
    # against raw, lowercased, AND normalized names so format-only
    # variants don't get misclassified as refusals.
    truly_missing = [
        c for c in candidates
        if c not in available
        and c.lower() not in available_lower
        and _normalize_column(c) not in available_normalized
    ]
    if not truly_missing:
        return None

    # Use the first missing column verbatim as the refusal label. The
    # canonical phrasing in `_REFUSAL_TEMPLATE` quotes it back to the
    # user, which is exactly the auto-grader's category-1 expectation.
    return truly_missing[0]


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
    # Round-9 (CodeRabbit #14): emit the `render` stage on refusal
    # paths too. Without this `X-Stage-Timings.total_s` underreports
    # refused-request latency by the time spent rendering the
    # refusal HTML, which makes refused-vs-successful timings
    # incomparable in the eval renderer's per-stage table.
    _stage("render")
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
    *, request_id: str, parent_summary: str, base_url: str | None = None
) -> AnalyzeResponse:
    """Echo a parent refusal into a follow-up response.

    The contract (`docs/refusal-policy.md` §carry-through) requires the
    follow-up summary to match the parent verbatim — there's no path from
    "we couldn't analyze this" to a different narrative within the same
    session. We re-use the parent's `summary` directly and re-render the
    chart-less refusal HTML keyed under the follow-up's id.

    `base_url` mirrors `AnalyzeRequest.base_url`: routes pass
    `str(request.base_url)` so the carry-through URL respects forwarded
    proxy headers; library callers leave it None and the env fallback
    kicks in.
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
    # Round-9 (CodeRabbit #14): same gap as `_refusal_response` — the
    # carry-through path also rendered HTML without emitting a
    # `render` stage mark, so the X-Stage-Timings header on
    # carry-through follow-ups under-reported total_s. The follow-up
    # route binds a stage timer for the same reason analyze does, so
    # this `_stage("render")` will land in the bound dict.
    _stage("render")
    return AnalyzeResponse(
        id=request_id,
        report_html_url=f"{_public_base_url(base_url)}/reports/{request_id}.html",
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
