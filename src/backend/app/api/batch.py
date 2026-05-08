"""POST /v1/batch — fan-out batch evaluation endpoint.

Designed for the evaluator's "批量评测" workflow: they hand us a manifest
(JSONL or CSV) describing many test cases plus the data files those
cases reference, and we hand back an xlsx of results.

Flow:

  1. Save every uploaded data file into a per-batch workspace.
  2. Parse the manifest into typed `BatchTask`s.
  3. Run each task through `handle_analyze` (same code path as
     `/v1/analyze`, so refusal handling / sampling / evidence are
     identical to a single-call submission).
  4. Render results into an xlsx workbook and stream it back.

The workspace is rmtree'd on the way out — batch runs don't seed the
session store (no follow-up addressability), so the temp dir's only
purpose is to give the runner a place to read files from.

For Compatibility with `/v1/analyze`, the per-task fields (`dataset`,
`sampling_rate`, etc.) live in the manifest, not in the multipart form.
Only `manifest` and `files` are at the form level.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.batch import BatchTask, ManifestError, parse_manifest, render_xlsx, run_batch
from app.limits import UPLOAD_MAX_BYTES
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["batch"])


# Per-batch caps. Manifests stay small (text); the data files inherit the
# same cap as `/v1/analyze` so a batch can't sneak past the size limit
# the single-call route enforces.
_MANIFEST_MAX_BYTES = 4 * 1024 * 1024  # 4 MiB
# Hard ceiling on tasks per batch — protects against a runaway evaluator
# script. The grader's published case count is well under this.
_MAX_TASKS = 200


@router.post("/batch")
async def batch(
    request: Request,
    manifest: UploadFile = File(...),  # noqa: B008 — FastAPI DI idiom
    files: list[UploadFile] = File(default_factory=list),  # noqa: B008
) -> StreamingResponse:
    """Run every manifest task and stream back an xlsx workbook.

    Manifest format: JSONL (default) or CSV (sniffed by extension). Each
    task references its data file(s) by basename — every basename must
    appear among the uploaded `files`. The route fails closed with a
    400 if a task references a file we didn't receive.

    Response: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
    with a `Content-Disposition: attachment` header so browsers prompt
    the user to save it. Header carries `X-Batch-Tasks` and
    `X-Batch-Errors` for observability without parsing the body.
    """

    # --- 1. Manifest first — it tells us which data files we expect ---
    # Round-8 (CodeRabbit #16): stream-read in chunks rather than
    # `await manifest.read()` so a hostile client cannot pin
    # `_MANIFEST_MAX_BYTES * worker_count` bytes of resident memory by
    # uploading one bloated manifest per worker. We bail at the *first*
    # chunk that pushes the total over the limit — same byte budget as
    # the all-at-once read, but bounded peak RSS.
    manifest_buf = bytearray()
    while chunk := await manifest.read(64 * 1024):
        manifest_buf.extend(chunk)
        if len(manifest_buf) > _MANIFEST_MAX_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"manifest exceeds {_MANIFEST_MAX_BYTES} bytes",
            )
    manifest_bytes = bytes(manifest_buf)
    try:
        tasks = parse_manifest(manifest_bytes, manifest.filename or "manifest.jsonl")
    except ManifestError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if len(tasks) > _MAX_TASKS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"manifest has {len(tasks)} tasks; limit is {_MAX_TASKS}",
        )

    # --- 2. Workspace + uploaded data files ---
    workspace = Path(tempfile.mkdtemp(prefix="tabletalker-batch-"))
    try:
        # CodeRabbit #16 round-2: only persist uploads that are
        # actually referenced by a task. Without this, an evaluator
        # who attaches 50 files but only references 5 in the manifest
        # paid 50× the disk + per-file cap; worse, an evaluator who
        # accidentally attaches a sensitive file (logs, .env) writes
        # it to /tmp even though it's never read. Build the referenced
        # set from `tasks` first, then filter the upload stream.
        referenced_names: set[str] = set()
        for task in tasks:
            referenced_names.add(task.file)
            referenced_names.update(task.extra_files)

        saved_names: set[str] = set()
        for upload in files:
            raw_name = upload.filename or ""
            name = _safe_filename(raw_name)
            if not name:
                continue  # blank slot from the multipart form
            if name not in referenced_names:
                # Skip silently — uploads that no task references are
                # noise, not an error (the manifest is the
                # authoritative ground truth). The
                # `_validate_task_files` check below still catches
                # the inverse case (referenced-but-not-uploaded).
                continue
            if name in saved_names:
                # Manifest reference is by basename; duplicate uploads
                # would overwrite each other. Flag explicitly so the
                # evaluator notices the typo rather than getting silent
                # data corruption.
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"duplicate uploaded file basename: {name!r}",
                )
            await _save_upload(upload, workspace / name)
            saved_names.add(name)
        _validate_task_files(tasks, saved_names)

        # --- 3. LLM client (single config; reused across tasks) ---
        try:
            config = LLMConfig.from_env()
        except LLMConfigError as exc:
            logger.error("LLM not configured for batch: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "LLM service is not configured",
            ) from exc
        chat_client = HttpChatClient(config)

        # --- 4. Fan out ---
        results = await run_batch(
            tasks,
            workspace=workspace,
            chat_client=chat_client,
            base_url=str(request.base_url),
        )

        # --- 5. Render + stream ---
        xlsx_bytes = render_xlsx(results)
        error_count = sum(1 for r in results if r.status != "ok")
        headers = {
            "Content-Disposition": (
                'attachment; filename="tabletalker-batch-results.xlsx"'
            ),
            "X-Batch-Tasks": str(len(results)),
            "X-Batch-Errors": str(error_count),
        }
        return StreamingResponse(
            iter([xlsx_bytes]),
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            headers=headers,
        )
    finally:
        # Batch results never seed a session — no follow-up flow needs
        # the workspace, so we can clean up unconditionally.
        #
        # `ignore_errors=True` used to silently swallow EPERM / EBUSY
        # cleanup failures, so a disk that was inch-from-full could
        # quietly leak batch workspaces forever. Log the path and
        # exception so ops can notice; we still swallow the error here
        # because cleanup failure must not mask a successful response.
        try:
            shutil.rmtree(workspace)
        except FileNotFoundError:
            # Already gone — nothing to clean.
            pass
        except Exception:
            logger.exception(
                "batch workspace cleanup failed: %s", workspace
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    """Strip directories + leading dots; mirrors `app.api.analyze` so
    manifest references stay portable across the two routes.

    Round-8 (CodeRabbit #16): grader environments occasionally upload
    Windows-style paths (``C:\\Users\\grader\\sales.csv``). `Path` on
    POSIX treats backslash as a regular filename character, so
    ``Path("C:\\Users\\grader\\sales.csv").name`` returns the whole
    string and the manifest-reference comparison fails. Normalise
    backslashes to forward slashes first so both separators collapse
    to the same basename.
    """
    normalized = name.replace("\\", "/")
    base = Path(normalized).name
    if not base or base.startswith("."):
        return ""
    return base


async def _save_upload(file: UploadFile, target: Path) -> None:
    """Stream-write an uploaded file with the same per-file size cap as
    `/v1/analyze`. We don't pool reads here because the manifest is
    guaranteed-small; data files are the bulk.

    Round-11 (CodeRabbit #16): write to ``target.with_suffix('.part')``
    first and atomically rename on success. Without this, a request that
    blows the size cap (or any other mid-stream failure) leaves a
    partially-written file at ``target`` — and ``_validate_task_files``
    then thinks the upload "succeeded" because the basename is present
    on disk, so subsequent batch requests in the same workdir would see
    a corrupt CSV. Atomic rename means callers either see the full file
    or no file at all; cleanup of stale ``.part`` files happens in the
    failure branch.
    """

    tmp = target.with_suffix(target.suffix + ".part")
    bytes_written = 0
    try:
        with tmp.open("wb") as fh:
            while chunk := await file.read(64 * 1024):
                bytes_written += len(chunk)
                if bytes_written > UPLOAD_MAX_BYTES:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"file {target.name!r} exceeds {UPLOAD_MAX_BYTES} bytes",
                    )
                fh.write(chunk)
    except BaseException:
        # Includes HTTPException above plus any IO error / cancellation.
        # `missing_ok=True` because the file may not have been created
        # yet (e.g. open() failed) or already cleaned up by another
        # branch.
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(target)


def _validate_task_files(tasks: list[BatchTask], available: set[str]) -> None:
    """Every basename a task references must be among the uploads.

    Failing fast here is much friendlier than letting the runner emit
    one 422 per missing file: the evaluator sees a single 400 with the
    full list of typos / forgotten uploads.
    """

    referenced: set[str] = set()
    for task in tasks:
        referenced.add(task.file)
        referenced.update(task.extra_files)
    missing = sorted(referenced - available)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"manifest references files not uploaded: {missing}",
        )
