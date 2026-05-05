"""In-memory session store — parent analyses keyed by id.

The contract's `/v1/follow-up` route needs everything from the parent
turn: the original question, the file workspace, the findings, the
cohorts the planner is allowed to reference by name. Same single-worker
caveat as `app.report.store` — see that module's docstring for the
multi-process Redis-backed promotion path.

TTL eviction kicks in on every access (cheap O(1) with the OrderedDict
the FIFO uses), not on a background thread, so the store has zero
runtime overhead when idle.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from app.analyze.schema import AnalyzeResponse, Finding
from app.session.cohort import CohortDef

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Turn:
    """One question/response pair within a session.

    `kind` distinguishes the parent analysis from follow-ups so the
    trace and the prompt assembler can lay out the history with the
    right framing.
    """

    index: int
    kind: str  # "parent" | "follow_up"
    question: str
    response_id: str
    is_refusal: bool


@dataclass
class Session:
    """One parent analysis plus its accumulated follow-up turns.

    `workspace_dir` is the per-request temp dir the parent route created.
    Follow-ups reuse it (the file is still on disk for the duration of
    the session — see `cleanup` below).

    `parent_summary` is the *verbatim* summary string the parent emitted.
    Refusal carry-through (`docs/refusal-policy.md` §carry-through) hands
    it back unmodified to follow-ups of refused parents — that's why we
    store it on the session rather than re-deriving it from `findings`.
    """

    id: str
    workspace_dir: Path
    filename: str
    dataset: str
    original_question: str
    findings: list[Finding]
    parent_summary: str = ""
    cohorts: list[CohortDef] = field(default_factory=list)
    chart_anchors: list[str] = field(default_factory=list)
    refused: bool = False
    turns: list[Turn] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)


# Default TTL: 24h, per `docs/session-state.md` §6. Entries older than
# this on access get evicted. Tuned for the eval harness which fires
# follow-ups within a few seconds of the parent.
DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MAX_SESSIONS = 10_000


class SessionStore:
    """Thread-safe LRU+TTL cache of `parent_id -> Session`.

    LRU = move on every `get` so an active session never expires while
    follow-ups keep arriving. TTL = stale entries are dropped lazily on
    access.
    """

    def __init__(
        self,
        *,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        if not isinstance(max_sessions, int) or max_sessions < 1:
            raise ValueError(
                f"max_sessions must be a positive int, got {max_sessions!r}"
            )
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be > 0, got {ttl_seconds!r}")
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._items: OrderedDict[str, Session] = OrderedDict()

    def put(self, session: Session) -> None:
        """Insert / update a session; evict stale + over-cap entries."""

        with self._lock:
            self._items[session.id] = session
            self._items.move_to_end(session.id)
            self._evict_locked()

    def get(self, session_id: str) -> Session | None:
        """Look up by id, refreshing the LRU order on hit."""

        now = time.time()
        with self._lock:
            session = self._items.get(session_id)
            if session is None:
                return None
            if (now - session.last_used_at) > self.ttl_seconds:
                # TTL expired — drop and report miss so the route can
                # surface a clean 410/404 rather than serve stale state.
                del self._items[session_id]
                _cleanup_workspace(session)
                return None
            session.last_used_at = now
            self._items.move_to_end(session_id)
            return session

    def append_turn(self, session_id: str, turn: Turn) -> None:
        """Convenience: append a turn and bump LRU/TTL in one shot."""

        with self._lock:
            session = self._items.get(session_id)
            if session is None:
                raise KeyError(session_id)
            session.turns.append(turn)
            session.last_used_at = time.time()
            self._items.move_to_end(session_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        """Test helper — drop every entry."""

        with self._lock:
            for session in list(self._items.values()):
                _cleanup_workspace(session)
            self._items.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict_locked(self) -> None:
        """Drop expired entries, then trim down to `max_sessions`.

        Caller must hold `self._lock`.
        """

        now = time.time()
        # TTL sweep — iterate over a snapshot so we can mutate.
        for sid in [
            sid
            for sid, sess in self._items.items()
            if (now - sess.last_used_at) > self.ttl_seconds
        ]:
            evicted = self._items.pop(sid)
            _cleanup_workspace(evicted)
        # LRU trim.
        while len(self._items) > self.max_sessions:
            evicted_id, evicted = self._items.popitem(last=False)
            _cleanup_workspace(evicted)
            logger.info("session evicted (LRU cap): %s", evicted_id)


def _cleanup_workspace(session: Session) -> None:
    """Best-effort `rmtree` of a session's per-request temp dir.

    Called from `_evict_locked` and `clear` — never inside `get`'s hot
    path so a slow filesystem doesn't block the request that triggered
    the TTL miss. `ignore_errors=True` because a partially-cleaned dir
    is no worse than the alternative (a zombie path the OS will reap on
    its next /tmp sweep anyway).
    """

    try:
        shutil.rmtree(session.workspace_dir, ignore_errors=True)
    except OSError as exc:  # extremely defensive — `ignore_errors` already swallows most
        logger.warning(
            "session workspace cleanup failed for %s: %s", session.id, exc
        )


# Module-level singleton — the parent analyze route writes here, the
# follow-up route reads. Same caveat as `app.report.store`: single-worker
# only; promotion to a shared backend is a Day-2 task.
SESSION_STORE = SessionStore()


def session_from_response(
    response: AnalyzeResponse,
    *,
    workspace_dir: Path,
    filename: str,
    dataset: str,
    original_question: str,
    cohorts: list[CohortDef],
) -> Session:
    """Construct a `Session` from a finished parent analyze response.

    Centralised so the route doesn't have to know which AnalyzeResponse
    fields feed which Session fields — keeping that mapping here means
    contract drift breaks one place, not three.
    """

    chart_anchors = [c.html_anchor for c in response.charts]
    return Session(
        id=response.id,
        workspace_dir=workspace_dir,
        filename=filename,
        dataset=dataset,
        original_question=original_question,
        findings=list(response.findings),
        parent_summary=response.summary,
        cohorts=list(cohorts),
        chart_anchors=chart_anchors,
        refused=response.is_refusal,
        turns=[
            Turn(
                index=0,
                kind="parent",
                question=original_question,
                response_id=response.id,
                is_refusal=response.is_refusal,
            )
        ],
    )
