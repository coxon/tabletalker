"""Smoke tests for the FastAPI skeleton."""

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_version() -> None:
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "tabletalker-backend"
    assert body["version"] == __version__
