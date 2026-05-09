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

    # PR #22: keyword classifier removed — provide a refuse-op plan so
    # the parent analyze refuses via the LLM-driven path. Follow-up uses
    # carry-through (no LLM call), so one stub response suffices.
    refuse_plan = (
        '{"ops":[{"kind":"refuse","out":"_r","category":1,'
        '"narrative":"数据集中不包含「Race」字段，无法基于现有字段对该维度进行分析。"}],'
        '"answer":"_r"}'
    )
    stub = _SequencedStubClient([refuse_plan])
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
    # Parent burned 1 LLM call (planner emitted refuse op); follow-up
    # carry-through path makes zero LLM calls of its own.
    assert stub.calls == 1
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


def test_follow_up_rejects_unknown_body_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`extra='forbid'` surfaces typos like `parentId` as a 422 with a
    precise field name rather than silently ignoring the unknown key."""

    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    parent = _seed_parent(client, monkeypatch, stub)

    resp = client.post(
        "/v1/follow-up",
        json={"parentId": parent["id"], "question": "x"},
    )
    assert resp.status_code == 422


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


# ---------------------------------------------------------------------------
# Sampling inheritance (README §3.3 雷7 / §7.2 #7)
# ---------------------------------------------------------------------------


def test_follow_up_inherits_sampling_from_parent_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A follow-up must stamp the parent's `sampling_rate` / `sampling_note`
    on its own Evidence rows.

    Why: sampling is a property of the *file* on disk, not of the turn.
    The same workspace serves every follow-up. If the rate doesn't carry
    through, the auto-grader compares the follow-up's row counts to the
    full source and judges every follow-up Evidence as fabricated —
    breaking session-level scoring entirely.
    """
    stub = _SequencedStubClient(
        [
            _plan_json(),
            _narrative_json(),
            _plan_json(),
            _narrative_json(title="华南增速最快"),
        ]
    )
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    monkeypatch.setattr(follow_up_module, "HttpChatClient", lambda config: stub)

    # Parent declares sampling — bypass _seed_parent so we can pass form
    # fields the helper doesn't know about.
    parent_resp = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={
            "question": "各地区的总销售额是多少？",
            "dataset": "regional-sales",
            "sampling_rate": "0.25",
            "sampling_note": "25k of 100k rows; deterministic seed=42",
        },
    )
    assert parent_resp.status_code == 200, parent_resp.text
    parent_id = parent_resp.json()["id"]

    follow_resp = client.post(
        "/v1/follow-up",
        json={"parent_id": parent_id, "question": "他们的增速呢？"},
    )
    assert follow_resp.status_code == 200, follow_resp.text
    follow_body = follow_resp.json()
    assert follow_body["findings"], "happy-path follow-up should yield findings"
    for finding in follow_body["findings"]:
        # Round-9 (CodeRabbit #15): without this guard the inner loop
        # silently passes when the planner happens to emit an empty
        # evidence list — making the sampling-inheritance assertion
        # vacuous. We're testing that *evidence rows* inherit the
        # sampling fields, so each finding must actually carry rows.
        assert finding["evidence"], (
            f"finding {finding.get('id', '<no-id>')!r} should include "
            f"evidence rows so the sampling-inheritance assertion is "
            f"non-vacuous"
        )
        for row in finding["evidence"]:
            assert row["sampling_rate"] == 0.25
            assert row["sampling_note"] == "25k of 100k rows; deterministic seed=42"


def _regions_csv_bytes() -> bytes:
    """Companion fixture used by the multi-file follow-up test."""
    return (
        b"region,region_name\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,East China\n"
        b"\xe5\x8d\x8e\xe5\x8d\x97,South China\n"
        b"\xe5\x8d\x8e\xe5\x8c\x97,North China\n"
    )


def _multi_file_plan_json() -> str:
    """Plan that references BOTH tables — the follow-up must still be
    able to execute this, which requires `extra_filenames` to survive
    in the session.
    """
    return json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "sales", "path": "sales.csv"},
                {"kind": "load_csv", "out": "regions", "path": "regions.csv"},
                {
                    "kind": "join",
                    "out": "joined",
                    "left": "sales",
                    "right": "regions",
                    "on": ["region"],
                    "how": "inner",
                },
                {
                    "kind": "group_by",
                    "out": "g",
                    "src": "joined",
                    "by": ["region_name"],
                },
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


def test_follow_up_preserves_extra_filenames_from_multi_file_parent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multi-file parent turns must not degrade to single-file on follow-up.

    Round-15 (CodeRabbit #17 Critical): `session_from_response()` used to
    drop the auxiliary filenames, so the follow-up handler reconstructed
    an `AnalyzeRequest` with only the primary table. Any plan that
    referenced a secondary table (the common `join` case for 03_tmdb /
    04_telecom_churn cases in eval) would then fail with
    ``load_csv: file not found: regions.csv`` on the second turn.

    Regression shape:
      1. Parent: upload sales.csv + regions.csv, planner emits a
         two-file join plan → happy path.
      2. Follow-up: same two-file plan → must still succeed. If
         `extra_filenames` didn't survive on the session, the follow-up
         would 422 with a missing-file error because regions.csv isn't
         exposed to the executor anymore.
    """
    stub = _SequencedStubClient(
        [
            _multi_file_plan_json(),
            _narrative_json(title="华东领先", summary="华东 300，华南 50，差距明显。"),
            _multi_file_plan_json(),
            _narrative_json(title="增速对比", summary="华东增速高于其余地区。"),
        ]
    )
    monkeypatch.setattr(analyze_module, "HttpChatClient", lambda config: stub)
    monkeypatch.setattr(follow_up_module, "HttpChatClient", lambda config: stub)

    parent_resp = client.post(
        "/v1/analyze",
        files=[
            ("file", ("sales.csv", _csv_bytes(), "text/csv")),
            ("extra_files", ("regions.csv", _regions_csv_bytes(), "text/csv")),
        ],
        data={"question": "各地区的总销售额是多少？", "dataset": "regional-sales"},
    )
    assert parent_resp.status_code == 200, parent_resp.text
    parent_id = parent_resp.json()["id"]

    # Verify the session actually records the auxiliary filename —
    # failing here pinpoints the session-side regression before the
    # follow-up even runs.
    session = SESSION_STORE.get(parent_id)
    assert session is not None
    assert "regions.csv" in session.extra_filenames, (
        f"session.extra_filenames must include regions.csv; "
        f"got {session.extra_filenames!r}"
    )

    follow_resp = client.post(
        "/v1/follow-up",
        json={"parent_id": parent_id, "question": "他们的增速呢？"},
    )
    assert follow_resp.status_code == 200, (
        f"follow-up must succeed on a multi-file parent — a 422 here "
        f"means regions.csv was not forwarded to the follow-up's executor. "
        f"Body: {follow_resp.text}"
    )
    follow_body = follow_resp.json()
    assert follow_body["is_refusal"] is False
    # Findings must be present — if the join silently short-circuited
    # to the single-file path, the grouped aggregate on
    # `region_name` would have failed.
    assert follow_body["findings"]
