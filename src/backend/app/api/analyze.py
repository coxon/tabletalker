"""POST /v1/analyze — the public submission-contract endpoint.

This is the route the organizer's grader calls. The response shape is
frozen — see `docs/submission-contract.md`. The heavy lifting lives in
`app.analyze.handler`; this module only:

  - Saves the upload into a per-session workspace.
  - Builds an `AnalyzeRequest` for the handler.
  - Maps `AnalyzeFailure` to HTTP errors.
  - Registers the resulting state into the session store so follow-ups
    can pick the workspace up by `parent_id`.

Workspace lifetime: the parent's temp dir survives until the session
expires (TTL or LRU eviction). That trade — keeping ≤20 MiB per session
in the OS temp dir for ~24 h — is what lets `/v1/follow-up` re-read the
file without round-tripping through the network. Cleanup happens in
`app.session.store` when an entry is evicted.

The internal `/spreadsheet/analyze` route (PR #3.5) is unaffected — it
still exists for dev/debug, but the grader never sees it.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status

from app.analyze.handler import (
    AnalyzeFailure,
    AnalyzeRequest,
    handle_analyze,
)
from app.analyze.schema import AnalyzeResponse
from app.analyze.stages import bind_stage_timer, serialize_header
from app.limits import UPLOAD_MAX_BYTES
from app.session import (
    SESSION_STORE,
    extract_cohorts,
    session_from_response,
)
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: Request,
    response: Response,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI DI idiom
    question: str = Form(...),
    dataset: str | None = Form(default=None),
) -> AnalyzeResponse:
    """Run a single-turn analysis. Returns the contract-shape JSON.

    The response also carries an `X-Stage-Timings` header with per-stage
    durations from the pipeline (see `app.analyze.stages`). The header is
    informational — the JSON contract shape is unchanged.

    `report_html_url` resolution prefers the request's own origin (so a
    deploy behind a TLS-terminating proxy with `--proxy-headers` returns
    `https://demo.example.com/reports/<id>.html`) and falls back to
    `APP_PUBLIC_URL` from `.env` when the request URL isn't usable.
    """

    # Normalise once: surrounding whitespace shouldn't change the request
    # identity, the LLM prompt, or the evidence `dataset` label.
    clean_question = question.strip()
    clean_dataset = (dataset or "").strip()
    if not clean_question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "question must not be empty")

    filename = _safe_filename(file.filename or "upload.csv")
    workspace = Path(tempfile.mkdtemp(prefix="tabletalker-analyze-"))
    keep_workspace = False
    try:
        target = workspace / filename
        await _save_upload(file, target)

        try:
            config = LLMConfig.from_env()
        except LLMConfigError as exc:
            logger.error("LLM not configured: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "LLM service is not configured",
            ) from exc

        chat_client = HttpChatClient(config)
        effective_dataset = clean_dataset or Path(filename).stem
        analyze_request = AnalyzeRequest(
            workspace=workspace,
            filename=filename,
            # `dataset` defaults to the file's stem so casual uploads
            # ("sales.csv") still produce a sensible Evidence.dataset.
            # Named datasets pass `dataset=...` in the form.
            dataset=effective_dataset,
            question=clean_question,
            base_url=str(request.base_url),
        )
        try:
            with bind_stage_timer() as timer:
                analyze_response = await handle_analyze(
                    analyze_request, chat_client=chat_client
                )
            response.headers["X-Stage-Timings"] = serialize_header(timer)
        except AnalyzeFailure as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

        # Register the session so /v1/follow-up can pick it up. We do
        # this *before* the early-return so even refused parents are
        # addressable — the contract requires the same shape, and the
        # follow-up handler enforces refusal carry-through.
        cohorts = extract_cohorts(analyze_response.findings, turn_index=0)
        session = session_from_response(
            analyze_response,
            workspace_dir=workspace,
            filename=filename,
            dataset=effective_dataset,
            original_question=clean_question,
            cohorts=cohorts,
        )
        SESSION_STORE.put(session)
        # Workspace ownership has transferred to the session store — do
        # not rmtree it on the way out.
        keep_workspace = True
        return analyze_response
    finally:
        if not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Upload helpers (mirror the internal /spreadsheet route's behaviour so
# the same caps apply consistently across both endpoints)
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    base = Path(name).name
    if not base or base.startswith("."):
        return "upload.csv"
    return base


async def _save_upload(file: UploadFile, target: Path) -> None:
    bytes_written = 0
    with target.open("wb") as fh:
        while chunk := await file.read(64 * 1024):
            bytes_written += len(chunk)
            if bytes_written > UPLOAD_MAX_BYTES:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"upload exceeds {UPLOAD_MAX_BYTES} bytes",
                )
            fh.write(chunk)
