"""GET /v1/self-test/* route smoke tests.

The judges' /self-test page hits these endpoints; a crash here means a
404/500 lands in front of the auto-grader. Cover the happy path on the
real `自测报告/` file, plus the 404 / 503 fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import selftest as selftest_module
from app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_MD = _REPO_ROOT / "自测报告" / "latest_evaluation_metrics.md"


def test_report_html_renders_real_file() -> None:
    """The renderer must turn the live markdown into HTML that contains
    at least one `<table>` (the auto-grader file always has scoring tables).
    If this regresses, judges open `/self-test` to a blank panel."""
    if not _REAL_MD.exists():
        # File is mandatory per CLAUDE.md project rule #2 — its absence
        # is a real regression (someone deleted the submission artefact),
        # not a "skip silently because dev box". Use pytest.skip so the
        # CI report shows a SKIPPED with a loud reason instead of a
        # silent green pass that masks the missing file.
        pytest.skip(f"missing required artefact: {_REAL_MD}")

    with TestClient(app) as client:
        resp = client.get("/v1/self-test/report.html")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers.get("cache-control") == "no-store"
    body = resp.text
    assert "<table>" in body, "tables extension must turn `|` rows into <table>"
    assert "<h1>" in body or "<h2>" in body


def test_report_md_serves_raw_with_attachment_header() -> None:
    if not _REAL_MD.exists():
        pytest.skip(f"missing required artefact: {_REAL_MD}")

    with TestClient(app) as client:
        resp = client.get("/v1/self-test/report.md")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    # Sanity: body should match the file on disk byte-for-byte (UTF-8).
    assert resp.content == _REAL_MD.read_bytes()


def test_report_md_404_when_file_missing(monkeypatch, tmp_path: Path) -> None:
    """If `自测报告/latest_evaluation_metrics.md` is deleted, the route must
    404 cleanly — never 500. (Possible on a clean docker checkout that
    stripped CN dirs.)"""

    fake = tmp_path / "missing.md"
    monkeypatch.setattr(selftest_module, "_REPORT_MD", fake)

    with TestClient(app) as client:
        resp = client.get("/v1/self-test/report.md")

    assert resp.status_code == 404


def test_cases_jsonl_emits_one_line_per_case(tmp_path: Path, monkeypatch) -> None:
    """Build a fake run dir with two per-case JSONs, point the resolver at
    it, and confirm the JSONL has exactly two lines that round-trip."""

    run_dir = tmp_path / "fakerun"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps({"backend": "x", "cases": [], "metrics": {}}),
        encoding="utf-8",
    )
    case_a = {"case_id": "01_a", "main": {"status_code": 200}}
    case_b = {"case_id": "02_b", "main": {"status_code": 200}}
    (run_dir / "01_a.json").write_text(
        json.dumps(case_a, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "02_b.json").write_text(
        json.dumps(case_b, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(selftest_module, "_resolve_active_run", lambda: run_dir)

    with TestClient(app) as client:
        resp = client.get("/v1/self-test/cases.jsonl")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [
        line for line in resp.text.split("\n") if line.strip()
    ]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    case_ids = {p["case_id"] for p in parsed}
    assert case_ids == {"01_a", "02_b"}


def test_cases_xlsx_returns_workbook(tmp_path: Path, monkeypatch) -> None:
    """Confirm the route hands back a real openpyxl-readable workbook with
    both sheets present — judges who download this expect a file Excel can
    open without complaint."""
    from openpyxl import load_workbook

    run_dir = tmp_path / "fakerun"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps({
            "backend": "x",
            "cases": [
                {
                    "case_id": "01_a",
                    "main": {"status_code": 200},
                    "followup": {"status_code": 200},
                    "trap": {"status_code": 200},
                    "trap_expected_refusal": True,
                }
            ],
            "metrics": {"main_pass_rate": 0.9},
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(selftest_module, "_resolve_active_run", lambda: run_dir)

    with TestClient(app) as client:
        resp = client.get("/v1/self-test/cases.xlsx")

    assert resp.status_code == 200
    assert "openxmlformats" in resp.headers["content-type"]

    out = tmp_path / "out.xlsx"
    out.write_bytes(resp.content)
    wb = load_workbook(out)
    assert wb.sheetnames == ["Summary", "Cases"]
    cases_ws = wb["Cases"]
    assert cases_ws.max_row >= 2  # header + at least one row
    # Header row must include the columns judges depend on.
    headers_row = [c.value for c in cases_ws[1]]
    assert "case_id" in headers_row
    assert "main_status" in headers_row
