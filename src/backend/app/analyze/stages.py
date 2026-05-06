"""Per-stage timing instrumentation for the `/v1/analyze` pipeline.

The handler runs a 7-step pipeline (profile → refusal → preview/plan_req →
plan(LLM) → execute → evidence → finalize(LLM) → assemble/render). Most of
the wall-clock time lives in the two LLM calls, but we don't want to *guess*
that — the API exposes per-stage durations so the eval runner can publish
honest P50/P95 per stage in `自测报告/latest_evaluation_metrics.md`.

The collector is opt-in: a stage is only recorded if the handler's caller
attached a `StageTimer` for the current request via `bind_stage_timer()`.
That keeps `handle_analyze` library-callable from contexts that don't care
about timings (existing unit tests, scripts), without forcing them to read
or pass extra state.

Why a contextvar rather than a parameter:

  - The handler's existing signature is part of the test surface
    (`tests/test_analyze_api.py` and the follow-up route both call it
    positionally). Adding a kwarg would ripple through every call site
    and every stub.
  - The route can install the timer just before invoking the handler and
    drop it afterwards, scoping the binding to a single request without
    leaking across concurrent requests (contextvars are async-safe).
  - The eval client reads the timings from a response header so we
    don't widen the public contract shape (`AnalyzeResponse` is frozen
    by `docs/submission-contract.md`).

Stage names are stable strings — the eval renderer joins on them.
"""

from __future__ import annotations

import contextvars
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

# Stable, ordered list of stage names. The handler uses `record(name)` to
# mark the *end* of the stage, so the duration covers everything since the
# previous mark (or `started_at` for the first stage). Keep this list in
# pipeline order — the renderer iterates it for table column ordering.
STAGE_ORDER: tuple[str, ...] = (
    "profile",          # parse + type inference
    "preview_plan_req", # 5-row preview + PlanRequest assembly
    "plan_llm",         # planner LLM round-trip
    "execute",          # sandboxed op execution
    "evidence",         # evidence row build
    "finalize_llm",     # finalize narrative LLM round-trip
    "render",           # Jinja HTML + chart pick + assemble response
)


@dataclass
class StageTimer:
    """Mutable accumulator for one request's stage timings.

    `record(name)` is called *after* a stage completes; the duration is
    `now - last_mark`, and `last_mark` advances. Stages can be skipped
    (refusal short-circuit doesn't run plan/execute/etc.) — the timer
    simply doesn't record entries for them, and the renderer treats
    missing keys as "not measured for this turn" rather than zero.

    All durations are seconds (float). `started_at` is wall-clock for
    eyeballing alignment with server logs; durations come from
    `time.perf_counter()` for monotonic correctness.

    `ops` is a parallel, optional dimension: when the executor finishes
    we stuff each op's `(kind, out, ms)` here so the eval renderer can
    show "which op in a complex plan was the slow one". The umbrella
    `execute` duration in `durations` still reflects total time inside
    the executor (so total_s remains additive over `durations`); `ops`
    is purely diagnostic.
    """

    started_wall: float = field(default_factory=time.time)
    _t0: float = field(default_factory=time.perf_counter)
    _last: float = field(init=False)
    durations: dict[str, float] = field(default_factory=dict)
    ops: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._last = self._t0

    def record(self, stage: str) -> None:
        """Mark `stage` complete; duration = now − last_mark."""
        now = time.perf_counter()
        # Last-write-wins: a re-recorded stage overwrites rather than
        # accumulating. The handler never re-records the same stage in
        # one request, but if a future refactor does, we'd rather see
        # the most recent measurement than a silent sum.
        self.durations[stage] = max(0.0, now - self._last)
        self._last = now

    def record_ops(self, op_entries: list[dict[str, object]]) -> None:
        """Attach the executor's per-op timings.

        `op_entries` is `[{kind, out, ms}, ...]` in plan order. We don't
        recompute durations here — the executor already wall-clocks each
        op via `result.ms`, so we just transcribe. Called once per
        request, post-execute, by the handler.
        """
        # Defensive copy + clamp shape so a buggy caller can't smuggle
        # surprise keys into the response header (which is parsed by the
        # eval renderer).
        clean: list[dict[str, object]] = []
        for entry in op_entries:
            clean.append(
                {
                    "kind": str(entry.get("kind", "")),
                    "out": str(entry.get("out", "")),
                    "ms": round(float(entry.get("ms") or 0.0), 3),
                }
            )
        self.ops = clean

    def total_s(self) -> float:
        """Sum of recorded stage durations (≈ end-to-end wall time)."""
        return sum(self.durations.values())

    def as_payload(self) -> dict[str, object]:
        """JSON-safe dict for the response header."""
        payload: dict[str, object] = {
            "started_wall": round(self.started_wall, 3),
            "total_s": round(self.total_s(), 4),
            "stages": {k: round(v, 4) for k, v in self.durations.items()},
        }
        # Only include `ops` when populated — refusal-carry / library-mode
        # callers leave it empty and the header stays compact.
        if self.ops:
            payload["ops"] = self.ops
        return payload


# Per-request binding. `None` means "no caller asked for timings"; the
# handler's `record(...)` calls become no-ops. ContextVar isolates
# concurrent requests — each FastAPI request runs in its own task with its
# own ContextVar copy, so timer state can't bleed across requests.
_active: contextvars.ContextVar[StageTimer | None] = contextvars.ContextVar(
    "tabletalker_stage_timer", default=None
)


@contextmanager
def bind_stage_timer() -> Iterator[StageTimer]:
    """Install a fresh `StageTimer` for the duration of a `with` block.

    Yields the timer so the caller (route handler) can read its results
    after `handle_analyze` returns. Restores the previous binding on
    exit so nested calls don't clobber each other — not currently used
    but keeps the abstraction safe for future composition.
    """
    timer = StageTimer()
    token = _active.set(timer)
    try:
        yield timer
    finally:
        _active.reset(token)


def record(stage: str) -> None:
    """Record the end of `stage` if a timer is bound; no-op otherwise.

    The handler calls this; library-mode callers that didn't bind a
    timer pay nothing beyond a ContextVar read.
    """
    timer = _active.get()
    if timer is not None:
        timer.record(stage)


def record_ops(op_entries: list[dict[str, object]]) -> None:
    """Attach per-op timings to the bound timer; no-op otherwise.

    The handler calls this once after the executor returns, passing
    `[{kind, out, ms}, ...]` in plan order. The eval runner reads it
    out of the `X-Stage-Timings` header to surface "which op in a
    complex plan was the slow one".
    """
    timer = _active.get()
    if timer is not None:
        timer.record_ops(op_entries)


def serialize_header(timer: StageTimer) -> str:
    """JSON-encode the timer for the `X-Stage-Timings` response header.

    Header values must be ASCII-safe; we use `ensure_ascii=True` so any
    future non-ASCII stage name (we don't have any) wouldn't break HTTP
    serialisation. Compact separators keep the header short — most
    proxies tolerate a few hundred bytes without complaint.
    """
    return json.dumps(timer.as_payload(), separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "STAGE_ORDER",
    "StageTimer",
    "bind_stage_timer",
    "record",
    "record_ops",
    "serialize_header",
]
