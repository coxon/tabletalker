"""Cross-restart persistence layer.

In-process state (`app.session.store`, `app.report.store`) is fast but
dies with the worker. The "历史分析" UI needs a durable index of every
analysis the user has run so it can list them across restarts and after
the 24h TTL has aged the in-memory entry out.

We deliberately keep two layers:

  - `app.session.store.SESSION_STORE` — the hot path. Every `/v1/follow-up`
    reads from it and the workspace lives there. Unchanged by this
    package; we never touch its lock or its lifecycle.
  - `app.persistence.sessions.SESSION_RECORDER` — the durable index.
    Routes write to it on every parent / follow-up completion. Reads
    happen exclusively from `/v1/sessions` (the list / detail UI).
    Failures here log and swallow — a sqlite hiccup must not 500 a real
    analysis request.

Storage backend is sqlite (stdlib, no new deps). The DB path resolves
from `TABLETALKER_DATA_DIR` (default `./data` relative to CWD), so prod
deploys can mount a volume for it.
"""

from app.persistence.sessions import (
    SESSION_RECORDER,
    SessionDetail,
    SessionRecorder,
    SessionSummary,
    SessionTurnRecord,
    get_session_recorder,
    set_session_recorder,
)

__all__ = [
    "SESSION_RECORDER",
    "SessionDetail",
    "SessionRecorder",
    "SessionSummary",
    "SessionTurnRecord",
    "get_session_recorder",
    "set_session_recorder",
]
