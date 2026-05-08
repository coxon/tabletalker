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
from app.limits import UPLOAD_MAX_BYTES, UPLOAD_MAX_FILES, UPLOAD_MAX_TOTAL_BYTES
from app.persistence import get_session_recorder
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
    sampling_rate: float | None = Form(default=None),
    sampling_note: str | None = Form(default=None),
    extra_files: list[UploadFile] = File(default_factory=list),  # noqa: B008
) -> AnalyzeResponse:
    """Run a single-turn analysis. Returns the contract-shape JSON.

    The response also carries an `X-Stage-Timings` header with per-stage
    durations from the pipeline (see `app.analyze.stages`). The header is
    informational — the JSON contract shape is unchanged.

    `report_html_url` resolution prefers the request's own origin (so a
    deploy behind a TLS-terminating proxy with `--proxy-headers` returns
    `https://demo.example.com/reports/<id>.html`) and falls back to
    `APP_PUBLIC_URL` from `.env` when the request URL isn't usable.

    `sampling_rate` (optional, 0..1) declares that the uploaded file is a
    downsample of the source. Required by README §3.3 雷7 / §7.2 #7
    whenever the caller pre-sampled — every emitted Evidence row will
    carry this rate so the auto-grader scales row_count expectations
    instead of judging the analysis as fabricated. `sampling_note` is a
    free-text companion (e.g. "25k rows of 100k, deterministic seed=42")
    surfaced in the HTML report.

    `extra_files` is the multi-file extension. The primary `file` is
    always the first table the planner sees (and the default for refusal
    + Evidence dataset/table); auxiliaries land in the same workspace
    and the planner is told it can `join` them on shared keys. Eval
    harnesses that only send a single `file` are unaffected — leaving
    `extra_files` empty preserves the original single-table flow.
    """

    # Normalise once: surrounding whitespace shouldn't change the request
    # identity, the LLM prompt, or the evidence `dataset` label.
    clean_question = question.strip()
    clean_dataset = (dataset or "").strip()
    clean_note = (sampling_note or "").strip() or None
    if not clean_question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "question must not be empty")
    if sampling_rate is not None and not (0.0 < sampling_rate <= 1.0):
        # `0.0` would mean "analyzed nothing" — nonsense as evidence
        # context. `>1.0` is impossible by definition. Reject early so
        # the schema validator's pydantic error doesn't surface as a 500.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "sampling_rate must be in (0, 1]",
        )

    filename = _safe_filename(file.filename or "upload.csv")
    workspace = Path(tempfile.mkdtemp(prefix="tabletalker-analyze-"))
    keep_workspace = False
    try:
        target = workspace / filename
        # Round-7 (CodeRabbit #15): the primary upload also gets the
        # aggregate budget so a single-file request cannot exceed
        # UPLOAD_MAX_TOTAL_BYTES even when that constant is tuned below
        # the per-file `UPLOAD_MAX_BYTES`. Mid-stream enforcement, same
        # as the auxiliary writes below.
        total_bytes = await _save_upload(
            file,
            target,
            remaining_total_budget=UPLOAD_MAX_TOTAL_BYTES,
        )

        # Auxiliary files: same per-file size cap as the primary, dedup
        # on filename so a client uploading the same file twice doesn't
        # silently overwrite. Empty `filename` slots from form data
        # (e.g. some browsers POST a blank when no file picked) are
        # filtered out so they don't become a stray `upload.csv`. We
        # also enforce *aggregate* caps (count + total bytes) so a
        # caller can't pin all of /tmp by uploading dozens of files
        # each at the per-file ceiling. Cleanup-on-error is the `finally`.
        non_blank_extras = [
            extra for extra in extra_files if (extra.filename or "").strip()
        ]
        # +1 for the primary; comparing against `UPLOAD_MAX_FILES` (which
        # already includes the primary) keeps the constant intuitive.
        if 1 + len(non_blank_extras) > UPLOAD_MAX_FILES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"too many files; at most {UPLOAD_MAX_FILES} per request "
                f"(including the primary upload)",
            )
        extra_filenames: list[str] = []
        seen_names: set[str] = {filename}
        for extra in non_blank_extras:
            extra_name = _safe_filename(extra.filename or "")
            # Deduplicate against the primary AND prior auxiliaries. We
            # rename collisions with a numeric suffix so the planner
            # still sees both files distinctly.
            unique_name = extra_name
            counter = 1
            while unique_name in seen_names:
                stem = Path(extra_name).stem
                suffix = Path(extra_name).suffix
                unique_name = f"{stem}__{counter}{suffix}"
                counter += 1
            seen_names.add(unique_name)
            # Pass the *remaining* budget so the streaming write trips
            # 413 mid-chunk, not after writing 60 MiB to disk first.
            remaining = UPLOAD_MAX_TOTAL_BYTES - total_bytes
            total_bytes += await _save_upload(
                extra,
                workspace / unique_name,
                remaining_total_budget=remaining,
            )
            if total_bytes > UPLOAD_MAX_TOTAL_BYTES:
                # Defence-in-depth: the streaming check above is the
                # primary gate (it bails after one chunk past the
                # ceiling), but a future refactor that drops the budget
                # arg would silently bypass it. Keep this check as a
                # backstop. The `finally` rmtree's the workspace
                # including any partial write.
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"combined upload size exceeds "
                    f"{UPLOAD_MAX_TOTAL_BYTES} bytes",
                )
            extra_filenames.append(unique_name)

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
            sampling_rate=sampling_rate,
            sampling_note=clean_note,
            extra_filenames=tuple(extra_filenames),
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
            sampling_rate=sampling_rate,
            sampling_note=clean_note,
            # Preserve the multi-file parent shape so follow-up turns
            # rebuild the same AnalyzeRequest instead of silently
            # dropping to single-file (CodeRabbit #17 round-15
            # Critical: joins referencing a secondary table vanish
            # on the second turn without this).
            extra_filenames=tuple(extra_filenames),
        )
        SESSION_STORE.put(session)
        # Persist a durable copy in the history index. The recorder
        # swallows its own sqlite failures; this defensive try/except is
        # belt-and-braces in case a future refactor changes that
        # contract — losing a history row should never 500 the actual
        # analysis response.
        try:
            get_session_recorder().record_parent(
                analyze_response,
                primary_filename=filename,
                extra_filenames=extra_filenames,
                original_question=clean_question,
                sampling_rate=sampling_rate,
                sampling_note=clean_note,
            )
        except Exception:  # side-channel; never fail the request
            logger.exception(
                "history recorder: parent persist raised for %s",
                analyze_response.id,
            )
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
    """Normalise an upload's reported filename to a basename we can store.

    Browsers running on Windows still occasionally POST the full client
    path (e.g. ``C:\\Users\\alice\\sales.csv``); on macOS / Linux hosts
    `pathlib.Path` treats ``\\`` as a regular character, so the naïve
    `Path(name).name` would keep the whole string. That blows the
    multi-file dedup loop (every weird path looks distinct) and produces
    nonsense filenames in the workspace. Normalise backslashes to
    forward-slashes first so the basename split works cross-platform.
    Also rejects bare/dotfile names (`.env` etc.) as a defence-in-depth
    against a client uploading a file that the OS would treat as hidden.
    (CodeRabbit #17 round-15 nit.)
    """

    base = Path(name.replace("\\", "/")).name
    if not base or base.startswith("."):
        return "upload.csv"
    return base


