"""GET/DELETE /v1/sessions — durable analysis history.

Consumed by the "历史分析" page in the frontend. Reads from the sqlite
index maintained by `app.persistence.sessions.SESSION_RECORDER`; no
interaction with the in-memory `SESSION_STORE` (which covers only the
last 24 h and only this worker's memory).

The response shapes are separate Pydantic models — NOT the
submission-contract ones from `app.analyze.schema`. That module is
frozen by the external grader; history is our internal UI and wants
different fields (title, updated_at, follow_up_count). Keeping them in
separate files means a grader-facing schema change never silently
reshapes the history page, and vice versa.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.persistence import (
    SessionDetail,
    SessionSummary,
    SessionTurnRecord,
    get_session_recorder,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["sessions"])

# CR #18 round-1 (Major): a sqlite-side failure (locked DB, schema
# mismatch, disk-full read) must surface as a 503 — not a generic 500
# with a stack trace, and not a 404 (which would tell the UI "this
# session no longer exists" and risk users deleting their workspace
# expecting a re-create). One detail string keeps the wire surface
# uniform across all three routes.
_HISTORY_UNAVAILABLE = "Session history temporarily unavailable"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    """Reject unknown fields so schema drift surfaces at serialize time."""

    model_config = ConfigDict(extra="forbid")


class SessionStatsOut(_StrictModel):
    """Aggregate badges for the history page's three stat cards."""

    total: int = Field(..., description="All sessions stored.")
    this_week: int = Field(..., description="Sessions created in last 7 days.")
    continuable: int = Field(
        ...,
        description="Non-refused sessions — user can productively ask more.",
    )


class SessionSummaryOut(_StrictModel):
    """List-row shape — matches the history sidebar card.

    Timestamps are ISO-8601-ish floats (unix epoch seconds) rather than
    strings; the frontend formats them with `dayjs` + the locale, so
    pushing a pre-formatted string here would force server-side locale
    handling we don't need.
    """

    id: str
    title: str
    primary_filename: str
    extra_filenames: list[str]
    created_at: float
    updated_at: float
    status: Literal["completed", "refused"]
    is_refusal: bool
    follow_up_count: int
    chart_count: int
    finding_count: int


class SessionTurnOut(_StrictModel):
    """One turn for the detail panel's conversation preview."""

    turn_index: int
    kind: Literal["parent", "follow_up"]
    question: str
    response_id: str
    is_refusal: bool
    summary: str
    finding_count: int
    chart_count: int
    created_at: float


class SessionDetailOut(_StrictModel):
    """Detail panel shape — summary fields plus every turn."""

    id: str
    title: str
    primary_filename: str
    extra_filenames: list[str]
    created_at: float
    updated_at: float
    status: Literal["completed", "refused"]
    is_refusal: bool
    chart_count: int
    finding_count: int
    report_html_url: str
    sampling_rate: float | None
    sampling_note: str | None
    turns: list[SessionTurnOut]


class SessionListOut(_StrictModel):
    """Top-level list response: stats card data + the rows themselves."""

    stats: SessionStatsOut
    items: list[SessionSummaryOut]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=SessionListOut)
