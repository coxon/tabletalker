"""POST /v1/follow-up — second public submission-contract endpoint.

The grader calls `/v1/analyze` once to seed a session, then `/v1/follow-up`
zero or more times against the parent's `id`. Body shape (per contract §1
and §4):

    { "parent_id": "eval_analysis_<hex>", "question": "<chinese-or-english>" }

Response shape is identical to `/v1/analyze` — this module is mostly
plumbing on top of `app.analyze.handler.handle_analyze`:

  - Look up the parent session.
  - If the parent was refused, echo the canonical refusal narrative
    (see `docs/refusal-policy.md` §carry-through and contract §5 — there
    is no path from "we couldn't analyze that" to a real answer within
    the same session).
  - Otherwise, build a system prelude from the parent state and run the
    pipeline against the parent's workspace, reusing the same file.
  - Append the new turn to the session and return.

Workspace lifetime: the parent's temp dir is owned by `SESSION_STORE` and
survives until the entry is evicted (TTL + LRU). Follow-ups never create
a new workspace — they re-read the file the parent saved.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.analyze.handler import (
    AnalyzeFailure,
    AnalyzeRequest,
    bind_finalize_finding_listener,
    bind_finalize_recommendation_listener,
    bind_finalize_token_listener,
    build_refusal_carry_through,
    handle_analyze,
    make_followup_id,
)
from app.analyze.schema import AnalyzeResponse
from app.analyze.stages import STAGE_ORDER, StageTimer, bind_stage_timer, serialize_header
from app.persistence import get_session_recorder
from app.session import (
    SESSION_STORE,
    extract_cohorts,
    render_followup_system_prompt,
)
from app.session.resume import try_resume_session
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError
from app.spreadsheet.planner import bind_plan_op_listener

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["follow-up"])


class FollowUpRequest(BaseModel):
    """JSON body accepted by `/v1/follow-up`.

    `extra="forbid"` rejects unknown top-level keys so a typo in the
    grader's payload (e.g. `parentId` instead of `parent_id`) surfaces
    as a 422 with a precise field name rather than being silently
    ignored — much easier to debug under time pressure.
    """

    model_config = ConfigDict(extra="forbid")

    parent_id: str = Field(..., min_length=1, description="Parent analyze id.")
    question: str = Field(..., min_length=1, description="Follow-up question text.")


@router.post("/follow-up", response_model=AnalyzeResponse)
async def follow_up(
    body: FollowUpRequest, request: Request, response: Response
) -> AnalyzeResponse:
    """Run a follow-up analysis against an existing session.

    Like `/v1/analyze`, attaches an `X-Stage-Timings` header with
    per-stage durations. Refusal carry-through skips the LLM stages
    so the header reports near-zero `plan_llm` / `finalize_llm` —
    that's the truthful representation of the work done.

    `report_html_url` resolution mirrors `/v1/analyze`: the request's
    own origin (proxy-aware) wins over `APP_PUBLIC_URL`.
    """

    clean_question = body.question.strip()
    if not clean_question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "question must not be empty")

    session = SESSION_STORE.resolve(body.parent_id)
    if session is None:
        # In-memory miss → silently try to rebuild from durable
        # storage (typically because the backend restarted between
        # the parent analyze and this follow-up). Only 404's if the
        # disk artefacts are also missing.
        session = try_resume_session(body.parent_id)
    if session is None:
        # 404 covers both "never existed" and "expired (TTL)". The
        # contract doesn't distinguish — the grader retries on 404 by
        # re-issuing the parent.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"session {body.parent_id!r} not found or expired",
        )

    # Reserve the follow-up id under the store's lock so two concurrent
    # requests against the same parent can't collide on `_qN`. The
    # placeholder turn returned here is finalised via `set_turn_response`
    # once the pipeline produces a real answer (or rolled back via
    # `discard_turn` if it raises). The token is opaque — we just thread
    # it back through to the matching set/discard so the *right*
    # per-session lock is released even if the session was evicted and
    # its id reused in the meantime.
    try:
        request_id, turn_index, alloc_token = SESSION_STORE.allocate_follow_up_turn(
            session.id, id_factory=make_followup_id
        )
    except KeyError as exc:
        # Evicted between the `get` above and the lock — extremely
        # narrow window but the contract still wants a clean 404.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"session {session.id!r} not found or expired",
        ) from exc

    # Refusal carry-through happens before any LLM call — the contract
    # locks the session into the parent's narrative.
    if session.refused:
        try:
            with bind_stage_timer() as timer:
                carry_response = build_refusal_carry_through(
                    request_id=request_id,
                    parent_summary=session.parent_summary,
                    base_url=str(request.base_url),
                )
            response.headers["X-Stage-Timings"] = serialize_header(timer)
            _finalise_turn(
                session.id,
                turn_index,
                question=clean_question,
                is_refusal=True,
                allocation_token=alloc_token,
            )
        except Exception:
            SESSION_STORE.discard_turn(
                session.id, turn_index, allocation_token=alloc_token
            )
            raise
        _record_followup_safe(
            session_id=session.id,
            turn_index=turn_index,
            question=clean_question,
            response=carry_response,
        )
        return carry_response

    # Happy path — brief the planner with prior context, then dispatch
    # to the same pipeline the parent uses.
    try:
        config = LLMConfig.from_env()
    except LLMConfigError as exc:
        SESSION_STORE.discard_turn(
            session.id, turn_index, allocation_token=alloc_token
        )
        logger.error("LLM not configured: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "LLM service is not configured",
        ) from exc

    chat_client = HttpChatClient(config)
    prelude = render_followup_system_prompt(session, clean_question)
    analyze_request = AnalyzeRequest(
        workspace=session.workspace_dir,
        filename=session.filename,
        dataset=session.dataset,
        question=clean_question,
        prelude=prelude,
        request_id=request_id,
        is_followup=True,
        base_url=str(request.base_url),
        # Multi-file parent turns persist their auxiliary filenames on
        # the session so the follow-up rebuilds the SAME table set;
        # without this the follow-up silently degrades to single-file
        # and any join referencing a secondary table vanishes.
        # (CodeRabbit #17 round-15 Critical.)
        extra_filenames=session.extra_filenames,
        # Sampling decisions are session-scoped (the file on disk doesn't
        # change between turns); inherit them so every follow-up emits
        # Evidence with the same disclosure as its parent — required by
        # README §3.3 雷7 / §7.2 #7.
        sampling_rate=session.sampling_rate,
        sampling_note=session.sampling_note,
    )
    timer: StageTimer | None = None
    try:
        with bind_stage_timer() as timer:
            analyze_response = await handle_analyze(
                analyze_request, chat_client=chat_client
            )
        response.headers["X-Stage-Timings"] = serialize_header(timer)
    except AnalyzeFailure as exc:
        SESSION_STORE.discard_turn(
            session.id, turn_index, allocation_token=alloc_token
        )
        # Forward stage timings on error too — see analyze.py for rationale.
        timings_header = serialize_header(timer) if timer is not None else "{}"
        raise HTTPException(
            exc.status_code,
            str(exc),
            headers={"X-Stage-Timings": timings_header},
        ) from exc
    except Exception:
        SESSION_STORE.discard_turn(
            session.id, turn_index, allocation_token=alloc_token
        )
        raise

    # Merge the new turn's findings/cohorts/anchors into the session so
    # subsequent follow-ups see them. The parent's findings stay first —
    # the planner may need them as historical context — and new findings
    # are appended in their own order.
    #
    # Concurrent follow-ups against this parent are serialised by the
    # per-session lock acquired in `allocate_follow_up_turn`, so the
    # three rebinds below run as a unit relative to other follow-ups.
    # Each individual rebind is also atomic under the GIL; a concurrent
    # `SESSION_STORE.get()` can therefore only observe consistent
    # snapshots (old triple or new triple), never a half-mutated state.
    new_findings = list(session.findings) + list(analyze_response.findings)
    new_cohorts_combined = list(session.cohorts) + list(
        extract_cohorts(analyze_response.findings, turn_index=turn_index)
    )
    new_anchors = list(session.chart_anchors) + [
        c.html_anchor for c in analyze_response.charts
    ]
    session.findings = new_findings
    session.cohorts = new_cohorts_combined
    session.chart_anchors = new_anchors
    _finalise_turn(
        session.id,
        turn_index,
        question=clean_question,
        is_refusal=analyze_response.is_refusal,
        allocation_token=alloc_token,
    )
    _record_followup_safe(
        session_id=session.id,
        turn_index=turn_index,
        question=clean_question,
        response=analyze_response,
    )
    return analyze_response


def _finalise_turn(
    session_id: str,
    turn_index: int,
    *,
    question: str,
    is_refusal: bool,
    allocation_token: int,
) -> None:
    """Replace the placeholder turn with the real question/refusal flag.

    The store may have evicted the session in the gap between
    `allocate_follow_up_turn` and now (LRU pressure or TTL). We map that
    to the same 404 the lookup path uses — the response is otherwise
    already valid; the only thing the client loses is the trace entry.
    """

    try:
        SESSION_STORE.set_turn_response(
            session_id,
            turn_index,
            question=question,
            is_refusal=is_refusal,
            allocation_token=allocation_token,
        )
    except KeyError as exc:
        logger.warning(
            "session %s evicted before turn %d could be finalised", session_id, turn_index
        )
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"session {session_id!r} not found or expired",
        ) from exc


def _record_followup_safe(
    *,
    session_id: str,
    turn_index: int,
    question: str,
    response: AnalyzeResponse,
) -> None:
    """Best-effort write to the durable history index.

    Mirrors `analyze.py`'s parent-side recorder hook: the recorder
    already swallows sqlite errors internally, but this outer
    try/except catches anything outside that contract (e.g. a future
    refactor that changes the recorder signature) so the route never
    propagates a history-side failure to the client.
    """

    try:
        recorder = get_session_recorder()
        recorder.record_followup(
            session_id=session_id,
            turn_index=turn_index,
            question=question,
            response=response,
        )
        # Refresh the rich state JSON now that the in-memory Session
        # has the new turn's findings / cohorts / chart anchors merged
        # in. Without this update, a backend restart between turn N
        # and turn N+1 would resume the session at turn N's state,
        # losing the most recent context that the planner prelude
        # depends on.
        live_session = SESSION_STORE.get(session_id)
        if live_session is not None:
            from app.session.serde import session_to_dict
            recorder.record_state(session_id, session_to_dict(live_session))
    except Exception:  # side-channel; never fail the request
        logger.exception(
            "history recorder: follow-up persist raised for %s/%d",
            session_id,
            turn_index,
        )


# ---------------------------------------------------------------------------
# Streaming variant: /v1/follow-up/stream
# ---------------------------------------------------------------------------


@router.post("/follow-up/stream")
async def follow_up_stream(body: FollowUpRequest, request: Request) -> StreamingResponse:
    """NDJSON-streaming variant of `/v1/follow-up`.

    Same event shape as `/v1/analyze/stream`:

      {"type":"stage","name":"profile","status":"start"}
      ... (7 stages, 2 events each: start + end) ...
      {"type":"result","data":<AnalyzeResponse>,"stage_timings":{...}}

    Refusal carry-through (parent was refused) is fast and emits no
    stage events — only a single `result` with `is_refusal=True`. The
    SPA's StageTimeline component handles "no events received" by
    showing all stages as pending → done in one step.
    """
    clean_question = body.question.strip()
    if not clean_question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "question must not be empty")

    session = SESSION_STORE.resolve(body.parent_id)
    if session is None:
        # Same auto-resume fallback as the non-streaming endpoint;
        # see the docstring on `try_resume_session`.
        session = try_resume_session(body.parent_id)
    if session is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"session {body.parent_id!r} not found or expired",
        )

    try:
        request_id, turn_index, alloc_token = SESSION_STORE.allocate_follow_up_turn(
            session.id, id_factory=make_followup_id
        )
    except KeyError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"session {session.id!r} not found or expired",
        ) from exc

    # Refusal carry-through: emit a single result event immediately. The
    # frontend can show "No stage detail" (refusal carry doesn't run any
    # of the analyzer pipeline — the canonical refusal text is built
    # locally without an LLM call).
    if session.refused:
        try:
            with bind_stage_timer() as timer:
                carry_response = build_refusal_carry_through(
                    request_id=request_id,
                    parent_summary=session.parent_summary,
                    base_url=str(request.base_url),
                )
            _finalise_turn(
                session.id,
                turn_index,
                question=clean_question,
                is_refusal=True,
                allocation_token=alloc_token,
            )
            _record_followup_safe(
                session_id=session.id,
                turn_index=turn_index,
                question=clean_question,
                response=carry_response,
            )
        except Exception:
            SESSION_STORE.discard_turn(
                session.id, turn_index, allocation_token=alloc_token
            )
            raise

        async def carry_stream() -> AsyncIterator[bytes]:
            payload = {
                "type": "result",
                "data": carry_response.model_dump(mode="json"),
                "stage_timings": timer.as_payload(),
            }
            yield (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8")

        return StreamingResponse(
            carry_stream(),
            media_type="application/x-ndjson; charset=utf-8",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # Happy path — same machinery as /v1/analyze/stream.
    try:
        config = LLMConfig.from_env()
    except LLMConfigError as exc:
        SESSION_STORE.discard_turn(
            session.id, turn_index, allocation_token=alloc_token
        )
        logger.error("LLM not configured: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "LLM service is not configured",
        ) from exc

    chat_client = HttpChatClient(config)
    prelude = render_followup_system_prompt(session, clean_question)
    analyze_request = AnalyzeRequest(
        workspace=session.workspace_dir,
        filename=session.filename,
        dataset=session.dataset,
        question=clean_question,
        prelude=prelude,
        request_id=request_id,
        is_followup=True,
        base_url=str(request.base_url),
        extra_filenames=session.extra_filenames,
        sampling_rate=session.sampling_rate,
        sampling_note=session.sampling_note,
    )

    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def encode(payload: dict[str, object]) -> bytes:
        return (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")

    def emit(payload: dict[str, object]) -> None:
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
            return
        if idx + 1 < len(STAGE_ORDER):
            emit({
                "type": "stage",
                "name": STAGE_ORDER[idx + 1],
                "status": "start",
            })

    async def runner() -> None:
        timer: StageTimer | None = None
        turn_finalized = False

        def on_finalize_token(delta: str) -> None:
            # Live `summary` deltas as the finalize LLM streams its
            # JSON response. Frontend accumulates these into a
            # progressive summary so the user doesn't stare at a
            # silent spinner during the 10-15 s narrative call.
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
            # See api/analyze.py's identical hook — emit one chip per
            # op kind as the planner LLM closes each `"kind":"<name>"`
            # JSON value, so the user sees the plan being assembled.
            emit({
                "type": "partial",
                "field": "plan_op",
                "kind": kind,
            })

        try:
            emit({"type": "stage", "name": STAGE_ORDER[0], "status": "start"})
            try:
                with bind_plan_op_listener(on_plan_op):
                    with bind_finalize_token_listener(on_finalize_token):
                     with bind_finalize_finding_listener(on_finalize_finding):
                      with bind_finalize_recommendation_listener(on_finalize_recommendation):
                        with bind_stage_timer(listener=on_stage) as timer:
                            analyze_response = await handle_analyze(
                                analyze_request, chat_client=chat_client
                            )
            except AnalyzeFailure as exc:
                SESSION_STORE.discard_turn(
                    session.id, turn_index, allocation_token=alloc_token
                )
                emit({
                    "type": "error",
                    "status": exc.status_code,
                    "detail": str(exc),
                    "stage_timings": (
                        timer.as_payload() if timer is not None else {}
                    ),
                })
                return
            except Exception as exc:
                SESSION_STORE.discard_turn(
                    session.id, turn_index, allocation_token=alloc_token
                )
                logger.exception("follow-up/stream: handler raised")
                emit({
                    "type": "error",
                    "status": 500,
                    "detail": f"internal error: {exc}",
                    "stage_timings": (
                        timer.as_payload() if timer is not None else {}
                    ),
                })
                return

            # Merge new turn into session (mirrors the non-streaming
            # endpoint's post-handler bookkeeping; see follow_up() above
            # for full commentary on each rebind).
            new_findings = list(session.findings) + list(analyze_response.findings)
            new_cohorts_combined = list(session.cohorts) + list(
                extract_cohorts(analyze_response.findings, turn_index=turn_index)
            )
            new_anchors = list(session.chart_anchors) + [
                c.html_anchor for c in analyze_response.charts
            ]
            session.findings = new_findings
            session.cohorts = new_cohorts_combined
            session.chart_anchors = new_anchors
            _finalise_turn(
                session.id,
                turn_index,
                question=clean_question,
                is_refusal=analyze_response.is_refusal,
                allocation_token=alloc_token,
            )
            turn_finalized = True
            _record_followup_safe(
                session_id=session.id,
                turn_index=turn_index,
                question=clean_question,
                response=analyze_response,
            )
            emit({
                "type": "result",
                "data": analyze_response.model_dump(mode="json"),
                "stage_timings": timer.as_payload(),
            })
        except asyncio.CancelledError:
            # Client disconnected mid-stream → stream() calls task.cancel(),
            # which raises CancelledError here. CancelledError extends
            # BaseException (not Exception) since 3.8, so the broad
            # `except Exception` below cannot reach it; without this
            # explicit branch the per-turn allocation lock leaks and the
            # next follow-up on this session blocks forever waiting for it.
            if not turn_finalized:
                SESSION_STORE.discard_turn(
                    session.id, turn_index, allocation_token=alloc_token
                )
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("follow-up/stream: unhandled error")
            emit({
                "type": "error",
                "status": 500,
                "detail": f"internal error: {exc}",
                "stage_timings": {},
            })
        finally:
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
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
