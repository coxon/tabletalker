"""End-to-end tests for POST /v1/batch.

The LLM is stubbed (sequenced fake) so the runner round-trips through
the real `handle_analyze` pipeline without burning a real API call. The
xlsx output is parsed back via openpyxl so assertions key on
spreadsheet-shape data, not the binary blob.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import app.api.batch as batch_module
from app.main import app


class _SequencedStubClient:
    """Same shape as the analyze tests' stub — serves a list of pre-baked
    LLM responses in order. A batch of N happy-path tasks needs 2*N
    responses (planner + finalize per task)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls += 1
        if not self._responses:
            raise AssertionError(f"unexpected extra LLM call #{self.calls}")
        return self._responses.pop(0)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("LLM_BASE_URL", "https://stub.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    yield TestClient(app)


def _csv_bytes() -> bytes:
    return (
        b"region,amount\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,100\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,200\n"
        b"\xe5\x8d\x8e\xe5\x8d\x97,50\n"
        b"\xe5\x8d\x8e\xe5\x8c\x97,75\n"
    )


def _plan_json() -> str:
    return json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                {"kind": "group_by", "out": "g", "src": "raw", "by": ["region"]},
                {
                    "kind": "aggregate",
                    "out": "totals",
                    "src": "g",
                    "aggs": [{"column": "amount", "fn": "sum", "as": "total"}],
                },
                {"kind": "to_table", "out": "answer", "src": "totals"},
            ],
            "answer": "answer",
        }
    )


def _narrative_json() -> str:
    return json.dumps(
        {
            "summary": "华东总额 300，华南 50。建议加大华南促销。",
            "title": "华东销售领先",
            "detail": "华东 300，华南 50。",
            "recommendations": ["加大华南促销"],
            "confidence": 0.85,
        }
    )


# ---------------------------------------------------------------------------
# Happy path: JSONL manifest, two tasks, xlsx round-trip
# ---------------------------------------------------------------------------


def test_batch_runs_jsonl_manifest_and_returns_xlsx(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two-task JSONL manifest → run both → return an xlsx whose
    `summary` and `evidence` sheets reflect the pipeline output.

    Each task burns 2 LLM calls (planner + finalize), so the stub seeds
    4 responses total. The assertion set covers: response status code,
    workbook structure, both summary rows present, finding/evidence
    counts, and that error rows would surface if any (none here)."""

    stub = _SequencedStubClient(
        [_plan_json(), _narrative_json(), _plan_json(), _narrative_json()]
    )
    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)

    manifest = (
        json.dumps({"question": "各地区的总销售额是多少？", "file": "sales.csv"})
        + "\n"
        + json.dumps({"id": "task-y", "question": "再算一次", "file": "sales.csv"})
    ).encode("utf-8")

    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Batch-Tasks"] == "2"
    assert response.headers["X-Batch-Errors"] == "0"
    # Content-Disposition triggers a download in the browser.
    assert "attachment" in response.headers["Content-Disposition"]

    wb = load_workbook(io.BytesIO(response.content))
    assert wb.sheetnames == ["summary", "evidence"]

    summary = wb["summary"]
    # 1 header + 2 data rows.
    assert summary.max_row == 3
    headers = [summary.cell(row=1, column=c).value for c in range(1, summary.max_column + 1)]
    assert "task_id" in headers and "is_refusal" in headers and "summary" in headers
    # Rows are written in manifest order; second row's id was set explicitly.
    task_ids = [summary.cell(row=r, column=1).value for r in (2, 3)]
    assert task_ids == ["task_1", "task-y"]

    # Evidence sheet has at least 2 rows of evidence per task (count(*)
    # baseline + per-group rows). 2 tasks × ≥4 evidence rows = ≥8.
    evidence = wb["evidence"]
    assert evidence.max_row >= 1 + 8

    # 4 LLM calls fired (2 per task × 2 tasks).
    assert stub.calls == 4


# ---------------------------------------------------------------------------
# Error capture: a single bad task must NOT abort the batch
# ---------------------------------------------------------------------------


def test_batch_captures_per_task_errors_without_aborting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 1 succeeds, task 2's planner emits a malformed plan that
    fails ALL retries → its row carries `status=error`, but the workbook
    still includes task 1's full result.

    Regression target: an early implementation re-raised AnalyzeFailure
    out of the runner, killing the rest of the batch. The runner now
    captures per-task; this test pins that behaviour.
    """

    # Task 1: 2 valid responses (planner + finalize).
    # Task 2: 3 invalid responses (planner exhausts MAX_PLAN_RETRIES = 2,
    #         so 3 attempts total all return non-JSON).
    stub = _SequencedStubClient(
        [
            _plan_json(),
            _narrative_json(),
            "not json",
            "still not json",
            "definitely not json",
        ]
    )
    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)

    manifest = (
        json.dumps({"id": "good", "question": "OK", "file": "sales.csv"})
        + "\n"
        + json.dumps({"id": "bad", "question": "BROKEN", "file": "sales.csv"})
    ).encode("utf-8")

    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Batch-Errors"] == "1"

    wb = load_workbook(io.BytesIO(response.content))
    summary = wb["summary"]
    rows_by_id = {
        summary.cell(row=r, column=1).value: {
            summary.cell(row=1, column=c).value: summary.cell(row=r, column=c).value
            for c in range(1, summary.max_column + 1)
        }
        for r in range(2, summary.max_row + 1)
    }
    assert rows_by_id["good"]["status"] == "ok"
    assert rows_by_id["bad"]["status"] == "error"
    assert rows_by_id["bad"]["error"]  # carries the diagnostic
    # Summary text only present for the OK task.
    assert rows_by_id["good"]["summary"]
    assert rows_by_id["bad"]["summary"] in ("", None)


