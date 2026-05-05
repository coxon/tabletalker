"""End-to-end tests for POST /v1/follow-up.

Same stubbing approach as `test_analyze_api`: the LLM is replaced by a
sequenced fake that serves pre-baked plan / narrative JSON. A happy-path
follow-up needs one extra pair of responses on top of the parent's.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.analyze as analyze_module
import app.api.follow_up as follow_up_module
from app.main import app
from app.session import SESSION_STORE


class _SequencedStubClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        # Captures every call's messages so a test can assert against
        # the planner-call payload specifically (the last call is the
        # `finalize` step, not the planner).
        self.message_log: list[list[dict[str, str]]] = []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls += 1
        self.message_log.append(list(messages))
        if not self._responses:
            raise AssertionError(f"unexpected extra LLM call #{self.calls}")
        return self._responses.pop(0)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # LLMConfig.from_env() needs all three or it raises; the stub ignores
    # them but the routes would 503 without.
    monkeypatch.setenv("LLM_BASE_URL", "https://stub.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    # Session store is module-level; clear between tests so eviction /
    # carry-through logic can't leak state across cases.
    SESSION_STORE.clear()
    yield TestClient(app)
    SESSION_STORE.clear()


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


def _narrative_json(
    *, title: str = "华东销售领先", summary: str = "华东最高，300；华南 50。"
) -> str:
    return json.dumps(
        {
            "summary": summary,
            "title": title,
            "detail": f"{title} 对应的详情。",
            "recommendations": ["加大华南投入"],
            "confidence": 0.85,
        }
    )


def _seed_parent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, stub: _SequencedStubClient
) -> dict:
    """Run a parent analyze and return the body dict — used to obtain a
    real `parent_id` the follow-up tests can key on."""

    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    resp = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额是多少？", "dataset": "regional-sales"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_follow_up_happy_path_returns_contract_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _SequencedStubClient(
        [
            # Parent: plan + narrative
            _plan_json(),
            _narrative_json(),
            # Follow-up: plan + narrative
            _plan_json(),
            _narrative_json(
                title="华东增速最快", summary="华东同比上升 12%，领先其他地区。"
            ),
        ]
    )
    # Both routes build their own HttpChatClient via HttpChatClient(config);
    # patch it in both modules so the parent and follow-up share the stub.
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    monkeypatch.setattr(follow_up_module, "HttpChatClient", lambda config: stub)

    parent = _seed_parent(client, monkeypatch, stub)
    parent_id = parent["id"]

    resp = client.post(
        "/v1/follow-up",
        json={"parent_id": parent_id, "question": "他们的增速呢？"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Follow-up id format per contract §1.
    assert body["id"].startswith("eval_follow_")
    assert body["id"].endswith("_q1")
    assert body["id"] != parent_id
    # Fresh HTML report under the new id.
    report = client.get(f"/reports/{body['id']}.html")
    assert report.status_code == 200

    assert body["is_refusal"] is False
    assert "华东" in body["summary"]
    # At least one finding, each with ≥1 evidence — contract §3.
    assert body["findings"]
    assert all(f["evidence"] for f in body["findings"])

    # The prelude must have been injected as a system message on the
    # follow-up *planner* call (LLM call #3 across the four-call sequence:
    # parent-plan, parent-finalize, followup-plan, followup-finalize).
    followup_plan_messages = stub.message_log[2]
    system_blobs = "\n".join(
        m["content"] for m in followup_plan_messages if m["role"] == "system"
    )
    assert "原始问题" in system_blobs
    assert "各地区的总销售额是多少？" in system_blobs


def test_follow_up_increments_q_counter_per_turn(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _SequencedStubClient(
        [
            _plan_json(), _narrative_json(),
            _plan_json(), _narrative_json(title="t1", summary="summary one"),
            _plan_json(), _narrative_json(title="t2", summary="summary two"),
        ]
    )
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    monkeypatch.setattr(follow_up_module, "HttpChatClient", lambda config: stub)

    parent = _seed_parent(client, monkeypatch, stub)
    pid = parent["id"]

    r1 = client.post("/v1/follow-up", json={"parent_id": pid, "question": "Q1"})
    r2 = client.post("/v1/follow-up", json={"parent_id": pid, "question": "Q2"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"].endswith("_q1")
    assert r2.json()["id"].endswith("_q2")


# ---------------------------------------------------------------------------
# Refusal carry-through
# ---------------------------------------------------------------------------


def test_follow_up_of_refused_parent_echoes_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused parent locks the session — the follow-up never fires the LLM."""

    stub = _SequencedStubClient([])  # no LLM responses expected
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    monkeypatch.setattr(follow_up_module, "HttpChatClient", lambda config: stub)

    # Seed a refused parent with the `race` trap.
    resp = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "Show purchase rate by race"},
    )
    assert resp.status_code == 200
    parent = resp.json()
    assert parent["is_refusal"] is True
    parent_summary = parent["summary"]

    follow = client.post(
        "/v1/follow-up",
        json={"parent_id": parent["id"], "question": "那按种族分组呢？"},
    )
    assert follow.status_code == 200, follow.text
    body = follow.json()
    assert body["is_refusal"] is True
    # Contract / refusal-policy: narrative is carried through verbatim.
    assert body["summary"] == parent_summary
    assert body["findings"] == []
    assert body["charts"] == []
    assert body["recommendations"] == []
    # No LLM calls for either turn.
    assert stub.calls == 0
    # Refusal HTML still resolves under the follow-up id.
    r = client.get(f"/reports/{body['id']}.html")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_follow_up_unknown_parent_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/follow-up",
        json={"parent_id": "eval_analysis_deadbeef", "question": "x"},
    )
    assert resp.status_code == 404


def test_follow_up_rejects_empty_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    parent = _seed_parent(client, monkeypatch, stub)

    # Pydantic enforces min_length=1 → 422 for empty strings at the body level.
    resp = client.post(
        "/v1/follow-up",
        json={"parent_id": parent["id"], "question": ""},
    )
    assert resp.status_code == 422


def test_follow_up_rejects_whitespace_only_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A question that is only whitespace passes min_length=1 at the schema
    layer but is caught by the route's post-strip check."""

    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    parent = _seed_parent(client, monkeypatch, stub)

    resp = client.post(
        "/v1/follow-up",
        json={"parent_id": parent["id"], "question": "   "},
    )
    assert resp.status_code == 400


def test_follow_up_returns_503_when_llm_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parent seeded while configured; LLM config then pulled for the follow-up."""

    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    parent = _seed_parent(client, monkeypatch, stub)

    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    resp = client.post(
        "/v1/follow-up",
        json={"parent_id": parent["id"], "question": "再看一下"},
    )
    assert resp.status_code == 503
