"""End-to-end evaluation runner for TableTalker.

Usage:
    python eval/run.py [--backend http://localhost:8000] [--out eval/runs/<ts>]

For each case in `eval/cases.yaml`:
  1. POST the dataset + main question → /v1/analyze.
  2. POST a follow-up if defined → /v1/follow-up.
  3. POST a trap question if defined → /v1/analyze (separately scored).

Per-case latency, status, refusal correctness, evidence completeness,
chart-type counts, and summary length are recorded into a per-run
JSON dump and rolled up into the metrics table that back-fills
`自测报告/latest_evaluation_metrics.md`.

Determinism note: the LLM adds non-determinism we can't remove without
a stub. The metrics we publish are therefore "single-run measurements
on commit X". Re-running may shift LLM-derived numbers ±a few percent.
The deterministic numbers (profiling, plan execution, refusal
keyword-match) stay byte-stable across runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "datasets"
CASES_FILE = ROOT / "cases.yaml"
RUNS_DIR = ROOT / "runs"

logger = logging.getLogger("eval.run")

# Per-call timeout. The first analyze on a fresh dataset can hit ~60 s
# because both planner and finalize make LLM round-trips; tail follow-ups
# are usually faster but still LLM-bound.
HTTP_TIMEOUT_S = 180.0


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    label: str
    status_code: int
    latency_s: float
    body: dict | None = None
    error: str | None = None
    # Per-stage durations from the backend's `X-Stage-Timings` header,
    # if present. Missing or malformed → None (renderer treats as
    # "not measured"). See `app.analyze.stages` on the server.
    stage_timings: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and self.body is not None


@dataclass
class CaseResult:
    case_id: str
    main: TurnResult
    followup: TurnResult | None = None
    trap: TurnResult | None = None
    trap_expected_refusal: bool | None = None
    # Optional manifest metadata: when the source dataset was
    # sub-sampled before being committed to `eval/datasets-official/`,
    # `sampling_rate` (e.g. 0.25 for a 25% sample) is declared in
    # `cases-official.yaml`. The renderer surfaces this in §6 (evidence
    # disclosure) so the auto-grader can verify the sample-rate claim
    # in the run summary matches what the case used. None = full dataset.
    sampling_rate: float | None = None


@dataclass
class RunSummary:
    backend: str
    started_at: str
    completed_at: str
    cases: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _parse_stage_timings(response: httpx.Response) -> dict | None:
    """Decode the `X-Stage-Timings` header into a JSON dict.

    Backends without the header (e.g. an older deploy) return None,
    which the renderer reads as "not measured for this turn" rather
    than zero. Malformed JSON is logged-and-ignored — a bad header
    shouldn't fail an otherwise-good run, but silent swallowing hid
    a real planner regression once (CodeRabbit #14 round-6). The
    warning surfaces the offending payload so the next run can be
    diagnosed without re-instrumenting.
    """
    raw = response.headers.get("X-Stage-Timings")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        logger.warning(
            "X-Stage-Timings parse failed for %s: %s (raw=%r)",
            getattr(response, "url", "<unknown>"),
            exc,
            raw[:512],
        )
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "X-Stage-Timings is not a dict for %s: type=%s (raw=%r)",
            getattr(response, "url", "<unknown>"),
            type(parsed).__name__,
            raw[:512],
        )
        return None
    # Round-9 (CodeRabbit #14): tighten the seam earlier — reject any
    # payload carrying NaN/±inf at parse time so downstream callers
    # (`_stage_percentiles`, `_op_percentiles`, the JSON dump) can't
    # re-introduce them. `json.loads` accepts non-standard tokens by
    # default, so a misbehaving planner could otherwise leak Infinity
    # into the cached run JSON.
    if not _is_jsonable_finite(parsed):
        logger.warning(
            "X-Stage-Timings carries non-finite numeric values for %s "
            "(raw=%r)",
            getattr(response, "url", "<unknown>"),
            raw[:512],
        )
        return None
    return parsed


def _is_jsonable_finite(value: object) -> bool:
    """Walk a JSON-decoded payload and return False on any non-finite
    numeric leaf (NaN, +inf, -inf) **or** any boolean leaf in a numeric
    position.

    Booleans are *rejected* rather than skipped. Round-11 (CodeRabbit
    #14): a malformed header like
    ``{"stages":{"execute":true},"ops":[{"kind":"load_csv","ms":false}]}``
    would otherwise pass the finite-only filter — `bool` is a subclass
    of `int` and `True == 1` arithmetically. Treating those as valid
    timing values silently turns a typo into "1ms" / "0ms" entries in
    downstream stats. Failing the validation makes the malformed payload
    fall back to the `None` branch in `_parse_stage_timings`, same as
    NaN/Infinity.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_is_jsonable_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_is_jsonable_finite(v) for v in value)
    # str / None / other non-numeric → trivially finite.
    return True


async def _post_analyze(
    client: httpx.AsyncClient,
    dataset_path: Path,
    question: str,
    *,
    sampling_rate: float | None = None,
) -> TurnResult:
    started = time.monotonic()
    try:
        with dataset_path.open("rb") as f:
            # `sampling_rate` (CR #17 round-15 Major): when the manifest
            # declares the dataset was sub-sampled, forward it as a form
            # field so the backend stamps Evidence rows with the same
            # disclosure. Without this, recording sampling_rate on the
            # local CaseResult is a half-measure — the per-row Evidence
            # `sampling_rate` stays None and the auto-grader judges every
            # finding as based on a full-population claim, breaking the
            # 04_telecom_churn case (and any future sub-sampled dataset).
            data: dict[str, str] = {"question": question}
            if sampling_rate is not None:
                data["sampling_rate"] = str(sampling_rate)
            response = await client.post(
                "/v1/analyze",
                files={"file": (dataset_path.name, f, "text/csv")},
                data=data,
            )
    except httpx.HTTPError as exc:
        return TurnResult(
            label="analyze",
            status_code=0,
            latency_s=time.monotonic() - started,
            error=str(exc),
        )
    latency = time.monotonic() - started
    try:
        body = response.json()
    except ValueError:
        body = None
    return TurnResult(
        label="analyze",
        status_code=response.status_code,
        latency_s=latency,
        body=body,
        error=None
        if response.status_code == 200
        else (response.text[:500] if body is None else None),
        stage_timings=_parse_stage_timings(response)
        if response.status_code == 200
        else None,
    )


async def _post_followup(
    client: httpx.AsyncClient, parent_id: str, question: str
) -> TurnResult:
    started = time.monotonic()
    try:
        response = await client.post(
            "/v1/follow-up", json={"parent_id": parent_id, "question": question}
        )
    except httpx.HTTPError as exc:
        return TurnResult(
            label="follow_up",
            status_code=0,
            latency_s=time.monotonic() - started,
            error=str(exc),
        )
    latency = time.monotonic() - started
    try:
        body = response.json()
    except ValueError:
        body = None
    return TurnResult(
        label="follow_up",
        status_code=response.status_code,
        latency_s=latency,
        body=body,
        error=None
        if response.status_code == 200
        else (response.text[:500] if body is None else None),
        stage_timings=_parse_stage_timings(response)
        if response.status_code == 200
        else None,
    )


# ---------------------------------------------------------------------------
# Per-case driver
# ---------------------------------------------------------------------------


# Round-7 (CodeRabbit #17): dataset filenames are derived from
# `case["id"]`, which comes from a user-supplied YAML file. Restrict the
# token to the same alphabet `eval/build_datasets.py` writes
# (alphanumerics, underscore, hyphen) so a hostile cases.yaml cannot
# escape `data_dir/` via "../" or absolute paths.
_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _resolve_dataset_path(case_id: str, data_dir: Path) -> Path:
    """Return `data_dir/<case_id>.csv`, refusing path-traversal IDs.

    Two layers of defence:
    1. Whitelist regex on the raw ID — rejects "/", "\\", "..", and any
       non-portable character before it ever touches the filesystem.
    2. `commonpath` check on the resolved absolute path — catches
       symlink shenanigans and case-folding edge cases on macOS/Windows.
    """
    if not isinstance(case_id, str) or not _CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            f"case id must match {_CASE_ID_PATTERN.pattern!r} "
            f"(no path separators, no '..'), got: {case_id!r}"
        )
    candidate = (data_dir / f"{case_id}.csv").resolve()
    base = data_dir.resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"resolved dataset path {candidate} escapes data_dir {base}"
        ) from exc
    return candidate