# ---------------------------------------------------------------------------
# Validation: manifest references file not uploaded
# ---------------------------------------------------------------------------


def test_batch_rejects_when_manifest_references_unknown_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-flight failure: manifest mentions `nope.csv` which we never
    received. Must 400 with the missing names listed — no LLM calls."""

    stub = _SequencedStubClient([])
    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)

    manifest = json.dumps({"question": "Q", "file": "nope.csv"}).encode("utf-8")
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 400, response.text
    assert "nope.csv" in response.json()["detail"]
    assert stub.calls == 0


def test_batch_rejects_malformed_manifest(client: TestClient) -> None:
    """A manifest with a bad row → 400 with row-numbered diagnostic.

    The route should never let a `ManifestError` leak as a 500 — that
    would tell the evaluator the *system* is broken when in fact their
    input is fixable.
    """
    bad = b'{"question": "Q1", "file": "a.csv"}\n{this is not json}\n'
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", bad, "application/x-ndjson")),
            ("files", ("a.csv", b"x,y\n1,2\n", "text/csv")),
        ],
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "line 2" in detail


def test_batch_rejects_extra_files_wrong_type(client: TestClient) -> None:
    """`extra_files: 123` (a non-string, non-iterable) must surface as a
    400 with the row label, not a 500 from `TypeError` deeper in the
    parser. CodeRabbit #16: prevents silent regression to 500s on
    grader-side input mistakes.
    """
    bad = (
        b'{"question": "Q1", "file": "a.csv"}\n'
        b'{"question": "Q2", "file": "a.csv", "extra_files": 123}\n'
    )
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", bad, "application/x-ndjson")),
            ("files", ("a.csv", b"x,y\n1,2\n", "text/csv")),
        ],
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    # Both diagnostics must be present so the grader fixing the manifest
    # knows where to look (line 2) and what's wrong (extra_files type).
    assert "line 2" in detail
    assert "extra_files" in detail


def test_batch_runs_csv_manifest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CSV manifest path is feature-equivalent to JSONL.

    Evaluators editing in Excel/Numbers prefer CSV; this pins that the
    parser strips the BOM (utf-8-sig), supports `;`-separated extras,
    and produces the same `BatchTask` shape as JSONL."""

    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)

    manifest = (
        b"\xef\xbb\xbf"  # UTF-8 BOM (Excel adds this)
        b"question,file,id,sampling_rate\n"
        b"\xe5\x90\x84\xe5\x9c\xb0\xe5\x8c\xba\xe7\x9a\x84\xe6\x80\xbb\xe9\x94\x80\xe5\x94\xae,sales.csv,case-1,0.5\n"
    )
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.csv", manifest, "text/csv")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    wb = load_workbook(io.BytesIO(response.content))
    summary = wb["summary"]
    assert summary.cell(row=2, column=1).value == "case-1"
    # sampling_rate column propagates through to the row.
    headers = [
        summary.cell(row=1, column=c).value
        for c in range(1, summary.max_column + 1)
    ]
    rate_col = headers.index("sampling_rate") + 1
    assert summary.cell(row=2, column=rate_col).value == 0.5


# ---------------------------------------------------------------------------
# Misc guards
# ---------------------------------------------------------------------------


