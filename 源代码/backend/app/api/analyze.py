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
expires (TTL or LRU eviction). The upload byte caps in `app.limits` keep
that disk footprint bounded while letting `/v1/follow-up` re-read the file
without round-tripping through the network. Cleanup happens in
`app.session.store` when an entry is evicted.

The internal `/spreadsheet/analyze` route (PR #3.5) is unaffected — it
still exists for dev/debug, but the grader never sees it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.analyze.handler import (
    AnalyzeFailure,
    AnalyzeRequest,
    bind_finalize_finding_listener,
    bind_finalize_recommendation_listener,
    bind_finalize_token_listener,
    handle_analyze,
    new_request_id,
)
from app.analyze.schema import AnalyzeResponse
from app.analyze.stages import STAGE_ORDER, StageTimer, bind_stage_timer, serialize_header
from app.limits import UPLOAD_MAX_BYTES, UPLOAD_MAX_FILES, UPLOAD_MAX_TOTAL_BYTES
from app.persistence import get_session_recorder
from app.session import (
    SESSION_STORE,
    extract_cohorts,
    session_from_response,
)
from app.session.workspace import make_workspace
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError
from app.spreadsheet.planner import bind_plan_op_listener

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

    prep = await _prepare_request_or_raise(
        request=request,
        file=file,
        question=question,
        dataset=dataset,
        sampling_rate=sampling_rate,
        sampling_note=sampling_note,
        extra_files=extra_files,
    )
    keep_workspace = False
    try:
        # `bind_stage_timer()` is a contextmanager so the `as timer`
        # binding only happens once it succeeds. Initialise to None
        # outside the try so pyright understands the except clause's
        # reference is well-defined; in practice the timer is always
        # bound by the time AnalyzeFailure can be raised, but the
        # fallback `serialize_header(timer)` still works (it accepts
        # an empty StageTimer).
        timer: StageTimer | None = None
        try:
            with bind_stage_timer() as timer:
                analyze_response = await handle_analyze(
                    prep.analyze_request, chat_client=prep.chat_client
                )
            response.headers["X-Stage-Timings"] = serialize_header(timer)
        except AnalyzeFailure as exc:
            # Forward stage timings on the error path too — the eval renderer
            # needs to know which stage died on a 422/502, otherwise root-cause
            # analysis on a failed case requires re-running with a backend log
            # capture (which start.sh did not always do). FastAPI does not
            # propagate `response.headers` to the HTTPException response, so
            # set them on the exception itself.
            timings_header = serialize_header(timer) if timer is not None else "{}"
            raise HTTPException(
                exc.status_code,
                str(exc),
                headers={"X-Stage-Timings": timings_header},
            ) from exc

        _finalize_session(prep, analyze_response)
        # Workspace ownership has transferred to the session store — do
        # not rmtree it on the way out.
        keep_workspace = True
        return analyze_response
    finally:
        if not keep_workspace:
            shutil.rmtree(prep.workspace, ignore_errors=True)


@router.post("/analyze/stream")
async def analyze_stream(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    question: str = Form(...),
    dataset: str | None = Form(default=None),
    sampling_rate: float | None = Form(default=None),
    sampling_note: str | None = Form(default=None),
    extra_files: list[UploadFile] = File(default_factory=list),  # noqa: B008
) -> StreamingResponse:
    """NDJSON-streaming variant of `/v1/analyze`.

    Returns one JSON event per line as the analysis pipeline progresses:

      {"type":"stage","name":"profile","status":"start"}
      {"type":"stage","name":"profile","status":"end","duration_s":0.42}
      {"type":"stage","name":"preview_plan_req","status":"start"}
      ...
      {"type":"result","data":<AnalyzeResponse>,"stage_timings":{...}}

    On failure, the terminal event is:

      {"type":"error","status":<int>,"detail":"...","stage_timings":{...}}

    The data payload of `result` matches the JSON shape of `/v1/analyze`
    byte-for-byte (`AnalyzeResponse.model_dump(mode="json")`), so the
    frontend can reuse the same post-processing on the terminal event.
    The original `/v1/analyze` contract is unchanged — graders and any
    JSON consumer keep using that path; the streaming path is purely a
    UX addition for the SPA.
    """
    prep = await _prepare_request_or_raise(
        request=request,
        file=file,
        question=question,
        dataset=dataset,
        sampling_rate=sampling_rate,
        sampling_note=sampling_note,
        extra_files=extra_files,
    )

    # Unbounded queue: 7 stages per request, each event is < 200 bytes,
    # so memory is bounded by the handler's own pipeline, not by the
    # consumer's drain rate. A bounded queue would risk back-pressuring
    # the handler if a slow consumer (or browser tab in background)
    # falls behind, which is worse than a few KiB transient.
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def encode(payload: dict[str, object]) -> bytes:
        return (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")

    def emit(payload: dict[str, object]) -> None:
        # Unbounded `put_nowait` cannot raise QueueFull. The bytes encode
        # happens on the producer side so the streaming generator never
        # blocks the queue waiting on json.dumps.
        queue.put_nowait(encode(payload))

    def on_stage(stage_name: str, duration_s: float) -> None:
        emit({
            "type": "stage",
            "name": stage_name,
            "status": "end",
            "duration_s": round(duration_s, 4),
        })
        try:
            idx = STAGE_ORDER.index(stage_name)
        except ValueError:
            # Defensive: an out-of-band stage name shouldn't crash the
            # listener (telemetry must never break the request), so just
            # don't synthesise the next-start event.
            return
        if idx + 1 < len(STAGE_ORDER):
            emit({
                "type": "stage",
                "name": STAGE_ORDER[idx + 1],
                "status": "start",
            })

    async def runner() -> None:
        keep_workspace = False

        def on_finalize_token(delta: str) -> None:
            # Live `summary` deltas while the finalize LLM streams its
            # JSON response. See the analogous block in
            # api/follow_up.py for the rationale; both endpoints emit
            # the same `partial` event shape.
            emit({
                "type": "partial",
                "field": "summary",
                "delta": delta,
            })

        def on_finalize_finding(value: dict) -> None:
            emit({
                "type": "partial",
                "field": "finding",
                "value": value,
            })

        def on_finalize_recommendation(text: str) -> None:
            emit({
                "type": "partial",
                "field": "recommendation",
                "text": text,
            })

        def on_plan_op(kind: str) -> None:
            # Each op kind in the planner's streaming JSON triggers a
            # chip on the frontend so the user sees concrete progress
            # ("已规划 load → group_by → aggregate") instead of staring
            # at an opaque "正在规划" spinner. See planner._PlanOpEmitter.
            emit({
                "type": "partial",
                "field": "plan_op",
                "kind": kind,
            })

        try:
            # Synthesise the first stage's "start" before the handler
            # begins so the UI shows row 1 spinning immediately.
            emit({"type": "stage", "name": STAGE_ORDER[0], "status": "start"})
            timer: StageTimer | None = None
            try:
                with bind_plan_op_listener(on_plan_op):
                    with bind_finalize_token_listener(on_finalize_token):
                     with bind_finalize_finding_listener(on_finalize_finding):
                      with bind_finalize_recommendation_listener(on_finalize_recommendation):
                        with bind_stage_timer(listener=on_stage) as timer:
                            analyze_response = await handle_analyze(
                                prep.analyze_request, chat_client=prep.chat_client
                            )
                _finalize_session(prep, analyze_response)
                keep_workspace = True
                emit({
                    "type": "result",
                    "data": analyze_response.model_dump(mode="json"),
                    "stage_timings": timer.as_payload(),
                })
            except AnalyzeFailure as exc:
                emit({
                    "type": "error",
                    "status": exc.status_code,
                    "detail": str(exc),
                    "stage_timings": (
                        timer.as_payload() if timer is not None else {}
                    ),
                })
        except Exception as exc:  # pragma: no cover - defensive
            # Anything else (a bug in the handler / uncaught LLM error) —
            # surface it to the client as an error event rather than
            # closing the stream silently.
            logger.exception("analyze/stream: unhandled error")
            emit({
                "type": "error",
                "status": 500,
                "detail": f"internal error: {exc}",
                "stage_timings": {},
            })
        finally:
            if not keep_workspace:
                shutil.rmtree(prep.workspace, ignore_errors=True)
            # Sentinel: tell the consumer no more events are coming.
            queue.put_nowait(None)

    async def stream() -> AsyncIterator[bytes]:
        task = asyncio.create_task(runner())
        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                yield msg
        finally:
            # If the client disconnected mid-stream, cancel the runner so
            # the handler doesn't keep working on a request nobody is
            # listening to. The runner's own `finally` cleans up the
            # workspace.
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            # No buffering / no caching — proxies and browser tabs both
            # need to see events as they arrive.
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


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


# ---------------------------------------------------------------------------
# Shared upload-prep + session-finalize helpers (used by both `/v1/analyze`
# and `/v1/analyze/stream` so the two endpoints stay in lockstep).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PreparedAnalyze:
    """Bundle returned by `_prepare_request_or_raise` carrying everything
    the handler + post-handler bookkeeping need. Both endpoints consume
    these fields; keeping them in a frozen dataclass means a refactor
    can't accidentally drop one in one path while keeping it in the other.
    """
    workspace: Path
    filename: str
    effective_dataset: str
    clean_question: str
    clean_note: str | None
    sampling_rate: float | None
    extra_filenames: list[str]
    chat_client: HttpChatClient
    analyze_request: AnalyzeRequest


async def _prepare_request_or_raise(
    *,
    request: Request,
    file: UploadFile,
    question: str,
    dataset: str | None,
    sampling_rate: float | None,
    sampling_note: str | None,
    extra_files: list[UploadFile],
) -> _PreparedAnalyze:
    """Validate the form, save the uploads to a tmp workspace, and build
    the `AnalyzeRequest`. Raises `HTTPException` on any validation /
    upload failure; the workspace is cleaned up before raising so the
    caller doesn't have to know about it on the error path.

    The success path returns the workspace as part of the bundle —
    cleanup is the caller's responsibility (so the streaming endpoint
    can hand the workspace off to the session store *after* the handler
    actually returns)."""

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
    # Generate the response_id up front so the workspace dir is keyed
    # by it. This makes resume after a backend restart trivial: the
    # session id is on disk, in the URL, and in the SQLite metadata
    # row — no hidden uuid mapping needed. `make_workspace` uses the
    # persistent root (PVC-mounted in k8s, env-overridable in dev) and
    # falls back to tempdir when no persistent storage is configured.
    request_id = new_request_id()
    workspace = make_workspace(request_id)
    try:
        target = workspace / filename
        # Round-7 (CodeRabbit #15): the primary upload also gets the
        # aggregate budget so a single-file request cannot exceed
        # UPLOAD_MAX_TOTAL_BYTES even when that constant is tuned below
        # the per-file `UPLOAD_MAX_BYTES`.
        total_bytes = await _save_upload(
            file,
            target,
            remaining_total_budget=UPLOAD_MAX_TOTAL_BYTES,
        )

        # Auxiliary files: same per-file size cap as the primary, dedup
        # on filename so a client uploading the same file twice doesn't
        # silently overwrite. Empty `filename` slots from form data are
        # filtered out so they don't become a stray `upload.csv`. We
        # also enforce *aggregate* caps (count + total bytes) so a
        # caller can't pin all of /tmp by uploading dozens of files
        # each at the per-file ceiling.
        non_blank_extras = [
            extra for extra in extra_files if (extra.filename or "").strip()
        ]
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
            unique_name = extra_name
            counter = 1
            while unique_name in seen_names:
                stem = Path(extra_name).stem
                suffix = Path(extra_name).suffix
                unique_name = f"{stem}__{counter}{suffix}"
                counter += 1
            seen_names.add(unique_name)
            remaining = UPLOAD_MAX_TOTAL_BYTES - total_bytes
            total_bytes += await _save_upload(
                extra,
                workspace / unique_name,
                remaining_total_budget=remaining,
            )
            if total_bytes > UPLOAD_MAX_TOTAL_BYTES:
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
            dataset=effective_dataset,
            question=clean_question,
            base_url=str(request.base_url),
            sampling_rate=sampling_rate,
            sampling_note=clean_note,
            extra_filenames=tuple(extra_filenames),
            request_id=request_id,
        )
    except BaseException:
        # Clean up the workspace before re-raising — the caller doesn't
        # know about the workspace yet so it can't do this cleanup itself.
        shutil.rmtree(workspace, ignore_errors=True)
        raise

    return _PreparedAnalyze(
        workspace=workspace,
        filename=filename,
        effective_dataset=effective_dataset,
        clean_question=clean_question,
        clean_note=clean_note,
        sampling_rate=sampling_rate,
        extra_filenames=extra_filenames,
        chat_client=chat_client,
        analyze_request=analyze_request,
    )


def _finalize_session(prep: _PreparedAnalyze, analyze_response: AnalyzeResponse) -> None:
    """Register the session + persist a history row after a successful
    `handle_analyze`. Caller is responsible for setting `keep_workspace`
    so the workspace isn't rmtree'd on the way out — ownership has just
    transferred to the session store."""

    # Register the session so /v1/follow-up can pick it up. We do this
    # even on refused parents — the contract requires the same shape,
    # and the follow-up handler enforces refusal carry-through.
    cohorts = extract_cohorts(analyze_response.findings, turn_index=0)
    session = session_from_response(
        analyze_response,
        workspace_dir=prep.workspace,
        filename=prep.filename,
        dataset=prep.effective_dataset,
        original_question=prep.clean_question,
        cohorts=cohorts,
        sampling_rate=prep.sampling_rate,
        sampling_note=prep.clean_note,
        extra_filenames=tuple(prep.extra_filenames),
    )
    SESSION_STORE.put(session)
    # Persist a durable copy in the history index. The recorder swallows
    # its own sqlite failures; this defensive try/except is belt-and-
    # braces in case a future refactor changes that contract — losing a
    # history row should never 500 the actual analysis response.
    try:
        recorder = get_session_recorder()
        recorder.record_parent(
            analyze_response,
            primary_filename=prep.filename,
            extra_filenames=prep.extra_filenames,
            original_question=prep.clean_question,
            sampling_rate=prep.sampling_rate,
            sampling_note=prep.clean_note,
        )
        # Rich state for resume after backend restart. Same recorder
        # instance, same defensive failure-swallowing semantics.
        from app.session.serde import session_to_dict
        recorder.record_state(session.id, session_to_dict(session))
    except Exception:  # side-channel; never fail the request
        logger.exception(
            "history recorder: parent persist raised for %s",
            analyze_response.id,
        )
