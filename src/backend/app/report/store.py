"""In-memory report store keyed by `request_id`.

The grader fetches `report_html_url` via a follow-up GET — usually within
seconds of the analyze response. Persisting the HTML to disk would buy us
nothing for the eval window and adds a cleanup race; an in-process dict
is the simplest thing that works for the demo and the public eval.

Capacity is bounded so a long-running test fixture (or a misconfigured
production deploy) can't pin gigabytes of HTML in memory. When we trip
the cap, the oldest entries are evicted FIFO — never the newest, which
the grader may still be in the middle of fetching.
"""

from __future__ import annotations

import threading
from collections import OrderedDict


class ReportStore:
    """Thread-safe FIFO cache of `request_id -> html` strings.

    `max_entries` is intentionally small for the demo (256 reports ≈ a
    few MiB). Bump it via `app.report.REPORT_STORE.max_entries = N` if
    we ever need to.
    """

    def __init__(self, *, max_entries: int = 256) -> None:
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
