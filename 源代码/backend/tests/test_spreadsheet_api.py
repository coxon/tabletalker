"""End-to-end API tests for POST /spreadsheet/analyze.

We monkeypatch the LLM client with a stub so tests don't hit the
network. The HTTP client is replaced via `app.api.spreadsheet`'s module
namespace.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.spreadsheet as api_module
from app.main import app


class _StubClient:
    def __init__(self, response_json: str) -> None:
        self._response = response_json

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        return self._response


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Required by LLMConfig.from_env(). Values are placeholders since the
    # stub never reads them — but they must be set for config to load.
    monkeypatch.setenv("LLM_BASE_URL", "https://stub.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    return TestClient(app)


def _csv_bytes() -> bytes:
    return b"region,amount\nE,100\nE,200\nS,50\n"


def _stub_plan() -> str:
    return json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "data.csv"},
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


def test_analyze_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubClient(_stub_plan())
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/spreadsheet/analyze",
        files={"file": ("data.csv", _csv_bytes(), "text/csv")},
        data={"question": "总销售额按地区"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["type"] == "table"
    rows = body["result"]["rows"]
    e_total = next(r for r in rows if r["region"] == "E")["total"]
    assert e_total == 300
    assert len(body["verses"]) == 4
    assert body["verses"][0]["verb"] == "load"


def test_analyze_rejects_empty_question(client: TestClient) -> None:
    response = client.post(
        "/spreadsheet/analyze",
        files={"file": ("data.csv", _csv_bytes(), "text/csv")},
        data={"question": "   "},
    )
    assert response.status_code == 400


def test_analyze_rejects_unsupported_extension(client: TestClient) -> None:
    response = client.post(
        "/spreadsheet/analyze",
        files={"file": ("data.txt", b"hello", "text/plain")},
        data={"question": "anything"},
    )
    assert response.status_code == 415


def test_analyze_propagates_op_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_plan = json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "data.csv"},
                {"kind": "sort", "out": "s", "src": "raw", "by": ["NOT_A_COL"]},
                {"kind": "to_table", "out": "answer", "src": "s"},
            ],
            "answer": "answer",
        }
    )
    monkeypatch.setattr(
        api_module, "HttpChatClient", lambda config: _StubClient(bad_plan)
    )
    response = client.post(
        "/spreadsheet/analyze",
        files={"file": ("data.csv", _csv_bytes(), "text/csv")},
        data={"question": "anything"},
    )
    assert response.status_code == 422
    # The response message is sanitised — it identifies the failing step
    # and op kind without leaking the underlying exception text. The detailed
    # cause (`'NOT_A_COL'`) is logged server-side, not returned to the client.
    # Step number is 1-based and aligns with `verses[n].n` shown in the trace —
    # the failing `sort` op is the 2nd op in the plan, so step 2.
    detail = response.json()["detail"]
    assert "step 2" in detail
    assert "sort" in detail


def test_analyze_413_on_oversized_upload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Shrink the cap for the test so we don't have to ship a 20 MiB blob.
    monkeypatch.setattr(api_module, "MAX_UPLOAD_BYTES", 64)
    payload = io.BytesIO(b"region,amount\n" + b"E,100\n" * 20)  # > 64 bytes
    response = client.post(
        "/spreadsheet/analyze",
        files={"file": ("big.csv", payload.getvalue(), "text/csv")},
        data={"question": "anything"},
    )
    assert response.status_code == 413
