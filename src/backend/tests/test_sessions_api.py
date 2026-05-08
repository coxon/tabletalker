"""HTTP-level tests for `/v1/sessions` (list / detail / delete).

Exercises the full Pydantic round-trip via FastAPI's TestClient so a
field rename in `app.api.sessions` immediately surfaces as a wire-shape
diff. The recorder is stubbed via `set_session_recorder()` to a
tmp_path-scoped instance so tests don't share state.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analyze.schema import AnalyzeResponse, Chart, Evidence, Finding
from app.main import app
from app.persistence import SessionRecorder, set_session_recorder

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def recorder(tmp_path: Path) -> Iterator[SessionRecorder]:
    """Swap the module singleton for a tmp-path-scoped recorder.

    Tests run in arbitrary order via pytest-xdist in CI; sharing the
    real `SESSION_RECORDER` (which points at `./data/sessions.db`)
    would let tests see each other's rows. The fixture restores the
    pre-test singleton state on teardown so the API's own boot path
    isn't poisoned for subsequent suites.
    """

    rec = SessionRecorder(db_path=tmp_path / "sessions.db")
    set_session_recorder(rec)
    yield rec
    set_session_recorder(None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _mk_response(
    response_id: str,
    *,
    summary: str = "测试摘要",
    refused: bool = False,
    n_findings: int = 1,
    n_charts: int = 0,
) -> AnalyzeResponse:
    findings = [
        Finding(
            title=f"finding {i}",
            detail="detail",
            evidence=[
                Evidence(
                    dataset="ds",
                    table="t.csv",
                    columns=["a"],
                    filters="",
                    aggregation="count(*)",
                    value=1,
                )
            ],
        )
        for i in range(n_findings)
    ]
    charts = [
        Chart(type="柱状图", title=f"chart {i}", html_anchor=f"#chart-{i}")
        for i in range(n_charts)
    ]
    return AnalyzeResponse(
        id=response_id,
        report_html_url=f"https://example.com/reports/{response_id}.html",
        summary=summary,
        findings=findings,
        charts=charts,
        recommendations=[],
        is_refusal=refused,
    )


# ---------------------------------------------------------------------------
# GET /v1/sessions — listing
# ---------------------------------------------------------------------------


def test_list_sessions_returns_empty_with_zeroed_stats(
    client: TestClient, recorder: SessionRecorder
) -> None:
    r = client.get("/v1/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "stats": {"total": 0, "this_week": 0, "continuable": 0},
        "items": [],
    }


def test_list_sessions_returns_recorded_rows(
    client: TestClient, recorder: SessionRecorder
) -> None:
    recorder.record_parent(
        _mk_response("alpha", n_findings=2, n_charts=1),
        primary_filename="sales.csv",
        extra_filenames=["regions.csv"],
        original_question="销售趋势如何?",
        sampling_rate=0.5,
        sampling_note="50% sample",
    )
    r = client.get("/v1/sessions")
    body = r.json()
    assert body["stats"]["total"] == 1
    assert body["stats"]["continuable"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == "alpha"
    assert item["title"] == "销售趋势如何?"
    assert item["primary_filename"] == "sales.csv"
    assert item["extra_filenames"] == ["regions.csv"]
    assert item["status"] == "completed"
    assert item["is_refusal"] is False
    assert item["finding_count"] == 2
    assert item["chart_count"] == 1
    assert item["follow_up_count"] == 0


def test_list_sessions_filters_by_q_and_status(
    client: TestClient, recorder: SessionRecorder
) -> None:
    recorder.record_parent(
        _mk_response("ok"),
        primary_filename="ok.csv",
        extra_filenames=[],
        original_question="销售",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_parent(
        _mk_response("bad", refused=True, n_findings=0),
        primary_filename="bad.csv",
        extra_filenames=[],
        original_question="销售也搜不到",
        sampling_rate=None,
        sampling_note=None,
    )
    # query filter
    r = client.get("/v1/sessions", params={"q": "ok"})
    assert {item["id"] for item in r.json()["items"]} == {"ok"}
    # status filter
    r2 = client.get("/v1/sessions", params={"status": "refused"})
    assert {item["id"] for item in r2.json()["items"]} == {"bad"}


def test_list_sessions_rejects_invalid_status(
    client: TestClient, recorder: SessionRecorder
) -> None:
    """Literal validation guards against typos like `?status=Completed`."""

    r = client.get("/v1/sessions", params={"status": "in_progress"})
    assert r.status_code == 422


@pytest.mark.parametrize("limit", [0, 1001])
def test_list_sessions_rejects_out_of_range_limit(
    client: TestClient, recorder: SessionRecorder, limit: int
) -> None:
    """`limit` is guarded by Pydantic at the route boundary.

    The recorder also clamps internally (defence-in-depth) but the wire
    contract is that the route 422s rather than silently coerces.
    """

    r = client.get("/v1/sessions", params={"limit": limit})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/sessions/{id} — detail
# ---------------------------------------------------------------------------


def test_get_session_returns_full_detail(
    client: TestClient, recorder: SessionRecorder
) -> None:
    recorder.record_parent(
        _mk_response("detailed"),
        primary_filename="x.csv",
        extra_filenames=["y.csv"],
        original_question="问题",
        sampling_rate=0.25,
        sampling_note="25% sample",
    )
    recorder.record_followup(
        session_id="detailed",
        turn_index=1,
        question="后续",
        response=_mk_response("eval_follow_detailed_q1", summary="follow up"),
    )
    r = client.get("/v1/sessions/detailed")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "detailed"
    assert body["sampling_rate"] == 0.25
    assert body["sampling_note"] == "25% sample"
    assert body["report_html_url"].endswith("/detailed.html")
    assert [t["turn_index"] for t in body["turns"]] == [0, 1]
    assert body["turns"][0]["kind"] == "parent"
    assert body["turns"][1]["kind"] == "follow_up"
    assert body["turns"][1]["summary"] == "follow up"


def test_get_session_returns_404_for_missing(
    client: TestClient, recorder: SessionRecorder
) -> None:
    r = client.get("/v1/sessions/missing")
    assert r.status_code == 404
    assert "missing" in r.json()["detail"]


# ---------------------------------------------------------------------------
# DELETE /v1/sessions/{id}
# ---------------------------------------------------------------------------


def test_delete_session_removes_row(
    client: TestClient, recorder: SessionRecorder
) -> None:
    recorder.record_parent(
        _mk_response("doomed"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    r = client.delete("/v1/sessions/doomed")
    assert r.status_code == 204
    # Subsequent fetch is 404.
    assert client.get("/v1/sessions/doomed").status_code == 404
    # Listing no longer includes it.
    assert client.get("/v1/sessions").json()["items"] == []


def test_delete_session_returns_404_when_missing(
    client: TestClient, recorder: SessionRecorder
) -> None:
    r = client.delete("/v1/sessions/never_existed")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 503 on persistence failure (CR #18 round-1)
# ---------------------------------------------------------------------------
#
# A broken/locked sqlite store must surface as 503 — not 500 (which the
# UI would render as a generic "something went wrong"), and not 404
# (which would tell the user their data is gone). Three routes, three
# tests, one shared sabotage trick: close the recorder's connection out
# from under it so every subsequent call raises sqlite.ProgrammingError.


def _break_recorder(rec: SessionRecorder) -> None:
    """Force every subsequent recorder call to raise sqlite.Error.

    Closing the connection is enough — sqlite raises
    `ProgrammingError` (subclass of `sqlite3.Error`) on any operation
    after `close()`, which is what our route's `except sqlite3.Error`
    catches.
    """

    rec._conn.close()


def test_list_sessions_returns_503_on_db_error(
    client: TestClient, recorder: SessionRecorder
) -> None:
    _break_recorder(recorder)
    r = client.get("/v1/sessions")
    assert r.status_code == 503
    assert r.json()["detail"] == "Session history temporarily unavailable"


def test_get_session_returns_503_on_db_error(
    client: TestClient, recorder: SessionRecorder
) -> None:
    _break_recorder(recorder)
    r = client.get("/v1/sessions/anything")
    assert r.status_code == 503


def test_delete_session_returns_503_on_db_error(
    client: TestClient, recorder: SessionRecorder
) -> None:
    """Critical: a broken DB must not collapse to 404 on delete.

    Pre-fix, delete_session swallowed sqlite errors and returned False,
    which the route translated to 404 — telling the user "this session
    is already gone" while in reality the row was still there. Now the
    error propagates and the route returns 503.
    """

    recorder.record_parent(
        _mk_response("real"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    _break_recorder(recorder)
    r = client.delete("/v1/sessions/real")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# CR #18 round-1: is_refusal is derived from status — they cannot diverge
# ---------------------------------------------------------------------------


def test_summary_is_refusal_is_derived_from_status(
    client: TestClient, recorder: SessionRecorder, tmp_path: Path
) -> None:
    """Even if the DB stores an inconsistent is_refusal flag, the wire
    response derives `is_refusal` from `status`. This guards against a
    future migration that adds a status value but forgets to update the
    flag column.
    """

    # Sneak an inconsistent row past the recorder by writing directly:
    # status=refused but is_refusal=0 (the wrong value if read raw).
    recorder.record_parent(
        _mk_response("inconsistent", refused=True, n_findings=0),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    # Force the underlying flag to disagree with status.
    recorder._conn.execute(
        "UPDATE sessions SET is_refusal = 0 WHERE id = ?", ("inconsistent",)
    )
    recorder._conn.commit()

    body = client.get("/v1/sessions").json()
    [item] = body["items"]
    assert item["status"] == "refused"
    # API derives this — the raw column was 0 but status wins.
    assert item["is_refusal"] is True


def test_corrupted_status_value_returns_503(
    client: TestClient, recorder: SessionRecorder
) -> None:
    """A row containing a status value outside the closed Literal set
    must surface as 503, not silently slip through as a free-form string.

    The DB column is plain TEXT (sqlite has no enum type), so a future
    schema or hand-edit could plant 'in_progress'. The recorder's
    coerce helpers raise `sqlite3.DatabaseError`, which the route maps
    to 503.
    """

    recorder.record_parent(
        _mk_response("legacy"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder._conn.execute(
        "UPDATE sessions SET status = 'in_progress' WHERE id = ?", ("legacy",)
    )
    recorder._conn.commit()

    r = client.get("/v1/sessions")
    assert r.status_code == 503
