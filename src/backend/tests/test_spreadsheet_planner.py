"""Planner tests with a stub ChatClient — no real LLM call."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from app.spreadsheet.planner import (
    MAX_PLAN_RETRIES,
    PlannerError,
    PlanRequest,
    make_plan,
)


class StubClient:
    """Deterministic ChatClient — returns a queue of canned responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("StubClient ran out of responses")
        return self._responses.pop(0)


def _request() -> PlanRequest:
    return PlanRequest(
        question="按地区合计销售额",
        table_preview=pd.DataFrame({"region": ["华东"], "amount": [100]}),
        workspace_filename="sales.csv",
    )


@pytest.mark.asyncio
async def test_make_plan_happy_path() -> None:
    valid = json.dumps(
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
    client = StubClient([valid])
    plan = await make_plan(client, _request())
    assert len(plan.ops) == 4
    assert plan.ops[0].kind == "load_csv"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_make_plan_retries_on_invalid_json() -> None:
    valid = json.dumps(
        {
            "ops": [{"kind": "load_csv", "out": "raw", "path": "sales.csv"}],
            "answer": "raw",
        }
    )
    client = StubClient(["not json at all", valid])
    plan = await make_plan(client, _request())
    assert plan.ops[0].kind == "load_csv"
    assert len(client.calls) == 2
    # Second call must include the failure feedback so the model can self-correct.
    second_call_messages = client.calls[1]
    assert any("rejected" in m["content"] for m in second_call_messages)


@pytest.mark.asyncio
async def test_make_plan_gives_up_after_max_retries() -> None:
    bogus = json.dumps({"ops": [{"kind": "no_such_op", "out": "x"}]})
    client = StubClient([bogus] * (MAX_PLAN_RETRIES + 1))
    with pytest.raises(PlannerError):
        await make_plan(client, _request())
    assert len(client.calls) == MAX_PLAN_RETRIES + 1
