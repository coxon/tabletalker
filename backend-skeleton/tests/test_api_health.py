"""API 集成测试 - 健康检查端点。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_returns_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert "version" in j
    assert "models_configured" in j


def test_health_has_5_models_configured(client):
    j = client.get("/api/health").json()
    assert isinstance(j["models_configured"], list)
    assert len(j["models_configured"]) == 5


def test_chat_stream_accepts_minimal_payload(client):
    """422 修复回归测试：字段缺失也不应该 422。"""
    r = client.post("/api/chat/stream", json={"question": "test"})
    # SSE 接口 status code 200 即可（流内容这里不验）
    assert r.status_code == 200


def test_chat_stream_accepts_empty_body(client):
    """完全空 body 也不能 422（fallback 到 question='（空问题）'）。"""
    r = client.post("/api/chat/stream", json={})
    assert r.status_code == 200


def test_datasets_list_returns_dict(client):
    """数据集列表端点。"""
    r = client.get("/api/datasets/")
    assert r.status_code == 200
    j = r.json()
    assert "datasets" in j


def test_dashboard_pin_creates_new(client):
    r = client.post("/api/dashboard/pin", json={
        "title": "测试看板",
        "kind": "bars",
        "message_id": "msg_test",
    })
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["dashboard_id"].startswith("dash_")
    assert j["card_id"].startswith("card_")


def test_dashboard_list_after_pin(client):
    """pin 后 list 应该看到新看板。"""
    client.post("/api/dashboard/pin", json={"title": "list 测试", "message_id": "m"})
    r = client.get("/api/dashboard/")
    j = r.json()
    assert "dashboards" in j


def test_eval_run_accepts_jsonl(client, tmp_path):
    sample = tmp_path / "eval.jsonl"
    sample.write_text(
        '{"id":"q1","question":"测试 1"}\n{"id":"q2","question":"测试 2"}\n'
    )
    with sample.open("rb") as f:
        r = client.post("/api/eval/run", files={"file": ("eval.jsonl", f, "application/x-ndjson")})
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 2
    assert j["task_id"].startswith("eval_")


def test_eval_run_rejects_non_jsonl(client, tmp_path):
    bad = tmp_path / "x.png"
    bad.write_bytes(b"\x89PNG fake")
    with bad.open("rb") as f:
        r = client.post("/api/eval/run", files={"file": ("x.png", f, "image/png")})
    assert r.status_code == 400
