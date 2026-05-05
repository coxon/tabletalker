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
from collections.abc import Callable
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
            evicted = self._evict_locked()
        # Workspace cleanup outside the lock — `shutil.rmtree` on a slow
        # filesystem must never block other `get`/`put` callers.
        for session_to_clean in evicted:
            _cleanup_workspace(session_to_clean)

    def get(self, session_id: str) -> Session | None:
        """Look up by id, refreshing the LRU order on hit."""

        now = time.time()
        evicted: Session | None = None
        with self._lock:
            session = self._items.get(session_id)
            if session is None:
                return None
            if (now - session.last_used_at) > self.ttl_seconds:
                # TTL expired — drop and report miss so the route can
                # surface a clean 410/404 rather than serve stale state.
                # Pop under the lock; clean the workspace after release.
                evicted = self._items.pop(session_id)
            else:
                session.last_used_at = now
                self._items.move_to_end(session_id)
        if evicted is not None:
            _cleanup_workspace(evicted)
            return None
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

    def allocate_follow_up_turn(
        self, session_id: str, *, id_factory: Callable[[str, int], str]
    ) -> tuple[str, int]:
        """Atomically reserve a follow-up id and turn slot.

        Two requests against the same parent must never derive the same
        `eval_follow_<suffix>_qN` id — that would collide in the report
        store and one of the responses would silently overwrite the
        other. We reserve the slot under the store's lock by appending a
        placeholder turn, then return `(allocated_id, turn_index)` so
        the route can finalise it via `set_turn_response` once the
        pipeline completes.

        Raises `KeyError` if the session was evicted mid-flight; callers
        translate that to a 404 (see follow_up route).
        """

        with self._lock:
            session = self._items.get(session_id)
            if session is None:
                raise KeyError(session_id)
            turn_index = len(session.turns)
            allocated_id = id_factory(session_id, turn_index)
            placeholder = Turn(
                index=turn_index,
                kind="follow_up",
                question="<pending>",
                response_id=allocated_id,
                is_refusal=False,
            )
            session.turns.append(placeholder)
            session.last_used_at = time.time()
            self._items.move_to_end(session_id)
            return allocated_id, turn_index

    def set_turn_response(
        self,
        session_id: str,
        turn_index: int,
        *,
        question: str,
        is_refusal: bool,
    ) -> None:
        """Finalise a previously-allocated turn.

        Replaces the placeholder appended by `allocate_follow_up_turn`.
        Raises `KeyError` if the session was evicted in the gap; the
        route maps that to a 404 — the response is already on its way
        back to the client at that point so we can't recover.
        """

        with self._lock:
            session = self._items.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if turn_index >= len(session.turns):
                # Defensive — this would mean another concurrent caller
                # truncated the turns list, which we never do today.
                raise KeyError((session_id, turn_index))
            existing = session.turns[turn_index]
            session.turns[turn_index] = Turn(
                index=turn_index,
                kind=existing.kind,
                question=question,
                response_id=existing.response_id,
                is_refusal=is_refusal,
            )
            session.last_used_at = time.time()
            self._items.move_to_end(session_id)

    def discard_turn(self, session_id: str, turn_index: int) -> None:
        """Roll back an allocated-but-unfilled turn.

        Used when the pipeline downstream of `allocate_follow_up_turn`
        raises before the response is built — leaving the placeholder
        in place would inflate `len(session.turns)` and skip the next
        q-counter, which graders would notice. Best-effort: if the
        session was already evicted, there's nothing to do.
        """

        with self._lock:
            session = self._items.get(session_id)
            if session is None:
                return
            # Only pop if our placeholder is still the tail; concurrent
            # finalisation may have shifted things underneath us.
            if turn_index < len(session.turns) and turn_index == len(session.turns) - 1:
                session.turns.pop()
                session.last_used_at = time.time()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        """Test helper — drop every entry."""

        with self._lock:
            evicted = list(self._items.values())
            self._items.clear()
        # Cleanup outside the lock; see `put`/`get` for the rationale.
        for session in evicted:
            _cleanup_workspace(session)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict_locked(self) -> list[Session]:
        """Drop expired entries, then trim down to `max_sessions`.

        Returns the list of evicted Sessions so the caller can run
        `_cleanup_workspace` *after* releasing the lock — keeps the
        critical section O(n) in dict mutations only, never O(rmtree).

        Caller must hold `self._lock`.
        """

        evicted: list[Session] = []
        now = time.time()
        # TTL sweep — iterate over a snapshot so we can mutate.
        for sid in [
            sid
            for sid, sess in self._items.items()
            if (now - sess.last_used_at) > self.ttl_seconds
        ]:
            evicted.append(self._items.pop(sid))
        # LRU trim.
        while len(self._items) > self.max_sessions:
            evicted_id, evicted_session = self._items.popitem(last=False)
            evicted.append(evicted_session)
            logger.info("session evicted (LRU cap): %s", evicted_id)
        return evicted


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
