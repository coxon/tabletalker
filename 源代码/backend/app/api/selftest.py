"""Public-facing self-test report endpoints.

Surfaces the contents of `自测报告/latest_evaluation_metrics.md` through
the same Next.js shell judges already use, so they don't have to grep
the source tree to find the auto-grader file.

Routes
------
- ``GET /v1/self-test/report.html`` — rendered HTML fragment (judges'
  default landing target). Body-only; the frontend wraps it in the
  page chrome.
- ``GET /v1/self-test/report.md`` — raw markdown, served as a download
  for offline reading.
- ``GET /v1/self-test/cases.jsonl`` — per-case results from the run
  the markdown was rendered from, one JSON object per line.
- ``GET /v1/self-test/cases.xlsx`` — same data as a workbook with two
  sheets (``Summary`` + ``Cases``).

The active run directory is parsed from the markdown itself (the
``数据来源`` line containing ``eval/runs/<id>/summary.json``). When the
parse fails - e.g. someone hand-edited the file - we fall back to the
most recently mtime'd subdirectory under ``eval/runs/`` that contains
a ``summary.json``.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import markdown as md_lib
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, Response

router = APIRouter(prefix="/v1/self-test", tags=["self-test"])

# Source-tree layout: api/selftest.py is 4 parents below the repo root
# (api -> app -> backend -> src -> root). In container deployments the
# tree is flattened to /app/app/api/selftest.py (parents[4] doesn't
# exist) and the data dirs are baked at /app/自测报告 + /app/eval/runs
# by the Dockerfile. Try the dev path first, then the container fallback.
_SRC = Path(__file__).resolve()
_DEV_ROOT = _SRC.parents[4] if len(_SRC.parents) > 4 else None
_CONTAINER_ROOT = Path("/app")


def _pick_data_root() -> Path:
    """Choose the path that actually has `自测报告/latest_evaluation_metrics.md`.

    Without this we'd return 404 in the container (parents[4] is bogus)
    even though the file is sitting at /app/自测报告. The fallback chain
    is dev-tree -> container-bake -> /nonexistent (so the route can
    still 404 cleanly when the file is genuinely missing)."""
    for candidate in (_DEV_ROOT, _CONTAINER_ROOT):
        if candidate is None:
            continue
        if (candidate / "自测报告" / "latest_evaluation_metrics.md").exists():
            return candidate
    return Path("/nonexistent")


_REPO_ROOT = _pick_data_root()
_REPORT_MD = _REPO_ROOT / "自测报告" / "latest_evaluation_metrics.md"
_RUNS_DIR = _REPO_ROOT / "eval" / "runs"

# Match the line ``> 数据来源：`eval/runs/<run-id>/summary.json``` (and any
# trailing parenthetical). The path is always relative to the repo root in
# the renderer's output, so we anchor on ``eval/runs/``.
_DATA_SOURCE_RE = re.compile(
    r"`(eval/runs/[^/`]+)/summary\.json`",
)


def _resolve_active_run() -> Path:
    """Find the run directory the live ``latest_evaluation_metrics.md`` was
    rendered from. Falls back to the most recent run dir on the disk."""
    if _REPORT_MD.exists():
        text = _REPORT_MD.read_text(encoding="utf-8")
        m = _DATA_SOURCE_RE.search(text)
        if m:
            run_dir = _REPO_ROOT / m.group(1)
            if (run_dir / "summary.json").exists():
                return run_dir

    # Fallback: pick the most recently modified eval run that has a summary.
    if _RUNS_DIR.exists():
        candidates = [
            d for d in _RUNS_DIR.iterdir()
            if d.is_dir() and (d / "summary.json").exists()
        ]
        if candidates:
            return max(candidates, key=lambda d: d.stat().st_mtime)

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "no eval run available — has the regression been executed?",
    )


def _read_report_md() -> str:
    if not _REPORT_MD.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "自测报告/latest_evaluation_metrics.md is missing",
        )
    return _REPORT_MD.read_text(encoding="utf-8")


@router.get("/report.html", response_class=HTMLResponse)
def report_html() -> HTMLResponse:
    """Return the report rendered as an HTML fragment.

    The frontend ``/self-test`` page injects this via ``dangerouslySetInnerHTML``
    inside the standard page chrome. Judges who load the URL directly get the
    fragment without page chrome — still readable, browsers render it fine."""
    raw_md = _read_report_md()
    html_body = md_lib.markdown(
        raw_md,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html",
    )
    return HTMLResponse(
        content=html_body,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/report.md")
def report_md() -> Response:
    """Return the raw markdown so judges can save it locally."""
    raw_md = _read_report_md()
    return Response(
        content=raw_md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="latest_evaluation_metrics.md"'
            ),
            "Cache-Control": "no-store",
        },
    )


def _load_run_artifacts() -> tuple[Path, dict[str, Any], list[Path]]:
    """Resolve the active run dir and return (path, summary, per_case_files)."""
    run_dir = _resolve_active_run()
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    case_files = sorted(
        p for p in run_dir.glob("*.json")
        if p.name != "summary.json"
    )
    return run_dir, summary, case_files


@router.get("/cases.jsonl")
def cases_jsonl() -> Response:
    """Concatenate per-case JSONs into one JSONL for offline analysis."""
    _, _, case_files = _load_run_artifacts()
    lines: list[str] = []
    for path in case_files:
        # Re-encode with sort_keys so diffs across runs stay stable.
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Skip a malformed file rather than 500 — the grader should
            # still see the rest of the cases.
            continue
        lines.append(json.dumps(obj, ensure_ascii=False, sort_keys=True))
    body = "\n".join(lines).encode("utf-8") + b"\n"
    return Response(
        content=body,
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="self_test_cases.jsonl"',
            "Cache-Control": "no-store",
        },
    )


def _summary_rows(summary: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten the summary header + metrics block into (key, value) rows."""
    rows: list[tuple[str, str]] = []
    for key in ("backend", "started_at", "completed_at"):
        if key in summary:
            rows.append((key, str(summary[key])))
    metrics = summary.get("metrics") or {}
    if isinstance(metrics, dict):
        for k, v in metrics.items():
            if isinstance(v, (dict, list)):
                rows.append((f"metrics.{k}", json.dumps(v, ensure_ascii=False)))
            else:
                rows.append((f"metrics.{k}", "" if v is None else str(v)))
    return rows