def test_batch_returns_503_when_llm_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the LLM env isn't set, the route fails before running any
    task — same 503 contract as `/v1/analyze`."""

    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    manifest = json.dumps({"question": "Q", "file": "sales.csv"}).encode("utf-8")
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# CodeRabbit #16 round-6 contract tests
# ---------------------------------------------------------------------------


def test_batch_skips_uploads_not_referenced_by_manifest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An evaluator who attaches extras the manifest doesn't reference
    (sensitive logs, stale fixtures) must not have those files written
    to /tmp. The route filters uploads to the referenced set first.

    Round-8 (CodeRabbit #16): assert *which* files reached the
    persistence layer by intercepting `_save_upload`. Without this
    intercept the test would have passed even if the route streamed
    every upload to disk and only filtered downstream — the response
    body would still be the same. We need a positive assertion that
    `secrets.csv` and `logs.csv` never touched the workspace.
    """
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])

    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)
    saved: list[str] = []
    real_save_upload = batch_module._save_upload

    async def _spy_save_upload(file: Any, target: Any) -> None:
        saved.append(target.name)
        return await real_save_upload(file, target)

    monkeypatch.setattr(batch_module, "_save_upload", _spy_save_upload)

    manifest = json.dumps({"question": "Q1", "file": "sales.csv"}).encode("utf-8")
    # Send 3 files; manifest only references sales.csv.
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
            # These two are noise — the route must persist neither.
            ("files", ("secrets.csv", b"key,value\nA,1\n", "text/csv")),
            ("files", ("logs.csv", b"ts,msg\n1,bad\n", "text/csv")),
        ],
    )
    # The manifest is satisfied → 200 + xlsx returned.
    assert response.status_code == 200, response.text
    assert response.headers["X-Batch-Tasks"] == "1"
    # Positive shape: only the referenced file ever reached the disk.
    assert saved == ["sales.csv"], (
        f"only manifest-referenced files must be persisted; got {saved!r}"
    )


def test_batch_rejects_non_utf8_manifest(client: TestClient) -> None:
    """A manifest with bad encoding must fail closed with a 400 — silent
    UTF-8 replacement masked typos in earlier rounds and fed garbled
    questions to the LLM.
    """
    # GBK-encoded Chinese — looks valid in some WeChat exports but is
    # not UTF-8 and would have been corrupted by `errors="replace"`.
    bad_bytes = "你好,sales.csv\n".encode("gbk")
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", bad_bytes, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 400, response.text
    assert "UTF-8" in response.json()["detail"]


def test_batch_rejects_duplicate_task_ids(client: TestClient) -> None:
    """Two manifest rows with the same `id` would shadow each other in
    any id-keyed downstream view. Surface a single 400 with the
    duplicate ids listed so the evaluator can fix the manifest.
    """
    rows = [
        {"id": "T1", "question": "Q1", "file": "sales.csv"},
        {"id": "T2", "question": "Q2", "file": "sales.csv"},
        # Collision with T1 — must be rejected.
        {"id": "T1", "question": "Q3", "file": "sales.csv"},
    ]
    manifest = b"\n".join(json.dumps(r).encode("utf-8") for r in rows)
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "duplicate" in detail.lower()
    assert "T1" in detail


