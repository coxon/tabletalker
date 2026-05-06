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
import math
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
    than zero. Malformed JSON is logged-but-ignored — we don't want a
    bad header to fail an otherwise-good run.
    """
    raw = response.headers.get("X-Stage-Timings")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _post_analyze(
    client: httpx.AsyncClient, dataset_path: Path, question: str
) -> TurnResult:
    started = time.monotonic()
    try:
        with dataset_path.open("rb") as f:
            response = await client.post(
                "/v1/analyze",
                files={"file": (dataset_path.name, f, "text/csv")},
                data={"question": question},
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


async def run_case(client: httpx.AsyncClient, case: dict) -> CaseResult:
    case_id = case["id"]
    dataset_path = DATA_DIR / f"{case_id}.csv"
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset missing: {dataset_path}")

    print(f"  · {case_id} · main", flush=True)
    main = await _post_analyze(client, dataset_path, case["question"])

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
        trap = await _post_analyze(client, dataset_path, case["trap"]["question"])

    return CaseResult(
        case_id=case_id,
        main=main,
        followup=followup,
        trap=trap,
        trap_expected_refusal=expected_refusal,
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

    trap_correct = 0
    trap_total = 0
    false_refuse_count = 0
    false_refuse_total = 0
    for r in results:
        if r.trap is not None and r.trap_expected_refusal is not None:
            trap_total += 1
            # Distinguish "request failed / shape was wrong" (None) from
            # "agent answered" (False). Coercing to False would let a
            # transport failure read as a non-refusal and inflate
            # correctness on `expected_refusal: false` cases.
            if r.trap.ok:
                v = (r.trap.body or {}).get("is_refusal")
                actual: bool | None = v if isinstance(v, bool) else None
            else:
                actual = None
            if actual is not None and actual == r.trap_expected_refusal:
                trap_correct += 1
            # `expected_refusal: false` traps are part of the false-
            # refuse measurement: a refusal there is precisely what
            # the metric is designed to catch. Skipping them would
            # inflate false-refuse correctness.
            if r.trap_expected_refusal is False and actual is not None:
                false_refuse_total += 1
                if actual is True:
                    false_refuse_count += 1
        if r.main.ok:
            false_refuse_total += 1
            if (r.main.body or {}).get("is_refusal") is True:
                false_refuse_count += 1

    refusal_accuracy = trap_correct / trap_total if trap_total else 0.0
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

    return {
        "datasets_total": main_total,
        "main_success_count": len(main_oks),
        "main_success_rate": plan_success_rate,
        "p50_latency_s": p50,
        "p95_latency_s": p95,
        "evidence_completeness": evidence_completeness,
        "distinct_chart_types": distinct_chart_types,
        "avg_summary_len_chars": avg_summary_len,
        "refusal_accuracy_on_traps": refusal_accuracy,
        "refusal_correct_count": trap_correct,
        "trap_cases_total": trap_total,
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
            if isinstance(v, (int, float)) and v >= 0:
                samples.append(float(v))
        if not samples:
            continue
        samples.sort()
        sample_n[stage] = len(samples)
        p50[stage] = samples[len(samples) // 2]
        idx = min(math.ceil(len(samples) * 0.95) - 1, len(samples) - 1)
        p95[stage] = samples[max(idx, 0)]
    return p50, p95, sample_n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    all_cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
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
                result = await run_case(client, case)
            except Exception as exc:  # noqa: BLE001
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
        return TurnResult(
            label=d["label"],
            status_code=d["status_code"],
            latency_s=d["latency_s"],
            body=d.get("body"),
            error=d.get("error"),
            stage_timings=d.get("stage_timings"),
        )

    main_turn = _turn(data["main"])
    assert main_turn is not None  # main is always present in a saved record
    return CaseResult(
        case_id=data["case_id"],
        main=main_turn,
        followup=_turn(data.get("followup")),
        trap=_turn(data.get("trap")),
        trap_expected_refusal=data.get("trap_expected_refusal"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://localhost:8000")
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
