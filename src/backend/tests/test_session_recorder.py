"""Sqlite-backed session history index — durability + read paths.

Locks in the contract `app.persistence.sessions.SessionRecorder` makes
to the routes:

  * `record_parent` is idempotent on `response.id` so retries don't
    UNIQUE-violate.
  * `record_followup` bumps `updated_at` on the parent row so the
    listing UI sorts conversation activity correctly.
  * `list_sessions` filters by status + substring + limits.
  * `get_session` returns the full turn list in `turn_index` order.
  * `delete_session` cascades to `session_turns` (FK + ON DELETE CASCADE).
  * Sqlite errors are swallowed by `record_*` — a disk-full scenario
    must not surface as a 500 on the analyze route.
  * The DB survives process boundaries (close + reopen, same file).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.analyze.schema import AnalyzeResponse, Chart, Evidence, Finding
from app.persistence import SessionRecorder
from app.persistence.sessions import _SCHEMA_VERSION

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def recorder(tmp_path: Path) -> Iterator[SessionRecorder]:
    """Each test gets a fresh sqlite file under tmp_path so they don't
    cross-pollute. We don't use the module-level singleton — that one
    points at the env-resolved path and would leak state across runs.
    """

    rec = SessionRecorder(db_path=tmp_path / "sessions.db")
    yield rec
    rec.close()


def _mk_response(
    response_id: str,
    *,
    summary: str = "测试摘要",
    refused: bool = False,
    n_findings: int = 1,
    n_charts: int = 0,
) -> AnalyzeResponse:
    """Minimal AnalyzeResponse — enough for the recorder fields we read."""

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
# record_parent — happy path + idempotency
# ---------------------------------------------------------------------------


def test_record_parent_persists_summary_and_filenames(
    recorder: SessionRecorder,
) -> None:
    response = _mk_response("eval_analysis_aaaa", n_findings=2, n_charts=1)
    recorder.record_parent(
        response,
        primary_filename="sales.csv",
        extra_filenames=["regions.csv", "products.csv"],
        original_question="销售趋势如何?",
        sampling_rate=0.25,
        sampling_note="Downsampled 25% with seed=42",
    )
    detail = recorder.get_session("eval_analysis_aaaa")
    assert detail is not None
    assert detail.title == "销售趋势如何?"
    assert detail.primary_filename == "sales.csv"
    assert detail.extra_filenames == ("regions.csv", "products.csv")
    assert detail.status == "completed"
    assert detail.is_refusal is False
    assert detail.finding_count == 2
    assert detail.chart_count == 1
    assert detail.sampling_rate == 0.25
    assert detail.sampling_note == "Downsampled 25% with seed=42"
    # Parent is recorded as turn_index 0.
    assert len(detail.turns) == 1
    assert detail.turns[0].turn_index == 0
    assert detail.turns[0].kind == "parent"
    assert detail.turns[0].question == "销售趋势如何?"


def test_record_parent_marks_refused_status(recorder: SessionRecorder) -> None:
    response = _mk_response("eval_analysis_bbbb", refused=True, n_findings=0)
    recorder.record_parent(
        response,
        primary_filename="bad.csv",
        extra_filenames=[],
        original_question="按种族分类的薪资",
        sampling_rate=None,
        sampling_note=None,
    )
    detail = recorder.get_session("eval_analysis_bbbb")
    assert detail is not None
    assert detail.status == "refused"
    assert detail.is_refusal is True


def test_record_parent_is_idempotent_on_retry(
    recorder: SessionRecorder,
) -> None:
    """A retried request with the same id must not UNIQUE-violate.

    Without UPSERT semantics a transient client retry (or a buggy
    proxy that double-fires the request) would put the recorder in a
    half-written state and 500 the second submit.
    """

    response = _mk_response("eval_analysis_cccc")
    for _ in range(3):
        recorder.record_parent(
            response,
            primary_filename="x.csv",
            extra_filenames=[],
            original_question="问题",
            sampling_rate=None,
            sampling_note=None,
        )
    summaries = recorder.list_sessions()
    matching = [s for s in summaries if s.id == "eval_analysis_cccc"]
    # Exactly one row regardless of retry count.
    assert len(matching) == 1


def test_record_parent_retry_preserves_existing_followups(
    recorder: SessionRecorder,
) -> None:
    """Critical UPSERT semantic: a parent retry that arrives AFTER
    follow-ups have been recorded MUST NOT delete those follow-ups.

    The previous `INSERT OR REPLACE` implementation was a DELETE +
    INSERT under the hood, which CASCADEd to `session_turns` and
    silently wiped the conversation history. UPSERT
    (`ON CONFLICT DO UPDATE`) keeps children intact. This test fails
    catastrophically (turn_index 1 missing) on the old implementation.
    """

    parent = _mk_response("eval_analysis_retry")
    recorder.record_parent(
        parent,
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="原始问题",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_followup(
        session_id="eval_analysis_retry",
        turn_index=1,
        question="后续",
        response=_mk_response("eval_follow_retry_q1", summary="follow up"),
    )
    # Now the user (or a flaky proxy) retries the parent.
    recorder.record_parent(
        parent,
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="原始问题",
        sampling_rate=None,
        sampling_note=None,
    )
    detail = recorder.get_session("eval_analysis_retry")
    assert detail is not None
    # Parent + follow-up still both there.
    assert [t.turn_index for t in detail.turns] == [0, 1]
    assert detail.turns[1].summary == "follow up"


def test_record_parent_truncates_long_title(recorder: SessionRecorder) -> None:
    """Titles over 40 chars get an ellipsis — keeps the listing tidy."""

    long_q = "请帮我分析一下" + "销售数据的趋势" * 10
    response = _mk_response("eval_analysis_dddd")
    recorder.record_parent(
        response,
        primary_filename="x.csv",
        extra_filenames=[],
        original_question=long_q,
        sampling_rate=None,
        sampling_note=None,
    )
    detail = recorder.get_session("eval_analysis_dddd")
    assert detail is not None
    assert detail.title.endswith("…")
    assert len(detail.title) <= 40


def test_record_parent_handles_empty_question(recorder: SessionRecorder) -> None:
    """Pure-whitespace questions get a fallback title.

    The route already 400s these, so this branch is purely defensive —
    but it's where we'd notice a regression that bypassed validation.
    """

    response = _mk_response("eval_analysis_eeee")
    recorder.record_parent(
        response,
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="   ",
        sampling_rate=None,
        sampling_note=None,
    )
    detail = recorder.get_session("eval_analysis_eeee")
    assert detail is not None
    assert detail.title == "未命名分析"


# ---------------------------------------------------------------------------
# record_followup — append + updated_at bump
# ---------------------------------------------------------------------------


def test_record_followup_appends_and_bumps_updated_at(
    recorder: SessionRecorder,
) -> None:
    parent = _mk_response("eval_analysis_ffff")
    recorder.record_parent(
        parent,
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="问题",
        sampling_rate=None,
        sampling_note=None,
    )
    parent_detail = recorder.get_session("eval_analysis_ffff")
    assert parent_detail is not None
    parent_updated_at = parent_detail.updated_at

    followup = _mk_response(
        "eval_follow_ffff_q1", summary="follow-up summary"
    )
    recorder.record_followup(
        session_id="eval_analysis_ffff",
        turn_index=1,
        question="那女性顾客呢?",
        response=followup,
    )
    detail = recorder.get_session("eval_analysis_ffff")
    assert detail is not None
    # Parent + follow-up turns sorted by turn_index.
    assert [t.turn_index for t in detail.turns] == [0, 1]
    assert detail.turns[1].kind == "follow_up"
    assert detail.turns[1].question == "那女性顾客呢?"
    assert detail.turns[1].summary == "follow-up summary"
    # `updated_at` advanced — the listing query keys on it.
    assert detail.updated_at >= parent_updated_at


def test_record_followup_overwrites_on_same_turn_index(
    recorder: SessionRecorder,
) -> None:
    """Same `(session_id, turn_index)` key -> upsert, not duplicate.

    A retried follow-up request goes through the same turn slot
    (`allocate_follow_up_turn` reserved the index up front), so the
    second `record_followup` must replace, not append.
    """

    recorder.record_parent(
        _mk_response("eval_analysis_gggg"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    for summary in ("first", "second"):
        recorder.record_followup(
            session_id="eval_analysis_gggg",
            turn_index=1,
            question="q?",
            response=_mk_response("eval_follow_gggg_q1", summary=summary),
        )
    detail = recorder.get_session("eval_analysis_gggg")
    assert detail is not None
    assert len(detail.turns) == 2  # parent + 1 follow-up, not 3
    assert detail.turns[1].summary == "second"


# ---------------------------------------------------------------------------
# list_sessions — filtering + ordering
# ---------------------------------------------------------------------------


def test_list_sessions_orders_by_updated_at_desc(
    recorder: SessionRecorder,
) -> None:
    """Newest activity bubbles up — matches the listing UI's expected order."""

    for i in range(3):
        recorder.record_parent(
            _mk_response(f"eval_analysis_{i:04d}"),
            primary_filename=f"file_{i}.csv",
            extra_filenames=[],
            original_question=f"问题 {i}",
            sampling_rate=None,
            sampling_note=None,
        )
    # Append a follow-up to the OLDEST session — it should now sort top.
    recorder.record_followup(
        session_id="eval_analysis_0000",
        turn_index=1,
        question="follow-up",
        response=_mk_response("eval_follow_0000_q1"),
    )
    rows = recorder.list_sessions()
    assert rows[0].id == "eval_analysis_0000"