def test_batch_xlsx_escapes_formula_like_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attacker-controlled fields prefixed with `=`/`+`/`-`/`@` must be
    written as text in the xlsx (single-quote prefix), not evaluated as
    formulas when the evaluator opens the workbook.
    """
    # Plan + narrative: stuff the malicious prefix into the summary.
    plan = _plan_json()
    narrative_with_attack = json.dumps(
        {
            "summary": "=HYPERLINK(\"http://attacker/\", \"click\")"
            + ("华东 300，华南 50，差距明显。" * 17),
            "title": "+CMD",
            "detail": "@SUM(A1:A10)",
            "recommendations": ["-DROP TABLE users;--"],
            "confidence": 0.5,
        }
    )
    stub = _SequencedStubClient([plan, narrative_with_attack])
    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)

    manifest = json.dumps(
        {
            "id": "=evil",
            "question": "+evil",
            "file": "sales.csv",
        }
    ).encode("utf-8")
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    # Pull out the xlsx and assert formula-shaped fields were quoted.
    wb = load_workbook(io.BytesIO(response.content))
    summary_ws = wb["summary"]
    # Round-9 (CodeRabbit #16): map header → column index instead of
    # hardcoding column positions, so a future column reorder doesn't
    # silently make this test assert against the wrong cells.
    headers = [
        summary_ws.cell(row=1, column=c).value
        for c in range(1, summary_ws.max_column + 1)
    ]
    col = {name: idx + 1 for idx, name in enumerate(headers)}
    id_cell = summary_ws.cell(row=2, column=col["task_id"]).value
    question_cell = summary_ws.cell(row=2, column=col["question"]).value
    summary_cell = summary_ws.cell(row=2, column=col["summary"]).value
    assert id_cell == "'=evil"  # quoted
    assert question_cell == "'+evil"
    # `summary` field still starts with `=HYPERLINK(...)` after quoting.
    assert isinstance(summary_cell, str) and summary_cell.startswith("'=HYPERLINK")


def test_batch_rejects_boolean_sampling_rate(client: TestClient) -> None:
    """A manifest with `"sampling_rate": true` must fail closed —
    `bool` is a subclass of `int`, so without an explicit guard the
    `_parse_optional_float` helper would silently coerce `true` to
    `1.0` (i.e. "we sampled 100%"). Round-8 (CodeRabbit #16).
    """
    manifest = json.dumps(
        {"question": "Q1", "file": "sales.csv", "sampling_rate": True}
    ).encode("utf-8")
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 400, response.text
    assert "sampling_rate" in response.text
    assert "boolean" in response.text


def test_batch_safe_filename_normalises_windows_paths(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-8 (CodeRabbit #16): `_safe_filename` must collapse
    backslash-separated Windows paths (like the ones some grader
    upload tools produce) to their basename so the manifest reference
    comparison succeeds.
    """
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)

    manifest = json.dumps({"question": "Q1", "file": "sales.csv"}).encode("utf-8")
    # The grader's UA submits the file with its full Windows path.
    # The route must normalise backslashes BEFORE comparing against
    # the manifest's bare-filename reference.
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("C:\\Users\\grader\\sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Batch-Tasks"] == "1"