def list_sessions(
    q: str | None = Query(
        default=None,
        description="Case-insensitive substring match against title + filename.",
    ),
    status_filter: Literal["completed", "refused"] | None = Query(
        default=None,
        alias="status",
        description="Optional status filter.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Max rows to return; UI pages client-side up to this cap.",
    ),
) -> SessionListOut:
    """Return the session index plus the badge stats in one roundtrip.

    Two queries are cheap on sqlite (the `updated_at` index makes the
    listing an O(limit) scan) and saving a network round-trip matters
    when the history page mounts — the UI otherwise flashes "0 analyses"
    before the stats resolve.

    Persistence errors are translated to 503; we deliberately do **not**
    fall back to an empty list because that would let a corrupted DB
    masquerade as "no history yet" and trick the user into starting
    fresh analyses against the same broken store.
    """

    try:
        recorder = get_session_recorder()
        rows = recorder.list_sessions(query=q, status=status_filter, limit=limit)
        stats = recorder.stats()
    except sqlite3.Error:
        logger.exception("session recorder unavailable on list_sessions")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _HISTORY_UNAVAILABLE
        ) from None
    return SessionListOut(
        stats=SessionStatsOut(**stats),
        items=[_summary_to_out(r) for r in rows],
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
def get_session(session_id: str) -> SessionDetailOut:
    """Fetch a single session with its full turn history.

    Returns 404 when the id is unknown — the history list is the source
    of truth for what's fetchable, so a missing id means the user
    either deleted it or is following a stale deep-link. A read error
    (corrupted row, locked file) yields 503 instead, so the UI can
    distinguish "gone" from "currently broken".
    """

    try:
        detail = get_session_recorder().get_session(session_id)
    except sqlite3.Error:
        logger.exception(
            "session recorder unavailable on get_session %s", session_id
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _HISTORY_UNAVAILABLE
        ) from None
    if detail is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"session {session_id!r} not found",
        )
    return _detail_to_out(detail)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str) -> None:
    """Remove a session + its turns from the durable index.

    The in-memory `SESSION_STORE` entry (if any) is deliberately left
    alone: an in-flight follow-up against `session_id` should complete
    against its workspace rather than break mid-response because the
    history UI removed the card. TTL will reap it on schedule.

    A sqlite error here is **not** collapsed into 404 (CR #18 round-1):
    the recorder used to swallow the error and return False, which the
    route would then translate to "not found", silently lying to the
    user. Now the recorder propagates and we 503 — preserving 404's
    meaning of "genuinely absent".
    """

    try:
        removed = get_session_recorder().delete_session(session_id)
    except sqlite3.Error:
        logger.exception(
            "session recorder unavailable on delete_session %s", session_id
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _HISTORY_UNAVAILABLE
        ) from None
    if not removed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"session {session_id!r} not found",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summary_to_out(row: SessionSummary) -> SessionSummaryOut:
    # CR #18 round-1 (Trivial): `is_refusal` is kept on the wire shape
    # because clients use it directly in iconography conditions, but
    # it's *derived* from `status` here rather than read from the
    # recorder field. That keeps the two from drifting if a future
    # writer forgets to set them in lock-step (e.g. a migration that
    # adds a new status value but doesn't update is_refusal).
    return SessionSummaryOut(
        id=row.id,
        title=row.title,
        primary_filename=row.primary_filename,
        extra_filenames=list(row.extra_filenames),
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=row.status,
        is_refusal=row.status == "refused",
        follow_up_count=row.follow_up_count,
        chart_count=row.chart_count,
        finding_count=row.finding_count,
    )


def _detail_to_out(detail: SessionDetail) -> SessionDetailOut:
    # Same derive-from-status rule as `_summary_to_out`. Turn-level
    # `is_refusal` *is* read directly from the per-turn record because
    # turns don't carry their own status — refusal is a property of
    # the response payload, not of the conversation row.
    return SessionDetailOut(
        id=detail.id,
        title=detail.title,
        primary_filename=detail.primary_filename,
        extra_filenames=list(detail.extra_filenames),
        created_at=detail.created_at,
        updated_at=detail.updated_at,
        status=detail.status,
        is_refusal=detail.status == "refused",
        chart_count=detail.chart_count,
        finding_count=detail.finding_count,
        report_html_url=detail.report_html_url,
        sampling_rate=detail.sampling_rate,
        sampling_note=detail.sampling_note,
        turns=[_turn_to_out(t) for t in detail.turns],
    )


def _turn_to_out(turn: SessionTurnRecord) -> SessionTurnOut:
    return SessionTurnOut(
        turn_index=turn.turn_index,
        kind=turn.kind,
        question=turn.question,
        response_id=turn.response_id,
        is_refusal=turn.is_refusal,
        summary=turn.summary,
        finding_count=turn.finding_count,
        chart_count=turn.chart_count,
        created_at=turn.created_at,
    )
