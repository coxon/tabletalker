"""Report store keyed by `request_id` — memory-first, optional disk
spillover.

The grader fetches `report_html_url` via a follow-up GET — usually within
seconds of the analyze response — so the in-process FIFO cache covers
the eval window with no I/O. Without disk spillover, however, a pod
restart between analyze and the GET (k8s rolls, OOM, image bump, etc.)
serves a 404 for every report id minted by the prior pod. That's a
real submission risk: judges keep tabs open across restarts.

When `disk_dir` is set, every `put()` ALSO writes `<disk_dir>/<id>.html`
to disk; `get()` falls back to disk on cache miss and re-warms memory.
With `disk_dir` pointing at the k8s PVC mount (`/app/data/reports`),
old report ids stay reachable across pod restarts. The disk write is
best-effort — a failure is logged but doesn't bubble to the analyze
handler (the in-memory copy still serves the immediate GET).

Capacity is bounded so a long-running test fixture (or a misconfigured
production deploy) can't pin gigabytes of HTML in memory. When we trip
the cap, the oldest entries are evicted FIFO from memory — disk copies
stay until manually purged. There's no auto-eviction on disk; for the
hackathon's expected volume that's fine, but a Redis or S3 backend
would be the next step.

**Single-worker assumption.** The store is module-level state, so a
multi-worker uvicorn / gunicorn deploy will land `POST /v1/analyze` and
`GET /reports/{id}.html` on different processes. With `disk_dir` set
the disk fallback covers this too — both workers see the same dir —
but per-process memory caches still drift.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)


def _warn_if_multi_worker() -> None:
    """Emit a warning if the process env points at >1 worker.

    Checks the conventional knobs (`WEB_CONCURRENCY`, `GUNICORN_WORKERS`)
    so a CI or prod deploy at least surfaces the inconsistency in logs.
    """

    for var in ("WEB_CONCURRENCY", "GUNICORN_WORKERS"):
        raw = os.environ.get(var)
        if raw is None:
            continue
        try:
            n = int(raw)
        except ValueError:
            continue
        if n > 1:
            logger.warning(
                "%s=%d but app.report.store uses in-process state — "
                "GET /reports/{id}.html will 404 for requests routed to "
                "a different worker. See app/report/store.py docstring.",
                var,
                n,
            )


_warn_if_multi_worker()


# Whitelist for the report id used as a filename. The id is generated
# server-side (`make_request_id` / `make_followup_id`), but the get()
# entry-point comes from a URL path component — defence-in-depth so a
# crafted id can't traverse out of `disk_dir`.
_ID_OK_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def _is_safe_id(report_id: str) -> bool:
    return (
        bool(report_id)
        and len(report_id) <= 128
        and all(ch in _ID_OK_CHARS for ch in report_id)
    )


class ReportStore:
    """Thread-safe FIFO memory cache of `request_id -> html` strings,
    with optional disk spillover at `<disk_dir>/<id>.html`.

    `max_entries` caps in-memory entries (256 reports ≈ a few MiB).
    `disk_dir` enables persistence — typically the k8s PVC mount; pass
    `None` (default) for the legacy in-memory-only behaviour the test
    suite relies on.
    """

    def __init__(
        self,
        *,
        max_entries: int = 256,
        disk_dir: Path | None = None,
    ) -> None:
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError(
                f"max_entries must be a positive int, got {max_entries!r}"
            )
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._items: OrderedDict[str, str] = OrderedDict()
        self._disk_dir = disk_dir
        if disk_dir is not None:
            try:
                disk_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                # Don't crash the import if the dir can't be created
                # (e.g. PVC not mounted in dev) — just disable disk
                # spillover and log so the deployer notices.
                logger.warning(
                    "ReportStore: disk_dir %s unavailable (%s); falling back "
                    "to memory-only — old report ids will 404 after a pod "
                    "restart.",
                    disk_dir,
                    exc,
                )
                self._disk_dir = None

    def put(self, report_id: str, html: str) -> None:
        with self._lock:
            # Re-puts move the entry to the back (it's the freshest).
            if report_id in self._items:
                self._items.move_to_end(report_id)
            self._items[report_id] = html
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
        # Disk write outside the lock — best-effort, swallow errors so a
        # transient ENOSPC on the PVC doesn't 500 the analyze response.
        if self._disk_dir is not None and _is_safe_id(report_id):
            target = self._disk_dir / f"{report_id}.html"
            try:
                target.write_text(html, encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    "ReportStore: disk write for %s failed: %s",
                    report_id, exc,
                )

    def get(self, report_id: str) -> str | None:
        with self._lock:
            cached = self._items.get(report_id)
        if cached is not None:
            return cached
        # Memory miss — try disk if enabled.
        if self._disk_dir is None or not _is_safe_id(report_id):
            return None
        target = self._disk_dir / f"{report_id}.html"
        try:
            html = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning(
                "ReportStore: disk read for %s failed: %s",
                report_id, exc,
            )
            return None
        # Re-warm memory so subsequent gets skip disk.
        with self._lock:
            self._items[report_id] = html
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
        return html

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        """Test helper — drop every entry. Production code should not call.

        Disk entries are NOT touched here; tests don't configure
        disk_dir, so there's nothing to clean."""
        with self._lock:
            self._items.clear()


def _resolve_disk_dir() -> Path | None:
    """Return the directory for disk spillover, or `None` to stay
    memory-only.

    Selection rules (highest precedence first):
      1. `TABLETALKER_REPORTS_DIR` env var — explicit override.
      2. `/app/data/reports` — auto-detected k8s/compose PVC mount.
      3. `None` — legacy behaviour for dev (just memory).
    """
    explicit = os.environ.get("TABLETALKER_REPORTS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    pvc_mount = Path("/app/data")
    if pvc_mount.is_dir():
        return pvc_mount / "reports"
    return None


# Module-level singleton — the handler writes to this on every analyze
# response, the route reads from it on every GET.
REPORT_STORE = ReportStore(disk_dir=_resolve_disk_dir())