async def test_save_upload_atomic_on_size_cap_breach(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Round-11 (CodeRabbit #16): if the upload busts UPLOAD_MAX_BYTES
    mid-stream, no partially-written file may remain at ``target``.

    The implementation writes to ``target.with_suffix('.part')`` and
    only renames to ``target`` on success. This test breaches the cap
    by stubbing ``UPLOAD_MAX_BYTES`` down to 4 bytes and feeding 16 —
    the 413 must come back, the ``.part`` sidecar must be cleaned, and
    ``target`` must NOT exist.
    """
    from fastapi import HTTPException

    import app.api.batch as _batch_module
    import app.limits as _limits_module

    monkeypatch.setattr(_limits_module, "UPLOAD_MAX_BYTES", 4)
    monkeypatch.setattr(_batch_module, "UPLOAD_MAX_BYTES", 4)

    class _FakeUpload:
        def __init__(self, payload: bytes, chunk_size: int) -> None:
            self._buf = payload
            self._idx = 0
            self._chunk = chunk_size

        async def read(self, _: int) -> bytes:
            chunk = self._buf[self._idx : self._idx + self._chunk]
            self._idx += self._chunk
            return chunk

    target = tmp_path / "x.csv"
    fake = _FakeUpload(b"AAAABBBBCCCCDDDD", chunk_size=2)

    with pytest.raises(HTTPException) as exc:
        await _batch_module._save_upload(fake, target)  # type: ignore[arg-type]
    assert exc.value.status_code == 413

    # Both target and the temp sidecar should be cleaned up.
    assert not target.exists(), "no partial file may remain at the target path"
    assert not (target.with_suffix(target.suffix + ".part")).exists(), (
        "the .part temp file must be unlinked on failure"
    )


# ---------------------------------------------------------------------------
# Round-14 (CodeRabbit #16): defensive manifest shape + non-leaking errors
# ---------------------------------------------------------------------------


def test_batch_csv_manifest_extra_column_overflow_does_not_500() -> None:
    """csv.DictReader yields ``{None: [...]}`` for extra-column rows.

    The old blank-row predicate was ``(v or "").strip()`` which blows up
    with ``AttributeError`` on the list produced by overflow. That is
    user-triggered input (a stray trailing comma in a data row), so the
    crash becomes a 500. The type-safe predicate must treat the list as
    "some elements present → row is NOT blank" and let the row be
    processed (or raise a clean `ManifestError` downstream for the shape
    violation), never surfacing as a 500.
    """
    from app.batch import parse_manifest

    # Header has 3 columns but the only data row has 5 → DictReader stashes
    # the extras under key `None` as a list.
    raw = (
        b"question,file,id\n"
        b"Q1,sales.csv,T1,oops,extra\n"
    )
    # Must not raise AttributeError / TypeError — either parses cleanly
    # (ignoring the overflow, since parse logic drops ``None`` keys) or
    # raises a typed ManifestError. Anything else is a regression.
    tasks = parse_manifest(raw, "m.csv")
    assert len(tasks) == 1
    assert tasks[0].id == "T1"
    assert tasks[0].question == "Q1"


def test_batch_csv_manifest_rejects_whitespace_only_task_id() -> None:
    """An ``id`` cell of ``"   "`` used to become the BatchTask id verbatim
    (``"   "`` → stripped to ``""``), silently colliding across rows.
    The fix normalises first, treats stripped-empty as missing, and
    falls back to the synthetic ``task_<index>`` id.
    """
    from app.batch import parse_manifest

    raw = (
        b"question,file,id\n"
        b"Q1,sales.csv,   \n"
        b"Q2,sales.csv,\n"
    )
    tasks = parse_manifest(raw, "m.csv")
    assert len(tasks) == 2
    # Both rows have blank id → synthetic ids; neither is the empty string.
    assert tasks[0].id and tasks[1].id
    assert tasks[0].id != tasks[1].id, (
        "whitespace-only ids must not collide with each other"
    )
    assert tasks[0].id.startswith("task_")
    assert tasks[1].id.startswith("task_")


def test_batch_crash_error_is_not_leaky(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected exceptions in `run_batch` must surface a coarse,
    non-sensitive label in the xlsx; internal repr (which may carry
    temp paths, LLM URLs, config values) stays in the log only.
    """
    class _BoomClient:
        def __init__(self, _config: object) -> None:
            pass

        async def chat(self, *args: object, **kwargs: object) -> str:
            raise RuntimeError(
                "secret-in-repr: /tmp/batch-xyz/.env "
                "https://internal-llm.corp/v1"
            )

    monkeypatch.setattr(batch_module, "HttpChatClient", _BoomClient)

    manifest = json.dumps({"question": "Q1", "file": "sales.csv"}).encode("utf-8")
    response = client.post(
        "/v1/batch",
        files=[
            ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
            ("files", ("sales.csv", _csv_bytes(), "text/csv")),
        ],
    )
    # The batch run itself doesn't fail — individual task failures are
    # captured per-row in the xlsx.
    assert response.status_code == 200, response.text
    wb = load_workbook(io.BytesIO(response.content))
    summary = wb["summary"]
    # Find the error column and read row 2's cell.
    headers = [
        summary.cell(row=1, column=c).value
        for c in range(1, summary.max_column + 1)
    ]
    err_col = headers.index("error") + 1
    # `Cell.value` is a `float | Decimal | str | CellRichText | datetime | ...`
    # union; pyright rightly refuses `in` against that. Narrow to `str` so
    # the containment checks below type-check (and the runtime semantics
    # are unchanged for the str/None case we actually emit).
    # CodeRabbit #17 round-15 nit.
    error_value = summary.cell(row=2, column=err_col).value
    error_label = str(error_value or "")
    # Coarse + class name only — no internal details.
    assert "RuntimeError" in error_label
    assert "see server logs" in error_label
    assert "/tmp/batch-xyz" not in error_label
    assert "internal-llm.corp" not in error_label
    assert ".env" not in error_label


def test_batch_workspace_cleanup_failure_is_logged_not_silent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`shutil.rmtree` failures used to be silently swallowed via
    ``ignore_errors=True``, so a partially-full disk could leak batch
    workspaces indefinitely with no operator signal. The fix logs
    cleanup failure via `logger.exception`.
    """
    import shutil as _shutil

    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(batch_module, "HttpChatClient", lambda config: stub)

    def _boom(path: Path | str) -> None:
        raise OSError("simulated rmtree failure")

    monkeypatch.setattr(_shutil, "rmtree", _boom)

    manifest = json.dumps({"question": "Q1", "file": "sales.csv"}).encode("utf-8")
    with caplog.at_level("ERROR", logger="app.api.batch"):
        response = client.post(
            "/v1/batch",
            files=[
                ("manifest", ("m.jsonl", manifest, "application/x-ndjson")),
                ("files", ("sales.csv", _csv_bytes(), "text/csv")),
            ],
        )
    # The user-visible response is still successful — cleanup failure
    # must not mask a successful batch run.
    assert response.status_code == 200, response.text
    # But the cleanup failure must be logged with enough detail for ops
    # to investigate — the "workspace cleanup failed" prefix proves we
    # hit the guarded branch rather than the old silent swallow.
    assert any(
        "workspace cleanup failed" in record.getMessage()
        for record in caplog.records
    ), [r.getMessage() for r in caplog.records]
