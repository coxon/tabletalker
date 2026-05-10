"""Auto-resume helpers — rebuild a Session from disk + SQLite.

Used by:
  * `POST /v1/sessions/{id}/resume` — explicit resume from the
    history page; returns 410 GONE on missing artefacts so the SPA
    can offer a fresh chat instead.
  * `/v1/follow-up` (and its streaming variant) — silent fallback
    when `SESSION_STORE.resolve(parent_id)` misses. The most common
    cause is "backend restarted, in-memory dict empty"; rebuilding
    on demand keeps follow-ups working without making the client
    learn about the resume endpoint.

The resume only succeeds when ALL THREE of these hold:
  1. The persisted `session_state` JSON exists in SQLite.
  2. The workspace root resolves to a real directory (i.e. the
     deploy uses a persistent volume rather than the legacy tempdir).
  3. The on-disk workspace dir for the session id contains the
     primary upload. Without it, no follow-up can re-execute the
     plan.

When any check fails, returns None — the caller decides whether to
404, 410, or propagate.
"""

from __future__ import annotations

import logging

from app.persistence import get_session_recorder
from app.session.serde import session_from_dict
from app.session.store import SESSION_STORE, Session
from app.session.workspace import resolve_workspace_root

logger = logging.getLogger(__name__)


def try_resume_session(parent_or_turn_id: str) -> Session | None:
    """Best-effort: bring a persisted session back into SESSION_STORE.

    Accepts either the parent's response_id (= session_id) or any
    follow-up turn's response_id; both resolve to the same root
    session. Returns the live `Session` on success (already
    `SESSION_STORE.put`-ed) or None if any prerequisite is missing.
    """

    # Already alive — skip the disk round-trip entirely.
    existing = SESSION_STORE.resolve(parent_or_turn_id)
    if existing is not None:
        return existing

    recorder = get_session_recorder()
    session_id = recorder.find_session_id_by_turn_response_id(parent_or_turn_id)
    if session_id is None:
        return None

    state = recorder.load_state(session_id)
    if state is None:
        return None

    root = resolve_workspace_root()
    if root is None:
        # tempdir-only deploy → workspace gone after restart, can't
        # rebuild a Session that follow-up planners can read from.
        logger.warning(
            "try_resume_session: workspace root unset; cannot resume %s",
            session_id,
        )
        return None

    workspace_dir = root / session_id
    if not workspace_dir.is_dir():
        logger.warning(
            "try_resume_session: workspace dir missing for %s",
            session_id,
        )
        return None

    primary_file = workspace_dir / state.get("filename", "")
    if not primary_file.is_file():
        logger.warning(
            "try_resume_session: primary upload missing under %s",
            workspace_dir,
        )
        return None

    session = session_from_dict(state, workspace_dir)
    SESSION_STORE.put(session)
    logger.info("try_resume_session: rehydrated %s into SESSION_STORE", session_id)
    return session
