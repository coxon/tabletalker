"""Stage-timing instrumentation tests.

Covers:
  - `StageTimer.record` advances `_last` so durations are non-overlapping.
  - `bind_stage_timer()` is per-context (concurrent requests don't bleed).
  - The route layer surfaces timings as the `X-Stage-Timings` header.
  - Library-mode callers (no `bind_stage_timer`) pay no penalty — `record()`
    is a no-op when the contextvar is unset.

We avoid sleep-based asserts (flaky on CI runners) and check structural
invariants instead: stage names, ordering, key shape.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.analyze as api_module
from app.analyze.stages import (
    STAGE_ORDER,
    StageTimer,
    bind_stage_timer,
    record,
    record_ops,
    serialize_header,
)
from app.main import app

# ---------------------------------------------------------------------------
# Unit: StageTimer
# ---------------------------------------------------------------------------


def test_record_unbound_is_noop() -> None:
    # Calling `record()` outside a `bind_stage_timer()` block must not
    # raise — handler.py and follow_up.py both rely on this so library
    # mode (e.g. CLI scripts that call `handle_analyze` directly) keeps
    # working without a timer.
    record("profile")  # would raise if record() reached into None
    record("plan_llm")


def test_bind_stage_timer_collects_records() -> None:
    with bind_stage_timer() as t:
        record("profile")
        record("execute")
    assert set(t.durations) == {"profile", "execute"}
    # Both durations must be non-negative; perf_counter monotonicity
    # guarantees this but we assert it explicitly so a future bug that
    # subtracts in the wrong direction surfaces here, not in metrics.
    assert all(v >= 0 for v in t.durations.values())


def test_bind_stage_timer_resets_after_block() -> None:
    # The context var is restored on exit so a second bind starts fresh.
    with bind_stage_timer() as t1:
        record("profile")
    assert "profile" in t1.durations
    record("profile")  # noop: outside the block
    with bind_stage_timer() as t2:
        record("execute")
    assert "execute" in t2.durations
    assert "profile" not in t2.durations


def test_serialize_header_shape() -> None:
    timer = StageTimer()
    timer.record("profile")
    timer.record("plan_llm")
    raw = serialize_header(timer)
    payload = json.loads(raw)
    # `ops` is optional — only present when populated.
    assert payload.keys() == {"started_wall", "total_s", "stages"}
    # `payload["total_s"]` is `round(sum(raw_durations), 4)` while the
    # RHS sums the *already-rounded* per-stage values; with N stages the
    # discrepancy can reach N×5e-5 plus timing jitter. Match the
    # integration test below (`abs=1e-3`) so loaded CI runners don't flake.
    assert payload["total_s"] == pytest.approx(
        sum(payload["stages"].values()), abs=1e-3
    )
    # All stage names live in STAGE_ORDER (typo guard for handler.py).
    assert set(payload["stages"]).issubset(set(STAGE_ORDER))


def test_record_ops_attaches_op_breakdown() -> None:
    """Per-op timings ride alongside `stages` for diagnostic depth."""
    with bind_stage_timer() as t:
        record("execute")
        record_ops(
            [
                {"kind": "load_csv", "out": "raw", "ms": 12.345},
                {"kind": "group_by", "out": "g", "ms": 0.7},
                {"kind": "aggregate", "out": "totals", "ms": 1.2},
            ]
        )
    assert len(t.ops) == 3
    assert t.ops[0] == {"kind": "load_csv", "out": "raw", "ms": 12.345}
    raw = serialize_header(t)
    payload = json.loads(raw)
    assert "ops" in payload  # populated → present
    assert [op["kind"] for op in payload["ops"]] == ["load_csv", "group_by", "aggregate"]
    # `ms` is rounded to 3 decimal places by record_ops; this is the
    # contract eval/run.py joins on for the per-op section of §9.
    assert payload["ops"][0]["ms"] == 12.345


def test_record_ops_is_noop_when_unbound() -> None:
    # Library-mode callers must not crash when no timer is attached.
    record_ops([{"kind": "load_csv", "out": "raw", "ms": 0.1}])  # no raise


def test_record_ops_omitted_when_empty() -> None:
    # Refusal-carry / no-execute paths leave `ops` empty; the header
    # stays compact rather than serialising `"ops":[]`.
    timer = StageTimer()
    timer.record("profile")
    raw = serialize_header(timer)
    payload = json.loads(raw)
    assert "ops" not in payload


def test_record_ops_sanitizes_malformed_entries() -> None:
    """Telemetry must never break the response (CodeRabbit #14 round-2).

    `record_ops` accepts whatever the executor handed us. A plan with
    one buggy op (e.g. `None` smuggled in by a future op kind, a non-
    numeric `ms`, a negative timing from clock skew, or a non-finite
    overflow like `1e309 == inf`) must not 500 the request. The
    contract:
      - Non-dict entries are silently skipped.
      - Non-numeric / negative / non-finite `ms` is coerced to `0.0`.
        Non-finite handling is round-4: `inf` would otherwise survive
        `max(0.0, ...)` and serialise as invalid `Infinity` JSON.
      - The header still serializes cleanly.
    """
    with bind_stage_timer() as t:
        record("execute")
        t.record_ops(
            [
                # Valid baseline
                {"kind": "load_csv", "out": "raw", "ms": 1.5},
                # Garbage that would normally crash `entry.get(...)`
                None,  # type: ignore[list-item]
                [1, 2, 3],  # type: ignore[list-item]
                "bad",  # type: ignore[list-item]
                # Non-numeric `ms` → coerced to 0.0 by `_safe_float`
                {"kind": "group_by", "out": "g", "ms": "N/A"},
                # Negative `ms` → clamped to 0.0
                {"kind": "aggregate", "out": "totals", "ms": -5.0},
                # Non-finite `ms` (overflow) → clamped to 0.0; without
                # this, `json.dumps` would emit `Infinity` (invalid
                # RFC 4627) and break strict header consumers.
                {"kind": "to_chart", "out": "chart", "ms": float("inf")},
                {"kind": "render", "out": "html", "ms": float("nan")},
            ]
        )
    raw = serialize_header(t)
    # Strict JSON parser must accept the header — `Infinity`/`NaN`
    # would fail `json.loads` (which mirrors the eval renderer).
    payload = json.loads(raw)
    assert "ops" in payload
    # 5 valid dicts survive (1 valid + 1 NA + 1 negative + 1 inf + 1 nan);
    # the 3 non-dict entries are dropped.
    assert len(payload["ops"]) == 5
    assert payload["ops"][0]["ms"] == 1.5
    # All sanitised entries collapsed to 0.0 — same floor as `record()`.
    for sanitised in payload["ops"][1:]:
        assert sanitised["ms"] == 0.0


def test_record_ops_caps_count_and_field_length() -> None:
    """Header serialisation is bounded: at most MAX_HEADER_OPS entries
    survive, and each `kind`/`out` is truncated to MAX_OP_FIELD_CHARS.

    Without these caps a planner emitting many ops or absurdly long
    opaque ids could blow past the proxy's response-header ceiling.
    """
    from app.analyze.stages import MAX_HEADER_OPS, MAX_OP_FIELD_CHARS

    long_name = "x" * (MAX_OP_FIELD_CHARS + 32)
    entries: list[dict[str, object]] = [
        {"kind": long_name, "out": long_name, "ms": 0.1}
        for _ in range(MAX_HEADER_OPS + 25)
    ]
    timer = StageTimer()
    timer.record_ops(entries)
    assert len(timer.ops) == MAX_HEADER_OPS
    # Both string fields are truncated to the configured ceiling.
    assert all(
        isinstance(op["kind"], str) and len(op["kind"]) == MAX_OP_FIELD_CHARS
        for op in timer.ops
    )
    assert all(
        isinstance(op["out"], str) and len(op["out"]) == MAX_OP_FIELD_CHARS
        for op in timer.ops
    )


def test_serialize_header_caps_byte_size_for_cjk_payload() -> None:
    """`ensure_ascii=True` expands CJK 6x (`测` -> `\\u6d4b`), so a
    CJK-heavy plan that satisfies the per-op char cap can still
    overflow the response header. Round-3 of CodeRabbit on #14:
    `serialize_header` must drop trailing ops until the serialised
    payload fits `MAX_HEADER_BYTES`.

    The test assembles 50 x 64-CJK-char ops (the legal max under the
    per-field caps) - naively this serialises to ~40 KiB; the header
    must come out at <= MAX_HEADER_BYTES with the head of the plan
    preserved (so the slow op, almost always near the head, stays
    visible in metrics).
    """
    from app.analyze.stages import (
        MAX_HEADER_BYTES,
        MAX_HEADER_OPS,
        MAX_OP_FIELD_CHARS,
    )

    timer = StageTimer()
    timer.record("execute")
    timer.record_ops(
        [
            {
                "kind": "测" * MAX_OP_FIELD_CHARS,
                "out": "试" * MAX_OP_FIELD_CHARS,
                "ms": 0.1,
            }
            for _ in range(MAX_HEADER_OPS)
        ]
    )
    raw = serialize_header(timer)
    # Header must fit the byte ceiling.
    assert len(raw.encode("ascii")) <= MAX_HEADER_BYTES
    payload = json.loads(raw)
    # Stages survive intact — the renderer joins on them and refusing
    # to publish them would lose more than dropping ops would.
    assert "stages" in payload and "execute" in payload["stages"]
    # Some ops survived (the head of the plan) — diagnostic value
    # isn't entirely lost, just bounded.
    assert "ops" in payload
    assert 0 < len(payload["ops"]) < MAX_HEADER_OPS



def test_concurrent_binds_are_isolated() -> None:
    # Two coroutines holding their own StageTimer must not mix their
    # records. `contextvars` is the mechanism; this test pins the
    # invariant down so a future refactor to a module-global would
    # immediately fail.
    async def _scenario(name: str) -> dict[str, float]:
        with bind_stage_timer() as t:
            record(name)
            await asyncio.sleep(0)  # yield control to the other task
            record("render")
        return dict(t.durations)

    async def _runner() -> tuple[dict[str, float], dict[str, float]]:
        a, b = await asyncio.gather(_scenario("profile"), _scenario("execute"))
        return a, b

    a, b = asyncio.run(_runner())
    assert "profile" in a and "render" in a
    assert "execute" in b and "render" in b
    # Cross-contamination would put "execute" into `a` or "profile" into `b`.
    assert "execute" not in a
    assert "profile" not in b


# ---------------------------------------------------------------------------
# Integration: header surfaced via /v1/analyze
# ---------------------------------------------------------------------------


class _SequencedStubClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not self._responses:
            raise AssertionError("unexpected extra LLM call")
        return self._responses.pop(0)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("LLM_BASE_URL", "https://stub.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    return TestClient(app)


def _csv_bytes() -> bytes:
    return (
        b"region,amount\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,100\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,200\n"
        b"\xe5\x8d\x8e\xe5\x8d\x97,50\n"
        b"\xe5\x8d\x8e\xe5\x8c\x97,75\n"
    )


def _plan_json() -> str:
    return json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                {"kind": "group_by", "out": "g", "src": "raw", "by": ["region"]},
                {
                    "kind": "aggregate",
                    "out": "totals",
                    "src": "g",
                    "aggs": [{"column": "amount", "fn": "sum", "as": "total"}],
                },
                {"kind": "to_table", "out": "answer", "src": "totals"},
            ],
            "answer": "answer",
        }
    )


def _narrative_json() -> str:
    return json.dumps(
        {
            "summary": "华东 300，华南 50，差距明显。" * 12,  # ≥300 chars
            "title": "区域销售对比",
            "detail": "华东总额 300，华南总额 50。",
            "recommendations": ["加大华南投放"],
            "confidence": 0.8,
        }
    )


def test_analyze_emits_x_stage_timings_header(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: header is present, parsable, lists known stages."""
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额是多少？"},
    )
    assert response.status_code == 200, response.text
    raw = response.headers.get("X-Stage-Timings")
    assert raw, "header must be present on 200 responses"
    payload = json.loads(raw)
    assert {"started_wall", "total_s", "stages"}.issubset(payload.keys())
    # Happy path runs the executor → `ops` must be present too.
    assert "ops" in payload, "happy path must surface per-op timings"
    assert isinstance(payload["ops"], list) and len(payload["ops"]) >= 1
    assert {"kind", "out", "ms"}.issubset(payload["ops"][0].keys())
    # The handler walks the deterministic stages on every happy path.
    # plan_llm + finalize_llm are stubbed (zero LLM latency) but still
    # recorded — what we assert is presence, not magnitude.
    expected_minimum = {
        "profile",
        "preview_plan_req",
        "plan_llm",
        "execute",
        "evidence",
        "finalize_llm",
        "render",
    }
    assert expected_minimum.issubset(payload["stages"])
    # Total must equal the sum of stage durations modulo float fuzz.
    assert payload["total_s"] == pytest.approx(
        sum(payload["stages"].values()), abs=1e-3
    )


