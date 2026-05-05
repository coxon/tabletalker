"""POST /spreadsheet/analyze — internal typed-plan pipeline endpoint.

This endpoint is **internal**. It is NOT the submission contract — see
`docs/submission-contract.md` for the frozen `/v1/analyze` shape that
the organizer's grader hits. This route exists so PR #4 can wire the
typed-plan engine in as an audit/trace layer beneath the public
`/v1/analyze` handler, and so the engine can be exercised in isolation
during development.

Multipart upload of (file, question). The handler:
  1. Saves the upload into a per-request workspace dir.
  2. Loads a small preview to give the planner column names.
  3. Asks the planner for a Plan.
  4. Runs the executor.
  5. Returns { plan, result, verses } — internal shape, NOT the
     submission contract.

The workspace dir is created under `tempfile.gettempdir()` and is the
only place the executor's load ops can read from — see
`SpreadsheetContext.resolve_path`.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.spreadsheet.executor import (
    OpExecutionError,
    PlanValidationError,
    execute,
)
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError, LLMError
from app.spreadsheet.planner import PlannerError, PlanRequest, make_plan
from app.spreadsheet.schema import Plan
from app.spreadsheet.verse import TableVerse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spreadsheet", tags=["spreadsheet"])

# Cap upload size to keep the prototype honest. Real limits land later.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MiB
PREVIEW_ROWS = 50


class AnalyzeResponse(BaseModel):
    """Internal pipeline response shape.

    Distinct from the submission contract (`docs/submission-contract.md`),
    which carries `id / report_html_url / summary / findings / charts /
    recommendations / is_refusal / confidence`. PR #4's `/v1/analyze`
    handler will adapt this internal shape into the public contract.
    """

    plan: Plan
    result: dict[str, Any]  # the answer payload (table or chart)
    verses: list[TableVerse]


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile = File(...),  # noqa: B008 — FastAPI dependency injection idiom
    question: str = Form(...),
) -> AnalyzeResponse:
    if not question.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "question must not be empty")

    filename = _safe_filename(file.filename or "upload.csv")
    workspace = Path(tempfile.mkdtemp(prefix="tabletalker-"))
    try:
        target = workspace / filename
        await _save_upload(file, target)
        try:
            preview = _load_preview(target)
        except HTTPException:
            raise
        except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            logger.warning("preview parse failed for %s: %s", filename, exc)
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "uploaded file could not be parsed; check format and encoding",
            ) from exc
        try:
            config = LLMConfig.from_env()
        except LLMConfigError as exc:
            logger.error("LLM not configured: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "LLM service is not configured",
            ) from exc

        client = HttpChatClient(config)
        request = PlanRequest(
            question=question,
            table_preview=preview,
            workspace_filename=filename,
        )

        try:
            plan = await make_plan(client, request)
        except PlannerError as exc:
            logger.warning("planner rejected request: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "planner failed to produce a valid plan",
            ) from exc
        except LLMError as exc:
            logger.warning("LLM call failed: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "LLM gateway error",
            ) from exc

        try:
            report = execute(plan, workspace)
        except PlanValidationError as exc:
            logger.info("plan validation failed: %s", exc)
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "generated plan failed validation",
            ) from exc
        except OpExecutionError as exc:
            logger.warning("op execution failed at #%d (%s): %s",
                           exc.op_index, exc.op.kind, exc.cause)
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"op execution failed at step {exc.op_index} ({exc.op.kind})",
            ) from exc

        return AnalyzeResponse(plan=plan, result=report.answer, verses=report.verses)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _safe_filename(name: str) -> str:
    """Strip any path components — the upload only ever lives in the workspace."""

    base = Path(name).name
    if not base or base.startswith("."):
        return "upload.csv"
    return base


async def _save_upload(file: UploadFile, target: Path) -> None:
    bytes_written = 0
    with target.open("wb") as fh:
        while chunk := await file.read(64 * 1024):
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"upload exceeds {MAX_UPLOAD_BYTES} bytes",
                )
            fh.write(chunk)


def _load_preview(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=PREVIEW_ROWS)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, nrows=PREVIEW_ROWS)
    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        f"unsupported file extension {suffix!r}; need .csv / .xlsx / .xls",
    )
