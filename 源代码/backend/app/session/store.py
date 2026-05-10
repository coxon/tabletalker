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

import itertools
import logging
import shutil
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.analyze.schema import AnalyzeResponse, Finding
from app.session.cohort import CohortDef

logger = logging.getLogger(__name__)


# Sentinel used by `allocate_follow_up_turn` to mark a reservation that
# has not yet been finalised. Module-level so tests and the route can
# reference the same string without typo risk.
PENDING_QUESTION = "<pending>"

TurnKind = Literal["parent", "follow_up"]


@dataclass(frozen=True)
class Turn:
    """One question/response pair within a session.

    `kind` distinguishes the parent analysis from follow-ups so the
    trace and the prompt assembler can lay out the history with the
    right framing.
    """

    index: int
    kind: TurnKind
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

    `_follow_up_lock` serialises the
    `allocate_follow_up_turn` → `set_turn_response` / `discard_turn`
    cycle on a *per-session* basis. This is intentional: without it, two
    in-flight follow-ups against the same parent could interleave such
    that A reserves q1, B reserves q2, A fails — and `discard_turn`
    can't safely pop A's placeholder (it isn't the tail anymore),
    leaving a dead `<pending>` turn that bumps the q-counter forever.
    Per-session serialisation keeps the q-numbering gap-free without
    holding the global store lock during the LLM round-trip.
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
    # Sampling declared on the parent request; persisted here so every
    # follow-up emits Evidence with the same sampling_rate / note. The
    # uploaded file on disk doesn't change between turns, so sampling is
    # session-scoped — re-prompting the user for it each turn would be
    # both annoying and an avenue for inconsistent grading. Required by
    # README §3.3 雷7 / §7.2 #7 whenever the source was downsampled.
    sampling_rate: float | None = None
    sampling_note: str | None = None
    # Auxiliary filenames from the multi-file parent turn (the primary
    # file is `filename`; these are the additional tables saved
    # alongside it in `workspace_dir`). Persisted so a follow-up can
    # rebuild the same `AnalyzeRequest` — without this, multi-file
    # conversations degrade to single-file on the second turn, which
    # silently breaks joins that reference a secondary table. Empty
    # tuple = single-file parent turn (the common case), so defaulting
    # is safe for older sessions in the store.
    extra_filenames: tuple[str, ...] = ()
    turns: list[Turn] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    # `repr=False` keeps logs/debug printouts readable; the lock object
    # has no useful str representation.
    _follow_up_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )


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
        # Per-allocation lock cache: maps a *unique* allocation token →
        # the `_follow_up_lock` that `allocate_follow_up_turn` acquired.
        # The token is monotonic and never reused, so a late
        # finalise/discard from an old session can't accidentally pop the
        # entry belonging to a new session that reused the same
        # `(session_id, turn_index)` tuple after eviction. Without this,
        # an old request could release the *new* session's lock — that
        # both reopens the interleaving bug per-session locking is meant
        # to fix and strands the old lock forever. The token is opaque to
        # callers; routes pass back what `allocate_follow_up_turn`
        # returned and never construct one themselves.
        self._allocation_locks: dict[int, threading.Lock] = {}
        self._allocation_token_counter = itertools.count()

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

    def resolve(self, session_or_turn_id: str) -> Session | None:
        """Look up a session by root id or by any response id in its turns.

        The public contract asks clients to send the parent
        ``eval_analysis_*`` id for every follow-up. The SPA streams each
        follow-up as a fresh response, though, and some callers naturally
        chain the next request with the latest ``eval_follow_*_qN`` id.
        Those turn ids are not sessions by themselves, but they should
        still resolve to the owning root session.
        """

        session = self.get(session_or_turn_id)
        if session is not None:
            return session

        now = time.time()
        evicted: list[Session] = []
        found: Session | None = None
        with self._lock:
            # TTL sweep first so a stale turn id cannot resurrect an
            # expired session. This mirrors `get()`'s stale miss behavior.
            for sid in [
                sid
                for sid, sess in self._items.items()
                if (now - sess.last_used_at) > self.ttl_seconds
            ]:
                evicted.append(self._items.pop(sid))

            found_sid: str | None = None
            for sid, candidate in self._items.items():
                if any(
                    turn.response_id == session_or_turn_id
                    for turn in candidate.turns
                ):
                    found_sid = sid
                    found = candidate
                    break
            if found_sid is not None and found is not None:
                found.last_used_at = now
                self._items.move_to_end(found_sid)

        for session_to_clean in evicted:
            _cleanup_workspace(session_to_clean)
        return found

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
    ) -> tuple[str, int, int]:
        """Atomically reserve a follow-up id and turn slot.

        Two requests against the same parent must never derive the same
        `eval_follow_<suffix>_qN` id — that would collide in the report
        store and one of the responses would silently overwrite the
        other. We reserve the slot under the store's lock by appending a
        placeholder turn, then return `(allocated_id, turn_index,
        allocation_token)` so the route can finalise it via
        `set_turn_response` once the pipeline completes. The token is an
        opaque process-unique handle; callers must pass it back to
        `set_turn_response` / `discard_turn` so we release the *right*
        per-session lock even if the original session was evicted and
        another one reused its id and `turn_index`.

        Per-session serialisation: this method also takes the session's
        `_follow_up_lock` and *keeps it held* across the LLM round-trip;
        the matching `set_turn_response` / `discard_turn` releases it.
        That guarantees discard always rolls back a tail placeholder and
        the q-counter stays gap-free even if two follow-ups for the same
        parent arrive in close succession (one will simply queue behind
        the other instead of interleaving). Different parents still run
        concurrently because each session owns its own lock.

        Raises `KeyError` if the session was evicted mid-flight; callers
        translate that to a 404 (see follow_up route).
        """

        # Acquire the per-session lock OUTSIDE the global store lock so a
        # contended session can't block lookups against other sessions.
        with self._lock:
            session = self._items.get(session_id)
            if session is None:
                raise KeyError(session_id)
            session_lock = session._follow_up_lock
        session_lock.acquire()
        try:
            with self._lock:
                # Re-check existence — eviction can happen while we waited
                # for the per-session lock.
                session = self._items.get(session_id)
                if session is None:
                    raise KeyError(session_id)
                turn_index = len(session.turns)
                allocated_id = id_factory(session_id, turn_index)
                placeholder = Turn(
                    index=turn_index,
                    kind="follow_up",
                    question=PENDING_QUESTION,
                    response_id=allocated_id,
                    is_refusal=False,
                )
                session.turns.append(placeholder)
                session.last_used_at = time.time()
                self._items.move_to_end(session_id)
                # Mint a unique allocation token. Monotonic counters can't
                # collide across the process lifetime, so a stale
                # finaliser holding a token from an evicted session can
                # never accidentally release the lock of a *new* session
                # that reused `(session_id, turn_index)`.
                token = next(self._allocation_token_counter)
                self._allocation_locks[token] = session_lock
                return allocated_id, turn_index, token
        except BaseException:
            # On failure release the per-session lock; the caller never
            # got a slot they're responsible for.
            session_lock.release()
            raise

    def _release_allocation_lock(self, token: int) -> None:
        """Pop and release the lock that `allocate_follow_up_turn` took.

        Idempotent: extra calls (e.g. from the `finally` of a path that
        already released) are no-ops. Returns silently if the entry
        isn't present — that case means a previous finalise/discard
        already cleaned up.
        """

        with self._lock:
            lock = self._allocation_locks.pop(token, None)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                # Lock was already released — defensive; shouldn't happen
                # given we pop atomically above, but cheaper to swallow
                # than to crash a request that already succeeded.
                pass

    def set_turn_response(
        self,
        session_id: str,
        turn_index: int,
        *,
        question: str,
        is_refusal: bool,
        allocation_token: int,
    ) -> None:
        """Finalise a previously-allocated turn.

        Replaces the placeholder appended by `allocate_follow_up_turn`
        and releases the matching per-session lock acquired there.
        `allocation_token` must be the value returned from the paired
        allocate — that's how we identify the *exact* lock to release
        even after id reuse.

        Raises `KeyError` if the session was evicted in the gap; the
        route maps that to a 404 — the response is already on its way
        back to the client at that point so we can't recover. The
        per-session lock is still released in that case via the
        side-channel cache (so a subsequent allocate against the same
        session id wouldn't deadlock).
        """

        try:
            with self._lock:
                session = self._items.get(session_id)
                if session is None:
                    raise KeyError(session_id)
                if turn_index >= len(session.turns):
                    # Defensive — this would mean another concurrent caller
                    # truncated the turns list, which we never do today.
                    raise KeyError((session_id, turn_index))
                existing = session.turns[turn_index]
                if existing.question != PENDING_QUESTION:
                    # Catches double-finalisation: a regression that
                    # called `set_turn_response` twice would silently
                    # overwrite a real answer otherwise.
                    raise RuntimeError(
                        f"turn {turn_index} on session {session_id!r} "
                        "is already finalised"
                    )
                session.turns[turn_index] = Turn(
                    index=turn_index,
                    kind=existing.kind,
                    question=question,
                    response_id=existing.response_id,
                    is_refusal=is_refusal,
                )
                session.last_used_at = time.time()
                self._items.move_to_end(session_id)
        finally:
            self._release_allocation_lock(allocation_token)

    def discard_turn(
        self, session_id: str, turn_index: int, *, allocation_token: int
    ) -> None:
        """Roll back an allocated-but-unfilled turn.

        Used when the pipeline downstream of `allocate_follow_up_turn`
        raises before the response is built. Per-session serialisation
        guarantees the placeholder is the tail at this point, so removal
        is unconditional under the per-session lock — the q-counter
        never skips. `allocation_token` releases the right per-session
        lock even after id reuse.

        Idempotent: extra checks ensure a stale double-discard (or a
        retry against a slot already reused by a fresh allocation) can't
        accidentally pop a finalised turn.
        """

        try:
            with self._lock:
                session = self._items.get(session_id)
                if session is None:
                    return  # already evicted; nothing to discard
                # Per-session serialisation invariant: the placeholder is
                # the tail. Bound + sentinel checks guard against the
                # stale-retry case where `turn_index` was already
                # finalised and the slot may have been consumed by a
                # later allocation — popping then would silently delete
                # a real turn.
                if turn_index < len(session.turns):
                    existing = session.turns[turn_index]
                    if existing.question == PENDING_QUESTION:
                        session.turns.pop(turn_index)
                        session.last_used_at = time.time()
        finally:
            self._release_allocation_lock(allocation_token)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        """Test helper — drop every entry."""

        with self._lock:
            evicted = list(self._items.values())
            self._items.clear()
            # Drop any in-flight allocation locks too. Tests and shutdown
            # paths assume `clear()` returns a pristine store; leaving
            # acquired locks behind would deadlock the next allocation
            # against any session id reused after the clear.
            stranded = list(self._allocation_locks.values())
            self._allocation_locks.clear()
        for lock in stranded:
            try:
                lock.release()
            except RuntimeError:
                pass
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
    sampling_rate: float | None = None,
    sampling_note: str | None = None,
    extra_filenames: tuple[str, ...] = (),
) -> Session:
    """Construct a `Session` from a finished parent analyze response.

    Centralised so the route doesn't have to know which AnalyzeResponse
    fields feed which Session fields — keeping that mapping here means
    contract drift breaks one place, not three.

    `sampling_rate` / `sampling_note` are propagated from the parent
    request so follow-ups can stamp the same disclosure on their own
    Evidence rows. The defaults of None preserve backward compatibility
    for callers that don't sample.

    `extra_filenames` carries the auxiliary tables from a multi-file
    parent turn so follow-up requests can rebuild the same multi-file
    `AnalyzeRequest`. The default of `()` preserves the single-file
    shape for callers that don't use multi-file analysis (e.g. most of
    the existing tests) and for in-flight sessions created before
    multi-file support landed (None / missing → empty tuple).
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
        sampling_rate=sampling_rate,
        sampling_note=sampling_note,
        extra_filenames=extra_filenames,
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
