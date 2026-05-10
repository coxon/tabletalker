"""Sqlite-backed session index — durable across restarts.

Why sqlite and not Redis / Postgres / a JSON file:

  * **stdlib** — no new dep, no new container in docker-compose.
  * **single writer** matches our deploy topology (single uvicorn worker;
    see `app.report.store` docstring). The hot path through
    `SESSION_STORE` is already serialised; sqlite's WAL handles the rest.
  * **schema migration is one ALTER away** — we're 2 days from deadline,
    and rolling a schema change forward in sqlite is `ALTER TABLE`,
    same as Postgres but without an external service to run it against.
  * **JSON file** would race the multi-tab UI (two browser windows
    submitting analyses at once would silently lose one of them on the
    next read-modify-write).

Failure policy: the recorder is a *side channel*. Every method except
`get_session` / `list_sessions` swallows exceptions after logging. A
disk-full or schema-drift event must NOT take down `/v1/analyze` —
losing a row in the history index is a strictly better failure mode
than dropping the actual analysis result.

Schema (v1):

    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        primary_filename TEXT NOT NULL,
        extra_filenames TEXT NOT NULL,        -- JSON array
        created_at REAL NOT NULL,             -- unix epoch seconds (UTC)
        updated_at REAL NOT NULL,
        status TEXT NOT NULL,                 -- 'completed' | 'refused'
        is_refusal INTEGER NOT NULL,          -- 0 / 1
        chart_count INTEGER NOT NULL,
        finding_count INTEGER NOT NULL,
        report_html_url TEXT NOT NULL,
        sampling_rate REAL,                   -- nullable
        sampling_note TEXT                    -- nullable
    );

    CREATE TABLE session_turns (
        session_id TEXT NOT NULL,
        turn_index INTEGER NOT NULL,
        kind TEXT NOT NULL,                   -- 'parent' | 'follow_up'
        question TEXT NOT NULL,
        response_id TEXT NOT NULL,
        is_refusal INTEGER NOT NULL,
        summary TEXT NOT NULL,
        finding_count INTEGER NOT NULL,
        chart_count INTEGER NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (session_id, turn_index),
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_sessions_updated_at ON sessions(updated_at DESC);

`title` defaults to the parent question's first 40 chars; we keep the
column denormalised because the listing UI sorts and filters on it.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.analyze.schema import AnalyzeResponse

logger = logging.getLogger(__name__)


_SCHEMA_VERSION = 1

# Closed enums for the two enum-shaped columns. Lifted to module-level
# (rather than inlined as `Literal[...]` in each dataclass) so the API
# layer can reuse the same aliases without having to redeclare the
# allowed values, and so a future refactor that adds a third state
# (e.g. "in_progress") changes one place. CR #18 round-1 nit: typing
# the persistence DTOs lets the API conversion functions drop their
# `# type: ignore[arg-type]` markers — the row→DTO→Pydantic chain is
# now Literal-typed end to end.
SessionStatus = Literal["completed", "refused"]
TurnKind = Literal["parent", "follow_up"]


def _resolve_db_path() -> Path:
    """Resolve the sqlite file path from env, with a `./data` fallback.

    Honours `TABLETALKER_DATA_DIR` so prod deployments can mount a volume
    (`docker run -v /var/lib/tabletalker:/app/data ...`). Tests override
    via `SessionRecorder(db_path=tmp_path / "sessions.db")` — the env
    knob is only consulted by the module-level singleton.
    """

    raw = os.environ.get("TABLETALKER_DATA_DIR", "").strip()
    base = Path(raw) if raw else Path.cwd() / "data"
    return base / "sessions.db"


# ---------------------------------------------------------------------------
# DTOs returned to the API layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionSummary:
    """Row-shape returned by `list_sessions` — keep it shallow.

    Mirrors the columns the listing UI shows: title, file chips, status
    badge, last-updated stamp, follow-up count. Detailed turn / chart
    fan-out lives in `SessionDetail` so the list query stays cheap.
    """

    id: str
    title: str
    primary_filename: str
    extra_filenames: tuple[str, ...]
    created_at: float
    updated_at: float
    status: SessionStatus
    is_refusal: bool
    follow_up_count: int
    chart_count: int
    finding_count: int


@dataclass(frozen=True)
class SessionTurnRecord:
    """One turn inside a session — what the detail panel renders."""

    turn_index: int
    kind: TurnKind
    question: str
    response_id: str
    is_refusal: bool
    summary: str
    finding_count: int
    chart_count: int
    created_at: float


@dataclass(frozen=True)
class SessionDetail:
    """Full session record — `list_sessions` row plus all turns + report URL."""

    id: str
    title: str
    primary_filename: str
    extra_filenames: tuple[str, ...]
    created_at: float
    updated_at: float
    status: SessionStatus
    is_refusal: bool
    chart_count: int
    finding_count: int
    report_html_url: str
    sampling_rate: float | None
    sampling_note: str | None
    turns: tuple[SessionTurnRecord, ...]


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class SessionRecorder:
    """Sqlite-backed durable index of analyses.

    Thread-safe via a single `threading.Lock` around the connection —
    sqlite itself is fine with concurrent reads but our connection is
    shared and serialising writes in Python is simpler than juggling
    per-thread connections. Throughput here is bounded by the analyze
    pipeline's LLM round-trips anyway; the lock is never the bottleneck.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _resolve_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we wrap multi-stmt ops in BEGIN
        )
        self._conn.row_factory = sqlite3.Row
        # WAL keeps reads non-blocking during writes — important when
        # the listing UI polls while a long analyze is mid-flight.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        # Schema bootstrap may raise (e.g. version mismatch — CR #18
        # round-1). Close the connection on failure so the file handle
        # doesn't leak; the caller will get the original exception and
        # the lazy singleton will not cache this half-built instance.
        try:
            self._init_schema()
        except BaseException:
            self._conn.close()
            raise

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create tables if absent. Idempotent — safe to call on every boot.

        We don't bother with `alembic` for a 2-day-deadline project; the
        `_schema_version` table acts as a tripwire for future migrations.
        """

        with self._tx() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS _schema_version "
                "(version INTEGER PRIMARY KEY)"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                "  id TEXT PRIMARY KEY,"
                "  title TEXT NOT NULL,"
                "  primary_filename TEXT NOT NULL,"
                "  extra_filenames TEXT NOT NULL,"
                "  created_at REAL NOT NULL,"
                "  updated_at REAL NOT NULL,"
                "  status TEXT NOT NULL,"
                "  is_refusal INTEGER NOT NULL,"
                "  chart_count INTEGER NOT NULL,"
                "  finding_count INTEGER NOT NULL,"
                "  report_html_url TEXT NOT NULL,"
                "  sampling_rate REAL,"
                "  sampling_note TEXT"
                ")"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS session_turns ("
                "  session_id TEXT NOT NULL,"
                "  turn_index INTEGER NOT NULL,"
                "  kind TEXT NOT NULL,"
                "  question TEXT NOT NULL,"
                "  response_id TEXT NOT NULL,"
                "  is_refusal INTEGER NOT NULL,"
                "  summary TEXT NOT NULL,"
                "  finding_count INTEGER NOT NULL,"
                "  chart_count INTEGER NOT NULL,"
                "  created_at REAL NOT NULL,"
                "  PRIMARY KEY (session_id, turn_index),"
                "  FOREIGN KEY (session_id) REFERENCES sessions(id) "
                "    ON DELETE CASCADE"
                ")"
            )
            # Session state JSON — the rich `Session` fields the planner
            # prelude depends on (findings, cohorts, chart_anchors,
            # parent_summary, refused, original_question, dataset). The
            # `sessions` and `session_turns` tables track display
            # metadata; `session_state` is what makes "resume after a
            # backend restart" possible. Additive, so `IF NOT EXISTS`
            # handles both fresh installs and existing v1 dbs without
            # bumping `_SCHEMA_VERSION`.
            cur.execute(
                "CREATE TABLE IF NOT EXISTS session_state ("
                "  session_id TEXT PRIMARY KEY,"
                "  state_json TEXT NOT NULL,"
                "  updated_at REAL NOT NULL,"
                "  FOREIGN KEY (session_id) REFERENCES sessions(id) "
                "    ON DELETE CASCADE"
                ")"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at "
                "ON sessions(updated_at DESC)"
            )
            row = cur.execute(
                "SELECT version FROM _schema_version"
            ).fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO _schema_version(version) VALUES (?)",
                    (_SCHEMA_VERSION,),
                )
            elif row["version"] != _SCHEMA_VERSION:
                # CR #18 round-1 (Major): fail closed instead of returning
                # a recorder bound to an incompatible schema. Caching such a
                # recorder would mean every subsequent /v1/sessions call
                # silently fails with the wrong column shape until the
                # process restarts; raising here lets the lazy singleton
                # re-attempt on the next call (after the operator has
                # cleaned up the rogue file). The route layer translates
                # `sqlite3.DatabaseError` to a 503, so the UI can render a
                # "history temporarily unavailable" toast instead of a
                # generic 500.
                logger.error(
                    "session DB schema version mismatch: file=%s found=%s "
                    "expected=%s. If this is the first boot of a new release, "
                    "run `rm %s` to recreate; otherwise investigate the source.",
                    self._db_path,
                    row["version"],
                    _SCHEMA_VERSION,
                    self._db_path,
                )
                raise sqlite3.DatabaseError(
                    f"session DB schema version mismatch for {self._db_path}: "
                    f"found {row['version']}, expected {_SCHEMA_VERSION}"
                )

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        """Take the lock + open a sqlite transaction.

        We're in autocommit mode (`isolation_level=None`) so explicit
        `BEGIN` / `COMMIT` keep multi-statement updates atomic. On error
        we ROLLBACK and re-raise — recorder callers swallow the
        exception, so the route still returns success.
        """

        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            try:
                yield cur
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.close()

    # ------------------------------------------------------------------
    # Write paths (called from /v1/analyze and /v1/follow-up)
    # ------------------------------------------------------------------

    def record_parent(
        self,
        response: AnalyzeResponse,
        *,
        primary_filename: str,
        extra_filenames: Iterable[str],
        original_question: str,
        sampling_rate: float | None,
        sampling_note: str | None,
    ) -> None:
        """Insert a fresh session row + its parent turn.

        Idempotency: if a request is retried with the same `response.id`
        (the contract id is currently regenerated per request, but a
        future retry-with-same-id path mustn't break us) we use sqlite
        UPSERT semantics so the second write updates the existing row
        in place instead of going through DELETE + INSERT.

        Why not `INSERT OR REPLACE`: that's implemented as DELETE +
        INSERT, which would CASCADE-delete every `session_turns` row
        the parent already had — a parent retry that arrived AFTER
        follow-ups had been recorded would silently erase the entire
        turn history. UPSERT (`ON CONFLICT DO UPDATE`) preserves
        children. Same reasoning applies to `session_turns` below.
        """

        now = time.time()
        title = _derive_title(original_question)
        try:
            with self._tx() as cur:
                cur.execute(
                    "INSERT INTO sessions ("
                    "  id, title, primary_filename, extra_filenames,"
                    "  created_at, updated_at, status, is_refusal,"
                    "  chart_count, finding_count, report_html_url,"
                    "  sampling_rate, sampling_note"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  title=excluded.title,"
                    "  primary_filename=excluded.primary_filename,"
                    "  extra_filenames=excluded.extra_filenames,"
                    "  updated_at=excluded.updated_at,"
                    "  status=excluded.status,"
                    "  is_refusal=excluded.is_refusal,"
                    "  chart_count=excluded.chart_count,"
                    "  finding_count=excluded.finding_count,"
                    "  report_html_url=excluded.report_html_url,"
                    "  sampling_rate=excluded.sampling_rate,"
                    "  sampling_note=excluded.sampling_note",
                    (
                        response.id,
                        title,
                        primary_filename,
                        json.dumps(list(extra_filenames), ensure_ascii=False),
                        now,
                        now,
                        "refused" if response.is_refusal else "completed",
                        1 if response.is_refusal else 0,
                        len(response.charts),
                        len(response.findings),
                        response.report_html_url,
                        sampling_rate,
                        sampling_note,
                    ),
                )
                cur.execute(
                    "INSERT INTO session_turns ("
                    "  session_id, turn_index, kind, question, response_id,"
                    "  is_refusal, summary, finding_count, chart_count, "
                    "  created_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(session_id, turn_index) DO UPDATE SET "
                    "  kind=excluded.kind,"
                    "  question=excluded.question,"
                    "  response_id=excluded.response_id,"
                    "  is_refusal=excluded.is_refusal,"
                    "  summary=excluded.summary,"
                    "  finding_count=excluded.finding_count,"
                    "  chart_count=excluded.chart_count",
                    (
                        response.id,
                        0,
                        "parent",
                        original_question,
                        response.id,
                        1 if response.is_refusal else 0,
                        response.summary,
                        len(response.findings),
                        len(response.charts),
                        now,
                    ),
                )
        except sqlite3.Error:
            # Side-channel; don't poison the request.
            logger.exception(
                "session recorder: failed to persist parent %s", response.id
            )

    def record_followup(
        self,
        *,
        session_id: str,
        turn_index: int,
        question: str,
        response: AnalyzeResponse,
    ) -> None:
        """Append a follow-up turn + bump the session's `updated_at`.

        We don't refresh `chart_count` / `finding_count` on the parent
        row because the listing card displays *parent-level* aggregates
        (the session's seed analysis); per-turn detail lives in the
        `session_turns` rows the detail panel reads. If a future UI pivot
        wants cumulative counts they're a `SELECT SUM(...)` away.

        UPSERT instead of `INSERT OR REPLACE` for the same reason as
        `record_parent` — DELETE + INSERT would technically be safe at
        the leaf level (no FK pointing at session_turns), but using the
        same idiom everywhere makes audit-by-grep easier and means a
        future schema change that adds a child table to session_turns
        doesn't silently reintroduce the cascade-delete footgun.
        """

        now = time.time()
        try:
            with self._tx() as cur:
                cur.execute(
                    "INSERT INTO session_turns ("
                    "  session_id, turn_index, kind, question, response_id,"
                    "  is_refusal, summary, finding_count, chart_count, "
                    "  created_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(session_id, turn_index) DO UPDATE SET "
                    "  kind=excluded.kind,"
                    "  question=excluded.question,"
                    "  response_id=excluded.response_id,"
                    "  is_refusal=excluded.is_refusal,"
                    "  summary=excluded.summary,"
                    "  finding_count=excluded.finding_count,"
                    "  chart_count=excluded.chart_count",
                    (
                        session_id,
                        turn_index,
                        "follow_up",
                        question,
                        response.id,
                        1 if response.is_refusal else 0,
                        response.summary,
                        len(response.findings),
                        len(response.charts),
                        now,
                    ),
                )
                cur.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (now, session_id),
                )
        except sqlite3.Error:
            logger.exception(
                "session recorder: failed to persist follow-up %s/%d",
                session_id,
                turn_index,
            )

    def record_state(self, session_id: str, state: dict) -> None:
        """Upsert the rich Session-state JSON for `session_id`.

        Called after every successful parent / follow-up turn. The
        payload is a dict produced by `app.session.serde.session_to_dict`
        and consumed by the resume endpoint to rebuild an in-memory
        `Session` after a backend restart. Failures are logged and
        swallowed — persistence is a side-channel and must not poison
        the request.
        """

        try:
            payload = json.dumps(state, ensure_ascii=False)
        except (TypeError, ValueError):
            logger.exception("record_state: non-JSON payload for %s", session_id)
            return
        now = time.time()
        try:
            with self._tx() as cur:
                cur.execute(
                    "INSERT INTO session_state (session_id, state_json, updated_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET "
                    "  state_json=excluded.state_json,"
                    "  updated_at=excluded.updated_at",
                    (session_id, payload, now),
                )
        except sqlite3.Error:
            logger.exception("record_state: sqlite write failed for %s", session_id)

    def load_state(self, session_id: str) -> dict | None:
        """Return the persisted Session-state dict for `session_id` or None."""

        try:
            with self._tx() as cur:
                row = cur.execute(
                    "SELECT state_json FROM session_state WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        except sqlite3.Error:
            logger.exception("load_state: sqlite read failed for %s", session_id)
            return None
        if row is None:
            return None
        try:
            return json.loads(row["state_json"])
        except (TypeError, ValueError):
            logger.exception("load_state: corrupt state_json for %s", session_id)
            return None

    def find_session_id_by_turn_response_id(
        self, response_id: str
    ) -> str | None:
        """Resolve a turn's response_id back to its owning session_id.

        Used by the follow-up auto-resume fallback: clients commonly
        send the LATEST turn's id as `parent_id`, but on a fresh
        process the in-memory `SESSION_STORE.resolve` walk has nothing
        to match against. The durable `session_turns` table does, and
        the `session_id` it returns lets the resume helper rehydrate
        the right session.

        First tries `id == response_id` (the parent's own id is the
        session id), then `session_turns.response_id`. Returns None if
        the id matches neither.
        """

        try:
            with self._tx() as cur:
                row = cur.execute(
                    "SELECT id FROM sessions WHERE id = ? LIMIT 1",
                    (response_id,),
                ).fetchone()
                if row is not None:
                    return str(row["id"])
                row = cur.execute(
                    "SELECT session_id FROM session_turns "
                    "WHERE response_id = ? LIMIT 1",
                    (response_id,),
                ).fetchone()
                if row is not None:
                    return str(row["session_id"])
                return None
        except sqlite3.Error:
            logger.exception(
                "find_session_id_by_turn_response_id: sqlite read failed for %s",
                response_id,
            )
            return None

    # ------------------------------------------------------------------
    # Read paths (called from /v1/sessions endpoints)
    # ------------------------------------------------------------------

    def list_sessions(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SessionSummary]:
        """Return sessions sorted by `updated_at DESC`.

        `query` does a case-insensitive substring match on title /
        primary filename. `status` filters by `'completed'` / `'refused'`.
        `limit` is a soft cap on UI page size; we don't paginate yet
        (sessions are bounded by the in-process LRU cap times any history,
        and the listing UI scrolls fine through ~1k entries).
        """

        # Bound the limit defensively — a malicious UI request asking for
        # 10**9 rows shouldn't be able to OOM the worker.
        limit = max(1, min(limit, 1000))
        clauses: list[str] = []
        params: list[object] = []
        if query:
            # CR #18 round-2 (Major): user input is a SQL LIKE pattern;
            # bare `%` and `_` would over-match (e.g. searching for "50%
            # off" would match every title). Escape them, then opt the
            # column LIKE clauses into ESCAPE '\' so the literal pattern
            # wins. Backslash itself must be doubled first, otherwise the
            # `\` we write before `%`/`_` would itself become an escaped
            # backslash followed by an unescaped wildcard.
            escaped = (
                query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append(
                "(title LIKE ? ESCAPE '\\' "
                "OR primary_filename LIKE ? ESCAPE '\\')"
            )
            like = f"%{escaped}%"
            params.extend([like, like])
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT s.id, s.title, s.primary_filename, s.extra_filenames,"
            "  s.created_at, s.updated_at, s.status, s.is_refusal,"
            "  s.chart_count, s.finding_count,"
            "  ("
            "    SELECT COUNT(*) FROM session_turns t"
            "    WHERE t.session_id = s.id AND t.kind = 'follow_up'"
            "  ) AS follow_up_count "
            "FROM sessions s "
            f"{where} "
            "ORDER BY s.updated_at DESC LIMIT ?"
        )
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_summary(r) for r in rows]

    def get_session(self, session_id: str) -> SessionDetail | None:
        """Fetch one session + all its turns. Returns None if absent."""

        with self._lock:
            session_row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session_row is None:
                return None
            turn_rows = self._conn.execute(
                "SELECT * FROM session_turns WHERE session_id = ? "
                "ORDER BY turn_index ASC",
                (session_id,),
            ).fetchall()
        turns = tuple(_row_to_turn(r) for r in turn_rows)
        # CR #18 round-2 (Major): coerce the status column the same way
        # `_row_to_summary` does. Without this, a hand-edited DB could
        # smuggle a free-form string into `SessionDetail.status` (the
        # field is Literal-typed, so pyright would believe it; the
        # Pydantic boundary in api/sessions.py would then 500). Going
        # through `_coerce_status` raises sqlite3.DatabaseError, which
        # the GET /v1/sessions/{id} route translates to 503.
        return SessionDetail(
            id=session_row["id"],
            title=session_row["title"],
            primary_filename=session_row["primary_filename"],
            extra_filenames=tuple(json.loads(session_row["extra_filenames"])),
            created_at=session_row["created_at"],
            updated_at=session_row["updated_at"],
            status=_coerce_status(session_row["status"]),
            is_refusal=bool(session_row["is_refusal"]),
            chart_count=session_row["chart_count"],
            finding_count=session_row["finding_count"],
            report_html_url=session_row["report_html_url"],
            sampling_rate=session_row["sampling_rate"],
            sampling_note=session_row["sampling_note"],
            turns=turns,
        )

    def delete_session(self, session_id: str) -> bool:
        """Drop a session + all its turns. Returns True iff a row was removed.

        Used by the "history" UI's trash icon. Doesn't touch the
        in-memory `SESSION_STORE` — a follow-up against a deleted history
        entry would still work until the in-memory TTL expires, which is
        the right tradeoff: deleting from history is "stop showing this
        in my list", not "yank the workspace mid-conversation".

        Unlike the write path (`record_parent` / `record_followup`),
        this method **propagates** sqlite errors instead of swallowing
        them. CR #18 round-1 (Major): the previous `return False` on
        error was indistinguishable from "session id not present", so a
        broken history store would tell the UI "the row is gone" and
        the user would see their analysis vanish. The route layer
        catches the exception and returns 503, leaving 404 to mean only
        what it should — a genuine miss.
        """

        with self._tx() as cur:
            cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            deleted = cur.rowcount
        return deleted > 0

    # ------------------------------------------------------------------
    # Test/admin helpers
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Aggregates for the history landing page's three stat cards.

        Returns:
            { 'total': N, 'this_week': M, 'continuable': K }

        `continuable` = sessions whose seed analysis didn't refuse — i.e.
        the user could productively click "继续追问". Refusal carry-through
        means even a refused parent is technically callable, but the UI
        treats those as terminal so the count there matches the badge.
        """

        now = time.time()
        week_ago = now - 7 * 24 * 60 * 60
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0]
            this_week = self._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE created_at >= ?",
                (week_ago,),
            ).fetchone()[0]
            continuable = self._conn.execute(
                # CR #18 round-2: status is the source of truth (the
                # API derives is_refusal from it). Counting from the
                # is_refusal flag column would diverge if a future
                # writer set status='refused' but forgot the flag —
                # exactly the divergence we eliminated in the DTO
                # layer in round-1.
                "SELECT COUNT(*) FROM sessions WHERE status != 'refused'"
            ).fetchone()[0]
        return {
            "total": int(total),
            "this_week": int(this_week),
            "continuable": int(continuable),
        }

    def clear(self) -> None:
        """Drop every row — test helper. Production code should not call."""

        with self._tx() as cur:
            cur.execute("DELETE FROM session_turns")
            cur.execute("DELETE FROM sessions")

    def close(self) -> None:
        """Close the underlying sqlite connection — used by tests."""

        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_title(question: str) -> str:
    """Default a session title from the parent question.

    The history list sorts by `updated_at` and shows the title large; a
    full question would wrap awkwardly. 40 chars is enough to disambiguate
    in practice and matches the reference design's truncation. Stripping
    surrounding whitespace + collapsing internal newlines keeps the
    rendered card single-line.
    """

    cleaned = " ".join(question.strip().split())
    if len(cleaned) <= 40:
        return cleaned or "未命名分析"
    return cleaned[:39] + "…"