async def _save_upload(
    file: UploadFile,
    target: Path,
    *,
    remaining_total_budget: int | None = None,
) -> int:
    """Stream the upload to `target`, capped at `UPLOAD_MAX_BYTES`.

    Returns bytes written so callers can track an aggregate footprint
    (the route enforces `UPLOAD_MAX_TOTAL_BYTES` across primary + all
    auxiliaries combined). The per-file cap is checked here so the
    upload short-circuits before consuming all of `/tmp` even when the
    aggregate logic isn't tracking yet.

    `remaining_total_budget` (CodeRabbit #15 round-2) lets callers
    enforce the aggregate ceiling *during* the stream, not after the
    whole file has hit disk. Without this, a 50 MiB primary + a 60 MiB
    auxiliary could land 110 MiB in /tmp before the post-write check
    raises 413 on iteration 2 — the malicious caller has already
    achieved most of the disk-pressure they wanted. Pass it None for
    "no aggregate gating" (the primary file path) or the remaining
    bytes-from-budget for auxiliaries.
    """
    bytes_written = 0
    with target.open("wb") as fh:
        while chunk := await file.read(64 * 1024):
            bytes_written += len(chunk)
            if bytes_written > UPLOAD_MAX_BYTES:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"upload exceeds {UPLOAD_MAX_BYTES} bytes",
                )
            if (
                remaining_total_budget is not None
                and bytes_written > remaining_total_budget
            ):
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"combined upload size exceeds "
                    f"{UPLOAD_MAX_TOTAL_BYTES} bytes",
                )
            fh.write(chunk)
    return bytes_written
