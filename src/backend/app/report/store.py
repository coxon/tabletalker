"""In-memory report store keyed by `request_id`.

The grader fetches `report_html_url` via a follow-up GET — usually within
seconds of the analyze response. Persisting the HTML to disk would buy us
nothing for the eval window and adds a cleanup race; an in-process dict
is the simplest thing that works for the demo and the public eval.

Capacity is bounded so a long-running test fixture (or a misconfigured
production deploy) can't pin gigabytes of HTML in memory. When we trip
the cap, the oldest entries are evicted FIFO — never the newest, which
the grader may still be in the middle of fetching.

**Single-worker assumption.** The store is module-level state, so a
multi-worker uvicorn / gunicorn deploy will land `POST /v1/analyze` and
`GET /reports/{id}.html` on different processes and serve 404s. We
accept that for the hackathon (the eval submission runs single-worker;
see `Makefile`'s `dev` target) and warn loudly on import if the env
suggests otherwise. Promoting this to Redis is tracked under PR #6+
roadmap notes.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict

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


class ReportStore:
    """Thread-safe FIFO cache of `request_id -> html` strings.

    `max_entries` is intentionally small for the demo (256 reports ≈ a
    few MiB). Bump it via `app.report.REPORT_STORE.max_entries = N` if
    we ever need to.
    """

    def __init__(self, *, max_entries: int = 256) -> None:
        # Defensive — a zero or negative cap would let `_items` grow,
        # then trip a KeyError in `popitem` on the very first put.
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError(
                f"max_entries must be a positive int, got {max_entries!r}"
            )
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._items: OrderedDict[str, str] = OrderedDict()

    def put(self, report_id: str, html: str) -> None:
        with self._lock:
            # Re-puts move the entry to the back (it's the freshest).
            if report_id in self._items:
                self._items.move_to_end(report_id)
            self._items[report_id] = html
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def get(self, report_id: str) -> str | None:
        with self._lock:
            return self._items.get(report_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        """Test helper — drop every entry. Production code should not call."""
        with self._lock:
            self._items.clear()


# Module-level singleton — the handler writes to this on every analyze
# response, the route reads from it on every GET. Importing this directly
# rather than passing it as a dependency keeps the wiring tiny; tests
# call `.clear()` between cases.
REPORT_STORE = ReportStore()
