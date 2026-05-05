"""POST /v1/analyze — the public submission-contract endpoint.

This is the route the organizer's grader calls. The response shape is
frozen — see `docs/submission-contract.md`. The heavy lifting lives in
`app.analyze.handler`; this module only:

  - Saves the upload into a per-request workspace.
  - Builds an `AnalyzeRequest` for the handler.
  - Maps `AnalyzeFailure` to HTTP errors.
  - Cleans up the workspace on the way out.

The internal `/spreadsheet/analyze` route (PR #3.5) is unaffected — it
still exists for dev/debug, but the grader never sees it.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.analyze.handler import (
    AnalyzeFailure,
    AnalyzeRequest,
    handle_analyze,
)
from app.analyze.schema import AnalyzeResponse
from app.limits import UPLOAD_MAX_BYTES
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile = File(...),  # noqa: B008 — FastAPI DI idiom
    question: str = Form(...),
    dataset: str | None = Form(default=None),
) -> AnalyzeResponse:
    """Run a single-turn analysis. Returns the contract-shape JSON."""

    # Normalise once: surrounding whitespace shouldn't change the request
    # identity, the LLM prompt, or the evidence `dataset` label.
    clean_question = question.strip()
    clean_dataset = (dataset or "").strip()
    if not clean_question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "question must not be empty")

    filename = _safe_filename(file.filename or "upload.csv")
    workspace = Path(tempfile.mkdtemp(prefix="tabletalker-analyze-"))
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
        request = AnalyzeRequest(
            workspace=workspace,
            filename=filename,
            # `dataset` defaults to the file's stem so casual uploads
            # ("sales.csv") still produce a sensible Evidence.dataset.
            # Named datasets pass `dataset=...` in the form.
            dataset=clean_dataset or Path(filename).stem,
            question=clean_question,
        )
        try:
            return await handle_analyze(request, chat_client=chat_client)
        except AnalyzeFailure as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
    finally:
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
