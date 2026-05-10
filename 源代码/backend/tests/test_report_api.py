"""GET /reports/{id}.html route smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.report import REPORT_STORE


def test_returns_stored_html() -> None:
    REPORT_STORE.put("eval_api_001", "<!doctype html><html><body>ok</body></html>")
    try:
        with TestClient(app) as client:
            resp = client.get("/reports/eval_api_001.html")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers.get("cache-control") == "no-store"
        assert "<body>ok</body>" in resp.text
    finally:
        REPORT_STORE.clear()


def test_unknown_id_returns_404() -> None:
    REPORT_STORE.clear()
    with TestClient(app) as client:
        resp = client.get("/reports/eval_api_missing.html")
    assert resp.status_code == 404


def test_store_evicts_oldest_at_cap() -> None:
    """Tiny `max_entries` proxy for the FIFO behaviour. The store must
    evict the oldest entry, never the newest the grader is fetching."""

    from app.report.store import ReportStore

    s = ReportStore(max_entries=2)
    s.put("a", "1")
    s.put("b", "2")
    s.put("c", "3")  # evicts "a"

    assert s.get("a") is None
    assert s.get("b") == "2"
    assert s.get("c") == "3"

def test_store_rejects_non_positive_max_entries() -> None:
    """A zero / negative cap would let `_items` grow then trip a KeyError
    on the very first put — fail-fast at construction time instead."""

    import pytest

    from app.report.store import ReportStore

    with pytest.raises(ValueError):
        ReportStore(max_entries=0)
    with pytest.raises(ValueError):
        ReportStore(max_entries=-1)