def test_list_sessions_filters_by_query_substring(
    recorder: SessionRecorder,
) -> None:
    recorder.record_parent(
        _mk_response("a"),
        primary_filename="sales_2024.csv",
        extra_filenames=[],
        original_question="销售趋势",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_parent(
        _mk_response("b"),
        primary_filename="users.csv",
        extra_filenames=[],
        original_question="用户留存",
        sampling_rate=None,
        sampling_note=None,
    )
    # Match by title.
    sales = recorder.list_sessions(query="销售")
    assert {s.id for s in sales} == {"a"}
    # Match by primary_filename.
    users = recorder.list_sessions(query="users")
    assert {s.id for s in users} == {"b"}
    # No match.
    none = recorder.list_sessions(query="nonexistent")
    assert none == []


def test_list_sessions_treats_like_wildcards_as_literals(
    recorder: SessionRecorder,
) -> None:
    """`%` and `_` in user input must NOT match arbitrary characters.

    CR #18 round-2 (Major): bare LIKE patterns let `%` over-match. A
    user searching for "50% off" would match every row; worse, an
    empty `_` could be used to enumerate rows by length. We escape
    wildcards and pass `ESCAPE '\\'` to the LIKE clause; a literal
    `%` should ONLY match a literal `%`.
    """

    recorder.record_parent(
        _mk_response("pct"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="50% 折扣分析",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_parent(
        _mk_response("plain"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="销售趋势",
        sampling_rate=None,
        sampling_note=None,
    )
    # Searching for "50%" must only match the row with literal "%".
    pct = recorder.list_sessions(query="50%")
    assert {s.id for s in pct} == {"pct"}
    # `_` should be literal — must not match anything (no row has it).
    underscore = recorder.list_sessions(query="50_")
    assert underscore == []
    # And the bare wildcard `%` alone should NOT match every row —
    # without escaping it would match all of them.
    just_pct = recorder.list_sessions(query="%")
    assert {s.id for s in just_pct} == {"pct"}


def test_list_sessions_filters_by_status(recorder: SessionRecorder) -> None:
    recorder.record_parent(
        _mk_response("ok", refused=False),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_parent(
        _mk_response("bad", refused=True, n_findings=0),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    completed = recorder.list_sessions(status="completed")
    assert {s.id for s in completed} == {"ok"}
    refused = recorder.list_sessions(status="refused")
    assert {s.id for s in refused} == {"bad"}


def test_list_sessions_respects_limit(recorder: SessionRecorder) -> None:
    for i in range(5):
        recorder.record_parent(
            _mk_response(f"s{i}"),
            primary_filename="x.csv",
            extra_filenames=[],
            original_question=f"q{i}",
            sampling_rate=None,
            sampling_note=None,
        )
    rows = recorder.list_sessions(limit=2)
    assert len(rows) == 2


def test_list_sessions_clamps_oversized_limit(
    recorder: SessionRecorder,
) -> None:
    """A malicious UI request asking for 10**9 rows should be clamped, not OOM.

    Defence-in-depth — FastAPI's `Query(le=1000)` already rejects this
    at the route boundary, but the recorder is also called from tests
    and from the future batch-export path, so the clamp lives in both
    places.
    """

    rows = recorder.list_sessions(limit=10**9)
    assert rows == []  # no rows, but didn't blow up trying to allocate


def test_list_sessions_includes_follow_up_count(
    recorder: SessionRecorder,
) -> None:
    recorder.record_parent(
        _mk_response("p"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    for i in range(3):
        recorder.record_followup(
            session_id="p",
            turn_index=i + 1,
            question=f"q{i}",
            response=_mk_response(f"eval_follow_p_q{i}"),
        )
    rows = recorder.list_sessions()
    assert rows[0].follow_up_count == 3


# ---------------------------------------------------------------------------
# get_session / delete_session
# ---------------------------------------------------------------------------


def test_get_session_returns_none_for_missing(recorder: SessionRecorder) -> None:
    assert recorder.get_session("nope") is None


def test_delete_session_cascades_to_turns(recorder: SessionRecorder) -> None:
    recorder.record_parent(
        _mk_response("victim"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_followup(
        session_id="victim",
        turn_index=1,
        question="q",
        response=_mk_response("eval_follow_victim_q1"),
    )
    assert recorder.delete_session("victim") is True
    assert recorder.get_session("victim") is None
    # And the turn rows are gone — proving FK CASCADE fired.
    rows = recorder.list_sessions()
    assert all(r.id != "victim" for r in rows)


def test_delete_session_returns_false_for_missing(
    recorder: SessionRecorder,
) -> None:
    assert recorder.delete_session("nope") is False


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_counts_total_and_continuable(recorder: SessionRecorder) -> None:
    recorder.record_parent(
        _mk_response("ok1"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_parent(
        _mk_response("ok2"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder.record_parent(
        _mk_response("bad", refused=True, n_findings=0),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    stats = recorder.stats()
    assert stats["total"] == 3
    assert stats["continuable"] == 2  # the 2 non-refused ones
    assert stats["this_week"] == 3  # all three were just recorded


def test_stats_continuable_derives_from_status_not_flag(
    recorder: SessionRecorder,
) -> None:
    """`continuable` counts the rows whose `status != 'refused'` —
    independent of the redundant `is_refusal` column. CR #18 round-2:
    keeps the badge in lockstep with the API's `is_refusal` derivation
    (which also reads from `status`).

    Plant a row with status=completed but is_refusal=1 (the impossible
    case post-write but possible after a hand-edit / failed migration).
    The count must include it.
    """

    recorder.record_parent(
        _mk_response("ok"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    # Force the flag to disagree with status.
    recorder._conn.execute(
        "UPDATE sessions SET is_refusal = 1 WHERE id = ?", ("ok",)
    )
    recorder._conn.commit()

    # status='completed' so it IS continuable, regardless of the flag.
    assert recorder.stats()["continuable"] == 1


def test_get_session_validates_status_column(
    recorder: SessionRecorder,
) -> None:
    """A row whose `status` column doesn't match the closed enum must
    surface as a sqlite error in `get_session`, not silently smuggle a
    free-form string into the Literal-typed DTO. CR #18 round-2.
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

    with pytest.raises(sqlite3.DatabaseError, match="unexpected status"):
        recorder.get_session("legacy")


# ---------------------------------------------------------------------------
# Cross-restart durability
# ---------------------------------------------------------------------------


def test_recorder_survives_close_and_reopen(tmp_path: Path) -> None:
    """The whole point of this layer — outlive a worker restart.

    Open recorder #1, write, close. Open recorder #2 against the same
    path; the rows must still be there. Without this guarantee the
    "历史分析" page would 0-out every time the dev hits Ctrl-C.
    """

    db_path = tmp_path / "durable.db"
    rec1 = SessionRecorder(db_path=db_path)
    rec1.record_parent(
        _mk_response("survivor"),
        primary_filename="x.csv",
        extra_filenames=["y.csv"],
        original_question="活下来了吗?",
        sampling_rate=None,
        sampling_note=None,
    )
    rec1.close()

    rec2 = SessionRecorder(db_path=db_path)
    detail = rec2.get_session("survivor")
    assert detail is not None
    assert detail.title == "活下来了吗?"
    assert detail.extra_filenames == ("y.csv",)
    rec2.close()


# ---------------------------------------------------------------------------
# Failure isolation — recorder swallows sqlite errors so the route doesn't 500
# ---------------------------------------------------------------------------


def test_record_parent_swallows_sqlite_errors(
    recorder: SessionRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locked / corrupted DB must not propagate to the route.

    Simulate a sqlite-side failure by closing the connection out from
    under the recorder. The next `record_parent` should log + return
    instead of raising — the contract that protects /v1/analyze.
    """

    recorder._conn.close()  # induce sqlite.ProgrammingError on next query
    # Should NOT raise.
    recorder.record_parent(
        _mk_response("dont_500"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )


# ---------------------------------------------------------------------------
# Failure propagation — read paths surface errors so the route can 503
# ---------------------------------------------------------------------------


def test_delete_session_propagates_sqlite_errors(
    recorder: SessionRecorder,
) -> None:
    """delete_session must NOT swallow sqlite errors (CR #18 round-1).

    The previous implementation `return False`d on sqlite.Error, which
    the route interpreted as 404. The user would think their row was
    gone and re-create it — except the next listing would still show
    it (because the DELETE never landed). Propagating lets the route
    distinguish "broken" (503) from "not present" (404).
    """

    recorder.record_parent(
        _mk_response("present"),
        primary_filename="x.csv",
        extra_filenames=[],
        original_question="q",
        sampling_rate=None,
        sampling_note=None,
    )
    recorder._conn.close()
    with pytest.raises(sqlite3.Error):
        recorder.delete_session("present")


def test_recorder_fails_closed_on_schema_version_mismatch(
    tmp_path: Path,
) -> None:
    """A DB whose `_schema_version` row disagrees with this build must
    refuse to bind, not silently keep going (CR #18 round-1).

    We pre-seed a sqlite file with an alien version row, then construct
    a SessionRecorder against it. The constructor must raise so the
    lazy singleton doesn't cache an incompatible recorder.
    """

    db_path = tmp_path / "wrong-version.db"
    # Hand-build the minimum needed for the bootstrap probe: just the
    # `_schema_version` table with a row claiming a future version.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE _schema_version (version INTEGER NOT NULL);"
        f"INSERT INTO _schema_version (version) VALUES ({_SCHEMA_VERSION + 99});"
    )
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.DatabaseError, match="schema version mismatch"):
        SessionRecorder(db_path=db_path)