def test_analyze_refusal_still_emits_header(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusal path short-circuits before LLM but still publishes timings.

    The eval renderer iterates all 200 responses; a missing header would
    look like "the backend forgot to instrument refusals" rather than the
    truth ("the LLM stages were skipped because we refused"). We surface
    a small `stages` dict instead.
    """
    # No stub — the refusal heuristic must fire on the keyword and
    # short-circuit before any LLM call.
    monkeypatch.setattr(
        api_module, "HttpChatClient", lambda config: _SequencedStubClient([])
    )

    csv = b"name,salary\nA,100\nB,200\n"
    response = client.post(
        "/v1/analyze",
        files={"file": ("emp.csv", csv, "text/csv")},
        # English token "race" — the trap detector requires whole-token
        # match (see _detect_refusal in handler.py). CJK questions like
        # "按种族分析" don't tokenise the keyword out cleanly under the
        # default `\w+` split, so they don't trigger the heuristic; the
        # production refusal flow there relies on the LLM's session
        # prelude rather than this trap. Test the path that the trap
        # actually covers.
        data={"question": "Show purchase rate by race"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    raw = response.headers.get("X-Stage-Timings")
    assert raw, "refusal must still publish a stage-timings header"
    payload = json.loads(raw)
    # Refusal records `profile` (we read the file before the trap fires).
    # plan/execute/finalize must NOT be present — this is the renderer's
    # signal that the turn was a refusal even before reading is_refusal.
    assert "profile" in payload["stages"]
    assert "plan_llm" not in payload["stages"]
    assert "finalize_llm" not in payload["stages"]