def _case_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Pick a stable subset of per-case fields suitable for a worksheet."""
    cases = summary.get("cases") or []
    if not isinstance(cases, list):
        return []
    rows: list[dict[str, Any]] = []
    for c in cases:
        if not isinstance(c, dict):
            continue

        def _stage_status(stage: object) -> str:
            if not isinstance(stage, dict):
                return ""
            code = stage.get("status_code")
            err = stage.get("error")
            if err:
                return f"error: {err}"
            return "" if code is None else str(code)

        rows.append({
            "case_id": c.get("case_id", ""),
            "primary_file": c.get("primary_file", ""),
            "extra_file_count": c.get("extra_file_count", 0),
            "main_status": _stage_status(c.get("main")),
            "followup_status": _stage_status(c.get("followup")),
            "trap_status": _stage_status(c.get("trap")),
            "trap_expected_refusal": c.get("trap_expected_refusal", ""),
        })
    return rows


@router.get("/cases.xlsx")
def cases_xlsx() -> Response:
    """Two-sheet workbook (Summary, Cases) for judges who prefer Excel."""
    from openpyxl import Workbook  # local import — heavy startup cost.

    _, summary, _ = _load_run_artifacts()

    wb = Workbook()
    summary_ws = wb.active
    assert summary_ws is not None  # for pyright; openpyxl always seeds one
    summary_ws.title = "Summary"
    summary_ws.append(["指标", "值"])
    for k, v in _summary_rows(summary):
        summary_ws.append([k, v])

    cases_ws = wb.create_sheet("Cases")
    case_rows = _case_rows(summary)
    if case_rows:
        headers = list(case_rows[0].keys())
        cases_ws.append(headers)
        for row in case_rows:
            cases_ws.append([row.get(h, "") for h in headers])
    else:
        cases_ws.append(["(no per-case rows in summary.json)"])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="self_test_cases.xlsx"',
            "Cache-Control": "no-store",
        },
    )