def _coerce_status(raw: str) -> SessionStatus:
    """Validate a sqlite-stored status string against the closed enum.

    The DB column is plain TEXT (sqlite has no enum type), so a row
    surviving from a future schema — or hand-edited by an operator —
    might contain a value pyright's `Literal` doesn't cover. Failing
    loud on read keeps a corrupted row from silently propagating into
    the API response (where `extra="forbid"` would 500 with a less
    obvious diagnostic). Cheap: one `in` check per row.
    """

    if raw not in ("completed", "refused"):
        raise sqlite3.DatabaseError(
            f"unexpected status value in session row: {raw!r}"
        )
    return raw


def _coerce_kind(raw: str) -> TurnKind:
    """Same closed-enum guard as `_coerce_status`, for `session_turns.kind`."""

    if raw not in ("parent", "follow_up"):
        raise sqlite3.DatabaseError(
            f"unexpected kind value in session_turns row: {raw!r}"
        )
    return raw


def _row_to_summary(row: sqlite3.Row) -> SessionSummary:
    return SessionSummary(
        id=row["id"],
        title=row["title"],
        primary_filename=row["primary_filename"],
        extra_filenames=tuple(json.loads(row["extra_filenames"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        status=_coerce_status(row["status"]),
        is_refusal=bool(row["is_refusal"]),
        follow_up_count=int(row["follow_up_count"]),
        chart_count=row["chart_count"],
        finding_count=row["finding_count"],
    )


def _row_to_turn(row: sqlite3.Row) -> SessionTurnRecord:
    return SessionTurnRecord(
        turn_index=row["turn_index"],
        kind=_coerce_kind(row["kind"]),
        question=row["question"],
        response_id=row["response_id"],
        is_refusal=bool(row["is_refusal"]),
        summary=row["summary"],
        finding_count=row["finding_count"],
        chart_count=row["chart_count"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------
#
# Eager construction at import time would create `./data/sessions.db`
# in CWD the first time *any* test imports a route that touches the
# recorder — most of our pytest runs would leak DB files next to wherever
# the user invoked `pytest` from. Lazy init lets tests inject their own
# instance via `set_session_recorder(...)` (or, equivalently, set
# `TABLETALKER_DATA_DIR` to `tmp_path` before the first call).
#
# Routes call `get_session_recorder()` instead of importing the binding
# directly — that's the seam tests need to stay isolated.

_recorder_lock = threading.Lock()
_recorder: SessionRecorder | None = None


def get_session_recorder() -> SessionRecorder:
    """Return the process-wide recorder, building it on first use."""

    global _recorder
    with _recorder_lock:
        if _recorder is None:
            _recorder = SessionRecorder()
        return _recorder


def set_session_recorder(recorder: SessionRecorder | None) -> None:
    """Test helper — replace (or clear) the module-level singleton.

    Pass `None` to force the next `get_session_recorder()` call to
    rebuild from scratch (useful when a test changed
    `TABLETALKER_DATA_DIR` in os.environ).
    """

    global _recorder
    with _recorder_lock:
        if _recorder is not None and recorder is not _recorder:
            _recorder.close()
        _recorder = recorder


# Backwards-compat alias for callers that prefer the SCREAMING_SNAKE
# style our other singletons use (`SESSION_STORE`, `REPORT_STORE`).
# `SESSION_RECORDER` always proxies through `get_session_recorder()` so
# tests that swap the singleton see consistent behaviour.
class _RecorderProxy:
    """Attribute-forwarding proxy so `SESSION_RECORDER.method(...)` works.

    Avoids capturing the singleton at import time (which would defeat
    the lazy init); every attribute access re-resolves through
    `get_session_recorder()`. Method-call latency is one extra dict
    lookup per call — negligible compared to the LLM round-trip the
    write follows.
    """

    def __getattr__(self, name: str) -> object:
        return getattr(get_session_recorder(), name)


SESSION_RECORDER = _RecorderProxy()
