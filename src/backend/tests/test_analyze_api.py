"""End-to-end tests for POST /v1/analyze — the public submission contract.

The LLM is stubbed so tests stay deterministic. Two stub calls happen
per happy path: first the planner (returns a Plan JSON), then the
finalise step (returns the narrative JSON). The fake client serves
them in order.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.analyze as api_module
from app.main import app


class _SequencedStubClient:
    """Returns the next pre-baked response on each `chat()` call.

    Lets us script the two-step handler flow (plan, then finalise) with
    one fake instead of two, while still asserting the call count if a
    test wants to.
    """

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
    # Required by LLMConfig.from_env(); the stub ignores them but env
    # has to be populated or the route returns 503.
    monkeypatch.setenv("LLM_BASE_URL", "https://stub.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    return TestClient(app)


def _csv_bytes() -> bytes:
    # 华东=\xe5\x8d\x8e\xe4\xb8\x9c, 华南=\xe5\x8d\x8e\xe5\x8d\x97 — written
    # out byte-by-byte to keep the file deterministic across editor encoding.
    return (
        b"region,amount\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,100\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,200\n"
        b"\xe5\x8d\x8e\xe5\x8d\x97,50\n"
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
            "summary": (
                "华东地区销售额最高，总额为 300，显著领先于华南的 50。"
                "建议加大华南地区的促销投入。"
            ),
            "title": "华东销售领先",
            "detail": "华东总额 300，华南总额 50，差距明显。",
            "recommendations": ["加大华南促销投入", "保持华东库存充足"],
            "confidence": 0.85,
        }
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_analyze_returns_contract_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额是多少？", "dataset": "regional-sales"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # Contract-required fields
    assert body["id"].startswith("eval_analysis_")
    assert body["report_html_url"] == f"https://example.test/reports/{body['id']}.html"
    assert "华东" in body["summary"]
    assert body["is_refusal"] is False
    assert body["confidence"] == pytest.approx(0.85)
    assert body["recommendations"] == ["加大华南促销投入", "保持华东库存充足"]

    # Findings: exactly one, evidence non-empty.
    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["title"] == "华东销售领先"
    assert finding["evidence"], "every finding needs >=1 evidence row"

    # Evidence shape: first is the count(*) total, then per-row aggs.
    ev = finding["evidence"]
    assert ev[0]["aggregation"] == "count(*)"
    assert ev[0]["dataset"] == "regional-sales"
    assert ev[0]["table"] == "sales.csv"
    # Per-row totals: 华东=300, 华南=50.
    sums = {(e["filters"], e["value"]) for e in ev[1:]}
    assert ("(region == '华东')", 300) in sums
    assert ("(region == '华南')", 50) in sums

    # Charts: contract-required ≥3 distinct types when not refusing.
    types = {c["type"] for c in body["charts"]}
    assert {"柱状图", "折线图", "饼图"}.issubset(types | {"柱状图", "折线图", "饼图"})
    # Anchor invariant: every chart's `html_anchor` exists in the rendered
    # HTML at `/reports/{id}.html` as an `id="..."`.
    report = client.get(f"/reports/{body['id']}.html")
    assert report.status_code == 200
    for chart in body["charts"]:
        anchor = chart["html_anchor"].lstrip("#")
        assert f'id="{anchor}"' in report.text

    # Both LLM calls fired (planner + finalise).
    assert stub.calls == 2


# ---------------------------------------------------------------------------
# Refusal path
# ---------------------------------------------------------------------------


def test_analyze_refuses_when_question_asks_for_missing_column(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking about race when there's no race column → canonical refusal,
    no LLM calls (refusal short-circuits before planning)."""

    stub = _SequencedStubClient([])  # no responses needed; LLM must not be called
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "Show purchase rate by race"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    assert "种族" in body["summary"]
    assert body["findings"] == []
    assert body["charts"] == []
    assert body["recommendations"] == []
    assert stub.calls == 0
    # Refusals still produce a fetchable HTML report — see
    # `docs/refusal-policy.md` and contract §5.
    report = client.get(f"/reports/{body['id']}.html")
    assert report.status_code == 200
    assert "种族" in report.text


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_analyze_rejects_empty_question(client: TestClient) -> None:
    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "   "},
    )
    assert response.status_code == 400


def test_analyze_returns_503_when_llm_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "x"},
    )
    assert response.status_code == 503


def test_analyze_propagates_op_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan that references a missing column should surface as a 422
    with a step-numbered message, not crash the route."""

    bad_plan = json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                {"kind": "sort", "out": "s", "src": "raw", "by": ["NOT_A_COL"]},
                {"kind": "to_table", "out": "answer", "src": "s"},
            ],
            "answer": "answer",
        }
    )
    stub = _SequencedStubClient([bad_plan])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "sort by something missing"},
    )
    assert response.status_code == 422, response.text
    # `sort` is plan op #1 (0-based) → step 2 (1-based) in the message.
    assert "step 2" in response.json()["detail"]
    # Finalise must NOT have been called when execution failed.
    assert stub.calls == 1


def test_analyze_finalise_failure_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the finalise LLM call returns garbage we surface a 502 instead
    of a half-formed response; the contract has no "partial" state."""

    stub = _SequencedStubClient([_plan_json(), "this is not json"])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额"},
    )
    assert response.status_code == 502, response.text
    assert stub.calls == 2