async def run_case(
    client: httpx.AsyncClient, case: dict, *, data_dir: Path
) -> CaseResult:
    case_id = case["id"]
    dataset_path = _resolve_dataset_path(case_id, data_dir)
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset missing: {dataset_path}")

    # Resolve once so main + trap forward the same sampling disclosure
    # to the backend; without this the trap turn would be evaluated
    # against full-population assumptions even when the case sub-sampled.
    sampling_rate = case.get("sampling_rate")

    print(f"  · {case_id} · main", flush=True)
    main = await _post_analyze(
        client, dataset_path, case["question"], sampling_rate=sampling_rate
    )

    followup: TurnResult | None = None
    if main.ok and "followup" in case:
        parent_id = main.body["id"]  # type: ignore[index]
        print(f"  · {case_id} · follow-up", flush=True)
        followup = await _post_followup(client, parent_id, case["followup"])

    trap: TurnResult | None = None
    expected_refusal: bool | None = None
    if "trap" in case:
        # Reject non-bool YAML values (e.g. the literal string "false",
        # which `bool(...)` would silently coerce to True). The whole
        # trap-scoring path lives or dies on this flag — better to
        # crash the run than score the wrong direction.
        raw = case["trap"].get("expected_refusal")
        if not isinstance(raw, bool):
            raise ValueError(
                f"{case_id}.trap.expected_refusal must be a boolean, got: {raw!r}"
            )
        expected_refusal = raw
        print(f"  · {case_id} · trap (expect_refuse={expected_refusal})", flush=True)
        trap = await _post_analyze(
            client,
            dataset_path,
            case["trap"]["question"],
            sampling_rate=sampling_rate,
        )

    return CaseResult(
        case_id=case_id,
        main=main,
        followup=followup,
        trap=trap,
        trap_expected_refusal=expected_refusal,
        sampling_rate=sampling_rate,
    )


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_metrics(results: Iterable[CaseResult]) -> dict:
    results = list(results)
    main_oks = [r for r in results if r.main.ok]
    main_total = len(results)

    plan_success_rate = len(main_oks) / main_total if main_total else 0.0

    # Latency stats are conditioned on a successful 200 main turn —
    # otherwise a 180 s read-timeout would always become the p95
    # regardless of how the underlying pipeline performs. Failed
    # mains are still visible in `main_success_rate`.
    main_latencies = sorted(r.main.latency_s for r in main_oks)
    p50 = main_latencies[len(main_latencies) // 2] if main_latencies else 0.0
    # `math.ceil(N * 0.95)` gives the 95th-percentile rank (1-based) per
    # the nearest-rank definition; clamp to N-1 because Python is 0-based
    # and the ceil at N == 20 would otherwise overshoot by one.
    if main_latencies:
        idx = min(math.ceil(len(main_latencies) * 0.95) - 1, len(main_latencies) - 1)
        p95 = main_latencies[max(idx, 0)]
    else:
        p95 = 0.0

    findings_total = 0
    findings_with_evidence = 0
    chart_types: Counter[str] = Counter()
    summary_lens: list[int] = []
    for r in main_oks:
        body = r.main.body or {}
        for f in body.get("findings", []):
            findings_total += 1
            if f.get("evidence"):
                findings_with_evidence += 1
        for c in body.get("charts", []):
            t = c.get("type")
            if isinstance(t, str):
                chart_types[t] += 1
        summary = body.get("summary")
        if isinstance(summary, str):
            summary_lens.append(len(summary))

    evidence_completeness = (
        findings_with_evidence / findings_total if findings_total else 0.0
    )
    distinct_chart_types = len(chart_types)
    avg_summary_len = sum(summary_lens) / len(summary_lens) if summary_lens else 0

    # Two parallel scores per trap:
    #   - `refusal_strict_*`:  the canonical-format definition — only a
    #     200 response with `is_refusal: True` counts. This is what the
    #     official §7.1 #2 ("拒答陷阱题时严格使用统一格式") requires for
    #     full scoring credit.
    #   - `refusal_correct_*` (lenient):  ALSO counts a 4xx response as
    #     effective refusal. Rationale: when the LLM's plan references a
    #     non-existent column, the executor returns 422 ("step 2: missing
    #     column NOT_A_COL"). The system did NOT fabricate analysis — it
    #     stopped honestly with a typed error. That's behaviorally a
    #     refusal even if the format isn't canonical. We surface both so
    #     the renderer can show "5/5 lenient, 4/5 strict" and the gap is
    #     exactly the work item to fix the canonical refusal phrasing
    #     for plan-failed-on-trap paths (P0-6 / H7).
    #   Transport failures (status 0) and 5xx are scored as None — those
    #   are infrastructure failures, not refusals, and shouldn't inflate
    #   either score.
    trap_correct = 0
    trap_strict_correct = 0
    trap_total = 0
    trap_strict_total = 0
    false_refuse_count = 0
    false_refuse_total = 0
    for r in results:
        if r.trap is not None and r.trap_expected_refusal is not None:
            actual_strict: bool | None = None
            actual_lenient: bool | None = None
            if r.trap.ok:
                v = (r.trap.body or {}).get("is_refusal")
                if isinstance(v, bool):
                    actual_strict = v
                    actual_lenient = v
            elif 400 <= r.trap.status_code < 500:
                # 4xx on a trap = "system refused to make stuff up" in
                # behaviour, even though the response body isn't the
                # canonical refusal envelope. Lenient-only refusal.
                actual_strict = None
                actual_lenient = True
            # status_code == 0 (transport) or 5xx → both stay None.
            # Only count scored traps in the denominator. Transport
            # failures and 5xx leave both `actual_*` as None, which
            # means we couldn't evaluate whether the system refused —
            # counting them as incorrect would punish infrastructure
            # flakes as "false positives / false negatives" and skew
            # the headline number downward. Use `actual_lenient` as
            # the scoring predicate because the lenient view is a
            # strict superset of the strict view — if lenient is None,
            # strict is also None, so neither score has a signal.
            if actual_lenient is not None:
                trap_total += 1
                if actual_lenient == r.trap_expected_refusal:
                    trap_correct += 1
            # The strict denominator must be tracked separately. A 4xx
            # trap is `actual_lenient=True`/`actual_strict=None` —
            # behaviourally a refusal but not a canonical-format one.
            # Counting it in `trap_total` and dividing strict-correct
            # by `trap_total` would treat it as a strict miss, dragging
            # `refusal_strict_accuracy` down for runs where the only
            # "non-strict" cases are infrastructure-level refusals. The
            # official §7.1 #2 metric measures *canonical-format usage
            # among scoreable cases*, so the strict denominator should
            # only include cases where strict is actually scored.
            if actual_strict is not None:
                trap_strict_total += 1
                if actual_strict == r.trap_expected_refusal:
                    trap_strict_correct += 1
            # `expected_refusal: false` traps are part of the false-
            # refuse measurement: a refusal there is precisely what
            # the metric is designed to catch. Skipping them would
            # inflate false-refuse correctness. We use the strict view
            # here — a 4xx isn't "the model insisted on refusing", it's
            # "the plan didn't validate", which is a different bug.
            if r.trap_expected_refusal is False and actual_strict is not None:
                false_refuse_total += 1
                if actual_strict is True:
                    false_refuse_count += 1
        if r.main.ok:
            false_refuse_total += 1
            if (r.main.body or {}).get("is_refusal") is True:
                false_refuse_count += 1

    refusal_accuracy = trap_correct / trap_total if trap_total else 0.0
    refusal_strict_accuracy = (
        trap_strict_correct / trap_strict_total if trap_strict_total else 0.0
    )
    false_refuse_rate = (
        false_refuse_count / false_refuse_total if false_refuse_total else 0.0
    )

    fu_total = sum(1 for r in results if r.followup is not None)
    fu_ok = 0
    fu_carries_session = 0
    for r in results:
        if r.followup is None:
            continue
        if r.followup.ok:
            fu_ok += 1
            fu_id = (r.followup.body or {}).get("id", "")
            parent_id = (r.main.body or {}).get("id", "")
            parent_suffix = parent_id.removeprefix("eval_analysis_")[:16]
            if fu_id.startswith(f"eval_follow_{parent_suffix}"):
                fu_carries_session += 1
    followup_success = fu_ok / fu_total if fu_total else 0.0
    session_carry = fu_carries_session / fu_total if fu_total else 0.0

    report_ok = 0
    for r in main_oks:
        body = r.main.body or {}
        url = body.get("report_html_url", "")
        rid = body.get("id", "")
        if url.endswith(f"/reports/{rid}.html") and rid.startswith("eval_"):
            report_ok += 1
    report_render_rate = report_ok / len(main_oks) if main_oks else 0.0

    # Per-stage P50/P95 across all 200-OK main turns. The backend
    # publishes these in `X-Stage-Timings`; missing turns (older deploys
    # without the header) are skipped so the percentile is over what we
    # actually measured.
    stage_p50, stage_p95, stage_n = _stage_percentiles(main_oks)

    # Per-op-kind aggregates pulled from the same header's `ops` list.
    # Useful for "in complex plans, which op is the slow one?" — for our
    # current op set the answer is always "neither, ops are < 20 ms" but
    # that's exactly what we want to confirm with measurement.
    op_p50, op_p95, op_n = _op_percentiles(main_oks)

    return {
        "datasets_total": main_total,
        "main_success_count": len(main_oks),
        "main_success_rate": plan_success_rate,
        "p50_latency_s": p50,
        "p95_latency_s": p95,
        "evidence_completeness": evidence_completeness,
        "distinct_chart_types": distinct_chart_types,
        "avg_summary_len_chars": avg_summary_len,
        "refusal_correct_accuracy": refusal_accuracy,
        # Round-14 (CodeRabbit #17): CR asked for the lenient rate key
        # to share the `refusal_correct_*` prefix with its count sibling
        # so readers don't have to memorise a second name. The old
        # `refusal_accuracy_on_traps` key is kept alongside as an alias
        # so previously-generated summary.json artifacts (and external
        # tooling that pinned the old name) keep rendering.
        "refusal_accuracy_on_traps": refusal_accuracy,
        "refusal_correct_count": trap_correct,
        "refusal_strict_accuracy": refusal_strict_accuracy,
        "refusal_strict_correct_count": trap_strict_correct,
        "trap_cases_total": trap_total,
        # Strict denominator may be smaller than lenient when 4xx traps
        # show up — see commentary in the scoring loop. Keep both so
        # the renderer can report e.g. "4/4 strict, 5/5 lenient" with
        # honest fractions on each side.
        "trap_strict_cases_total": trap_strict_total,
        "false_refuse_rate": false_refuse_rate,
        "false_refuse_count": false_refuse_count,
        "false_refuse_total": false_refuse_total,
        "followup_success_rate": followup_success,
        "session_carry_rate": session_carry,
        "report_render_rate": report_render_rate,
        # Per-stage timings (seconds). One key per stage from
        # `app.analyze.stages.STAGE_ORDER`. Renderer matches on the
        # stage name; missing stages are skipped in the table.
        "stage_p50_s": stage_p50,
        "stage_p95_s": stage_p95,
        "stage_sample_n": stage_n,
        # Per-op-kind timings (milliseconds). Aggregated across every op
        # invocation in every successful main turn — a 6-op plan
        # contributes 6 entries to whichever kinds it used.
        "op_p50_ms": op_p50,
        "op_p95_ms": op_p95,
        "op_sample_n": op_n,
    }


# Stage names mirror `app.analyze.stages.STAGE_ORDER` on the server. We
# duplicate them here rather than importing because the eval runner is a
# standalone client — keeping it import-free of the backend means it can
# run against a remote deploy without the source tree on the local box.
_STAGE_ORDER: tuple[str, ...] = (
    "profile",
    "preview_plan_req",
    "plan_llm",
    "execute",
    "evidence",
    "finalize_llm",
    "render",
)


def _stage_percentiles(
    main_oks: list[CaseResult],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Compute P50/P95 per stage across successful main turns.

    Returns three parallel dicts keyed by stage name:
      - `stage_p50_s`: median duration in seconds
      - `stage_p95_s`: p95 duration (nearest-rank, ceil-based)
      - `stage_sample_n`: how many turns contributed (so the renderer
        can show "未实现" when N == 0 for an upgraded stage)

    A stage is included only when at least one turn reported it. We
    don't fabricate zeros for missing stages — that would let an
    older-deploy run silently inflate P50 toward zero.
    """
    p50: dict[str, float] = {}
    p95: dict[str, float] = {}
    sample_n: dict[str, int] = {}
    for stage in _STAGE_ORDER:
        samples: list[float] = []
        for r in main_oks:
            timings = r.main.stage_timings or {}
            stages_dict = timings.get("stages") if isinstance(timings, dict) else None
            if not isinstance(stages_dict, dict):
                continue
            v = stages_dict.get(stage)
            # Reject NaN / ±inf alongside negatives (CodeRabbit #14
            # round-7): `json.loads` accepts non-standard tokens by
            # default and a planner that emits Infinity would silently
            # corrupt every P50/P95 cell downstream.
            if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0:
                samples.append(float(v))
        if not samples:
            continue
        samples.sort()
        sample_n[stage] = len(samples)
        p50[stage] = samples[len(samples) // 2]
        idx = min(math.ceil(len(samples) * 0.95) - 1, len(samples) - 1)
        p95[stage] = samples[max(idx, 0)]
    return p50, p95, sample_n


def _op_percentiles(
    main_oks: list[CaseResult],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Per-op-kind P50/P95 across every op invocation, in milliseconds.

    The header carries `ops: [{kind, out, ms}, ...]` per request. We
    flatten across all successful turns and bucket by `kind` — so a
    `group_by` op contributes one sample per appearance, regardless of
    which case used it. This answers "in a complex 8-op plan, which
    *kind* of op is the slow one" rather than the per-stage view's
    "is execute as a whole slow".

    Returns three parallel dicts keyed by op kind. Buckets with no
    samples are omitted (rather than zero-filled) so the renderer can
    show "未实现" honestly when an older deploy didn't surface `ops`.
    """
    by_kind: dict[str, list[float]] = {}
    for r in main_oks:
        timings = r.main.stage_timings or {}
        ops = timings.get("ops") if isinstance(timings, dict) else None
        if not isinstance(ops, list):
            continue
        for entry in ops:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            ms = entry.get("ms")
            # Round-7: `math.isfinite(ms)` rejects NaN / ±inf which
            # `isinstance(_, (int, float))` lets through. Without this,
            # one bad header poisons the per-op P50/P95 row.
            if (
                not isinstance(kind, str)
                or not isinstance(ms, (int, float))
                or not math.isfinite(ms)
                or ms < 0
            ):
                continue
            by_kind.setdefault(kind, []).append(float(ms))

    p50: dict[str, float] = {}
    p95: dict[str, float] = {}
    sample_n: dict[str, int] = {}
    for kind, samples in by_kind.items():
        samples.sort()
        sample_n[kind] = len(samples)
        p50[kind] = samples[len(samples) // 2]
        idx = min(math.ceil(len(samples) * 0.95) - 1, len(samples) - 1)
        p95[kind] = samples[max(idx, 0)]
    return p50, p95, sample_n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


# Round-7 (CodeRabbit #17): every downstream codepath assumes
# `cases.yaml` deserialises to a list of dicts each carrying at least
# `id` and `question`. Validate the shape eagerly so a malformed
# manifest fails with a clear message at startup, not with an opaque
# `KeyError: 'id'` six minutes into a 20-case run.
_REQUIRED_CASE_KEYS: tuple[str, ...] = ("id", "question")


def _load_and_validate_cases(cases_file: Path) -> list[dict]:
    raw = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"--cases must be a YAML list at the top level, got: "
            f"{type(raw).__name__}"
        )
    for index, case in enumerate(raw):
        if not isinstance(case, dict):
            raise ValueError(
                f"--cases[{index}] must be a mapping, got: {type(case).__name__}"
            )
        missing = [k for k in _REQUIRED_CASE_KEYS if k not in case]
        if missing:
            cid = case.get("id", f"#{index}")
            raise ValueError(
                f"--cases[{cid!r}] is missing required key(s): {missing}"
            )
        # Round-10 (CodeRabbit #17): key presence isn't enough — a YAML
        # with `id: 123` or `question: []` passes presence checks then
        # blows up downstream when `run_case` does `case["id"].format()`
        # or POSTs the list-typed question as form-data. Validate the
        # required-field types alongside the optional ones so all shape
        # bugs surface at startup with a single style of error message.
        cid = case.get("id", f"#{index}")
        if not isinstance(case["id"], str):
            raise ValueError(
                f"--cases[{cid!r}].id must be a string, got: "
                f"{type(case['id']).__name__}"
            )
        if not isinstance(case["question"], str):
            raise ValueError(
                f"--cases[{cid!r}].question must be a string, got: "
                f"{type(case['question']).__name__}"
            )
        # Round-11 (CodeRabbit #17): hoist the path-traversal-safe
        # `_CASE_ID_PATTERN` check up from `_resolve_dataset_path` so
        # malformed ids surface at *manifest validation* rather than
        # the first time we try to read the CSV. The lookup function
        # still enforces the same pattern as a defensive double-check.
        if not _CASE_ID_PATTERN.fullmatch(case["id"]):
            raise ValueError(
                f"--cases[{cid!r}].id must match {_CASE_ID_PATTERN.pattern!r} "
                f"(ASCII alphanumerics, underscore, hyphen — no separators "
                f"or dots so the .csv suffix concat can't span directories)"
            )
        # Round-9 (CodeRabbit #17): the optional `followup` and `trap`
        # branches in `run_case` assume specific shapes — `followup`
        # is a string (the question text) and `trap` is a mapping
        # containing `expected_refusal`. A YAML where someone wrote
        # `trap:\n  - expected_refusal: false` (list-of-mappings
        # instead of mapping) would crash mid-run with an obscure
        # AttributeError. Validate the shapes alongside the required
        # keys so the failure surfaces at startup with a clear pointer
        # to the offending case id.
        if "followup" in case and not isinstance(case["followup"], str):
            raise ValueError(
                f"--cases[{cid!r}].followup must be a string (the "
                f"follow-up question), got: {type(case['followup']).__name__}"
            )
        if "trap" in case:
            trap = case["trap"]
            if not isinstance(trap, dict):
                raise ValueError(
                    f"--cases[{cid!r}].trap must be a mapping, got: "
                    f"{type(trap).__name__}"
                )
            if "expected_refusal" not in trap:
                raise ValueError(
                    f"--cases[{cid!r}].trap is missing required key: "
                    f"'expected_refusal'"
                )
            if "question" not in trap:
                raise ValueError(
                    f"--cases[{cid!r}].trap is missing required key: "
                    f"'question'"
                )
            # `expected_refusal` flows into a `bool` comparison inside
            # the scoring loop; `"true"` (string) would silently always
            # be truthy and never match the boolean from the body.
            # `bool` is a subclass of `int` so we can't use
            # `isinstance(..., (bool, int))` — `1` would pass.
            if not isinstance(trap["expected_refusal"], bool):
                raise ValueError(
                    f"--cases[{cid!r}].trap.expected_refusal must be a "
                    f"boolean, got: {type(trap['expected_refusal']).__name__}"
                )
            if not isinstance(trap["question"], str):
                raise ValueError(
                    f"--cases[{cid!r}].trap.question must be a string, "
                    f"got: {type(trap['question']).__name__}"
                )
        # Round-12 (CodeRabbit #17): optional `sampling_rate` must be a
        # plain finite float in (0, 1]. The renderer surfaces it in §6
        # so a string like "0.25" would render literally; a value > 1
        # would mean "we sampled MORE than the source", which is
        # nonsense; 0 or negative would mean "no rows", also nonsense.
        if "sampling_rate" in case:
            rate = case["sampling_rate"]
            # Reject bool first (bool < int < float — any bool would
            # otherwise pass the `(int, float)` check).
            if isinstance(rate, bool) or not isinstance(rate, (int, float)):
                raise ValueError(
                    f"--cases[{cid!r}].sampling_rate must be a number, "
                    f"got: {type(rate).__name__}"
                )
            if not math.isfinite(rate) or not (0 < float(rate) <= 1):
                raise ValueError(
                    f"--cases[{cid!r}].sampling_rate must be in (0, 1], "
                    f"got: {rate!r}"
                )
    # Round-12 (CodeRabbit #17): reject duplicate case ids. A duplicate
    # would silently overwrite the earlier case's run JSON in
    # `<run_dir>/<case_id>.json`, mixing main/follow-up/trap turns from
    # two different cases under one identity and breaking both `--resume`
    # split logic and the renderer's per-case stats.
    seen_ids: set[str] = set()
    for index, case in enumerate(raw):
        cid = case["id"]
        if cid in seen_ids:
            raise ValueError(
                f"--cases[{index}] duplicates case id {cid!r}; case ids must "
                f"be unique within a manifest"
            )
        seen_ids.add(cid)
    return raw


async def main_async(args: argparse.Namespace) -> int:
    cases_file: Path = args.cases
    data_dir: Path = args.data_dir
    all_cases = _load_and_validate_cases(cases_file)
    cases = all_cases

    # `--resume <run-dir>` reuses an existing run directory and only
    # re-runs cases whose previous JSON dump shows a non-200 main turn
    # (or is missing entirely). Useful when the backend was restarted
    # mid-run; without it we'd waste 20+ minutes re-doing successful
    # 5+-minute LLM calls.
    if args.resume is not None:
        run_dir: Path = args.resume
        run_dir.mkdir(parents=True, exist_ok=True)
        keep, redo = _split_resume(cases, run_dir)
        print(f"→ resume mode: keeping {len(keep)} prior results, re-running {len(redo)}")
        cases = redo
    else:
        run_dir = args.out
        run_dir.mkdir(parents=True, exist_ok=True)
        keep = []

    # Reporting window: when resuming a run we keep the *original*
    # started_at so the metrics file stamps the full window across
    # multiple resume passes. Only fall back to "now" if there is no
    # prior summary or it can't be parsed.
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    if args.resume is not None and keep:
        prior = run_dir / "summary.json"
        if prior.exists():
            try:
                prior_started = json.loads(prior.read_text(encoding="utf-8")).get(
                    "started_at"
                )
                if isinstance(prior_started, str) and prior_started:
                    started = prior_started
            except (OSError, ValueError):
                pass
    print(f"→ backend: {args.backend}")
    print(f"→ run dir: {run_dir}")
    print(f"→ cases:   {len(cases)}\n")

    results: list[CaseResult] = list(keep)
    async with httpx.AsyncClient(base_url=args.backend, timeout=HTTP_TIMEOUT_S) as client:
        try:
            v = await client.get("/version")
            v.raise_for_status()
            print(f"→ backend reachable: {v.json()}\n")
        except httpx.HTTPError as exc:
            print(f"backend not reachable: {exc}", file=sys.stderr)
            return 2

        for case in cases:
            try:
                result = await run_case(client, case, data_dir=data_dir)
            except Exception as exc:
                print(f"  ✗ {case['id']} crashed: {exc}", file=sys.stderr)
                result = CaseResult(
                    case_id=case["id"],
                    main=TurnResult(
                        label="analyze", status_code=0, latency_s=0.0, error=str(exc)
                    ),
                )
            results.append(result)
            (run_dir / f"{case['id']}.json").write_text(
                json.dumps(asdict(result), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # Order results by their place in cases.yaml so the End-to-end
    # table in the rendered metrics file is in the natural 01..15
    # order. Stale resumed JSONs (case_id no longer in cases.yaml) get
    # an out-of-range key and sort to the end rather than crashing the
    # whole run.
    canonical_index = {c["id"]: i for i, c in enumerate(all_cases)}
    results.sort(key=lambda r: canonical_index.get(r.case_id, len(canonical_index)))

    metrics = compute_metrics(results)
    completed = time.strftime("%Y-%m-%dT%H:%M:%S")
    summary = RunSummary(
        backend=args.backend,
        started_at=started,
        completed_at=completed,
        cases=[asdict(r) for r in results],
        metrics=metrics,
    )
    (run_dir / "summary.json").write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Metrics ===")
    for k, v in metrics.items():
        print(f"  {k:35s} = {v}")
    print(f"\n→ summary: {run_dir / 'summary.json'}")
    return 0


def _split_resume(
    cases: list[dict], run_dir: Path
) -> tuple[list[CaseResult], list[dict]]:
    """Partition cases into (already-good, must-redo).

    A case is considered already-good iff its previous JSON dump has a
    main turn with status 200. We deliberately do NOT salvage a partial
    case (e.g. main 200 but follow-up 0): re-running the whole case is
    cheap relative to the LLM-bound main path, and it keeps follow-up
    chained correctly to a fresh parent_id.
    """
    keep: list[CaseResult] = []
    redo: list[dict] = []

    def _ok(turn: dict | None) -> bool:
        # Mirror TurnResult.ok — a saved 200 with body=null happened
        # during one regression where the eval client logged the wrong
        # response shape; it should re-run, not be salvaged.
        return (
            isinstance(turn, dict)
            and turn.get("status_code") == 200
            and isinstance(turn.get("body"), dict)
        )

    for case in cases:
        case_id = case["id"]
        path = run_dir / f"{case_id}.json"
        if not path.exists():
            redo.append(case)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            redo.append(case)
            continue
        if not _ok(data.get("main")):
            redo.append(case)
            continue
        if "followup" in case and not _ok(data.get("followup")):
            redo.append(case)
            continue
        if "trap" in case and not _ok(data.get("trap")):
            # Only 200 with a body counts as a successful trap turn —
            # that's the contract shape we score against.
            redo.append(case)
            continue
        keep.append(_dict_to_case_result(data))
    return keep, redo


def _dict_to_case_result(data: dict) -> CaseResult:
    def _turn(d: dict | None) -> TurnResult | None:
        if d is None:
            return None
        # Round-10 (CodeRabbit #14): a prior run JSON may have been
        # written before the live `_parse_stage_timings` started filtering
        # NaN/Infinity (or by a future bug that re-introduces it). Re-
        # validate the cached payload before re-emitting it into the new
        # summary.json so resumes can't smuggle invalid JSON forward.
        cached_timings = d.get("stage_timings")
        if not isinstance(cached_timings, dict) or not _is_jsonable_finite(
            cached_timings
        ):
            cached_timings = None
        return TurnResult(
            label=d["label"],
            status_code=d["status_code"],
            latency_s=d["latency_s"],
            body=d.get("body"),
            error=d.get("error"),
            stage_timings=cached_timings,
        )

    main_turn = _turn(data["main"])
    assert main_turn is not None  # main is always present in a saved record
    return CaseResult(
        case_id=data["case_id"],
        main=main_turn,
        followup=_turn(data.get("followup")),
        trap=_turn(data.get("trap")),
        trap_expected_refusal=data.get("trap_expected_refusal"),
        sampling_rate=data.get("sampling_rate"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument(
        "--cases",
        type=Path,
        default=CASES_FILE,
        help="Path to a cases YAML file (default: eval/cases.yaml).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="Directory holding `<case_id>.csv` per case (default: eval/datasets/).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=RUNS_DIR / time.strftime("%Y%m%d-%H%M%S"),
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Reuse this run dir; only re-runs cases whose prior result was non-200",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
