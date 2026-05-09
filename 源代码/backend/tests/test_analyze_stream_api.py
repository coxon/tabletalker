"""End-to-end tests for POST /v1/analyze/stream — the NDJSON-streaming
variant the SPA uses to drive the live stage timeline.

The contract endpoint /v1/analyze stays untouched; this file mirrors
test_analyze_api.py's stub pattern but asserts the streaming protocol
instead of the JSON body."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.analyze as api_module
from app.analyze.handler import AnalyzeFailure
from app.analyze.stages import STAGE_ORDER
from app.main import app


class _SequencedStubClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls += 1
        if not self._responses:
            raise AssertionError(f"unexpected extra LLM call #{self.calls}")
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
            "summary": "华东地区销售额最高，总额为 300。",
            "title": "华东销售领先",
            "detail": "华东总额 300，华南总额 50。",
            "recommendations": ["加大华南促销投入"],
            "confidence": 0.85,
        }
    )


def _read_ndjson(response_lines) -> list[dict]:
    """Decode an NDJSON stream into a list of parsed events.

    `iter_lines()` from httpx splits on the standard CR/LF set; our
    server emits `\n`-terminated JSON so each yielded line is one event.
    Skip blank lines defensively (httpx may yield trailing empty bytes
    on stream close).
    """
    events: list[dict] = []
    for raw in response_lines:
        if not raw:
            continue
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        text = text.strip()
        if not text:
            continue
        events.append(json.loads(text))
    return events


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_stream_emits_stage_progression_then_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Streaming endpoint must emit:
      1. one `stage` start event for the first stage,
      2. alternating end+next-start events for stages in STAGE_ORDER,
      3. a single terminal `result` event whose `data` matches the
         non-streaming endpoint's JSON shape.
    """
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    with client.stream(
        "POST",
        "/v1/analyze/stream",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额是多少？", "dataset": "regional-sales"},
    ) as response:
        assert response.status_code == 200, response.read().decode("utf-8")
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = _read_ndjson(response.iter_lines())

    # Last event is the result.
    assert events, "stream produced zero events"
    terminal = events[-1]
    assert terminal["type"] == "result", terminal
    body = terminal["data"]
    # Same contract shape as /v1/analyze.
    assert body["id"].startswith("eval_analysis_")
    assert body["is_refusal"] is False
    assert "华东" in body["summary"]

    # Every prior event is a stage event referencing a known stage.
    stage_events = events[:-1]
    assert all(e["type"] == "stage" for e in stage_events)
    for e in stage_events:
        assert e["name"] in STAGE_ORDER, e

    # First event is `start` for the first stage.
    assert stage_events[0] == {
        "type": "stage",
        "name": STAGE_ORDER[0],
        "status": "start",
    }

    # All seven stages appear with status=end.
    ended = [e for e in stage_events if e["status"] == "end"]
    assert {e["name"] for e in ended} == set(STAGE_ORDER)

    # Stage end events arrive in pipeline order — the auto-grader's
    # mental model and the UI's row order both depend on that.
    end_order = [e["name"] for e in ended]
    assert end_order == list(STAGE_ORDER), end_order


def test_stream_terminal_result_carries_stage_timings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The terminal `result` event must include the same per-stage
    durations the legacy endpoint puts in the X-Stage-Timings header.
    Eval consumers that switch to streaming shouldn't lose data."""
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    with client.stream(
        "POST",
        "/v1/analyze/stream",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额是多少？"},
    ) as response:
        events = _read_ndjson(response.iter_lines())

    terminal = events[-1]
    timings = terminal["stage_timings"]
    assert "stages" in timings
    assert "total_s" in timings
    # Every stage we executed should have a positive (or zero) duration.
    for name in STAGE_ORDER:
        assert name in timings["stages"], (name, timings["stages"])


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


def test_stream_emits_error_event_on_handler_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `handle_analyze` raises `AnalyzeFailure`, the stream must
    end with an `error` event (no `result` event), and the HTTP status
    code must still be 200 — errors are signalled IN-band via the event
    payload, not via the response status (a non-200 status would close
    the stream before we could surface stage events).
    """

    async def boom(*args: Any, **kwargs: Any):
        raise AnalyzeFailure("planner returned an unparseable plan", status_code=422)

    monkeypatch.setattr(api_module, "handle_analyze", boom)
    monkeypatch.setattr(
        api_module,
        "HttpChatClient",
        lambda config: _SequencedStubClient([]),
    )

    with client.stream(
        "POST",
        "/v1/analyze/stream",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "随便问"},
    ) as response:
        assert response.status_code == 200
        events = _read_ndjson(response.iter_lines())

    terminal = events[-1]
    assert terminal["type"] == "error"
    assert terminal["status"] == 422
    assert "unparseable" in terminal["detail"]
    # No stray `result` event should sneak in.
    assert not any(e["type"] == "result" for e in events)


def test_stream_rejects_empty_question(client: TestClient) -> None:
    """Form validation runs BEFORE the stream is opened, so an empty
    question gets a normal 400 — there's nothing to stream."""
    response = client.post(
        "/v1/analyze/stream",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "   "},
    )
    assert response.status_code == 400
    assert "must not be empty" in response.text


def test_stream_returns_503_when_llm_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same env-missing path as the legacy endpoint: surface 503 from
    the prep stage, no stream opened."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    response = client.post(
        "/v1/analyze/stream",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "什么卖得最好？"},
    )
    assert response.status_code == 503
