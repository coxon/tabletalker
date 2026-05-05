"""GET /reports/{id}.html — serve a previously-rendered analyze report.

The submission contract (§2) lists `report_html_url` alongside the two
analyze endpoints as the third route the grader hits. The handler stores
the rendered HTML in `app.report.REPORT_STORE` keyed by `request_id`;
this route is a thin lookup over that store.

We deliberately do NOT prefix this router (`/reports/{id}.html` is the
exact URL shape the contract calls out — see `docs/submission-contract.md`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse

from app.report import REPORT_STORE

router = APIRouter(tags=["reports"])


@router.get("/reports/{report_id}.html", response_class=HTMLResponse)
def get_report(report_id: str) -> HTMLResponse:
    """Return the HTML report for a given analyze request id, or 404."""

    html = REPORT_STORE.get(report_id)
    if html is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"report {report_id!r} not found (expired or never produced)",
        )
    # `Cache-Control: no-store` — reports are tied to a single request id
    # and contain user-uploaded data; we don't want intermediate caches
    # to retain them.
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-store"},
    )
