"""Report rendering — HTML report builder for `report_html_url`.

The submission contract (`docs/submission-contract.md` §2) requires every
analyze response to point at a rendered HTML report. This package owns
that artefact end-to-end:

  - `charts` — pure SVG chart builders (bar/line/pie). No JS, no remote
    CDNs; the eval network may block them.
  - `render` — Jinja-based HTML composition + the chart-anchor invariant
    check (every `Chart.html_anchor` must correspond to a `<div id=...>`).
  - `store` — in-memory id → HTML cache so the `GET /reports/{id}.html`
    route can return the freshly-rendered document.
"""

from app.report.charts import ChartImage, build_chart, supported_chart_types
from app.report.render import RenderedReport, render_report
from app.report.store import REPORT_STORE, ReportStore

__all__ = [
    "REPORT_STORE",
    "ChartImage",
    "RenderedReport",
    "ReportStore",
    "build_chart",
    "render_report",
    "supported_chart_types",
]
