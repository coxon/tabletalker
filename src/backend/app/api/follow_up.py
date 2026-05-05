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

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.analyze.handler import (
    AnalyzeFailure,
    AnalyzeRequest,
    build_refusal_carry_through,
    handle_analyze,
    make_followup_id,
)
from app.analyze.schema import AnalyzeResponse
from app.session import (
    SESSION_STORE,
    extract_cohorts,
    render_followup_system_prompt,
)
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError

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
async def follow_up(body: FollowUpRequest) -> AnalyzeResponse:
    """Run a follow-up analysis against an existing session."""

    clean_question = body.question.strip()
    if not clean_question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "question must not be empty")

    session = SESSION_STORE.get(body.parent_id)
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
            response = build_refusal_carry_through(
                request_id=request_id,
                parent_summary=session.parent_summary,
            )
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
        return response

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
    request = AnalyzeRequest(
        workspace=session.workspace_dir,
        filename=session.filename,
        dataset=session.dataset,
        question=clean_question,
        prelude=prelude,
        request_id=request_id,
        is_followup=True,
    )
    try:
        response = await handle_analyze(request, chat_client=chat_client)
    except AnalyzeFailure as exc:
        SESSION_STORE.discard_turn(
            session.id, turn_index, allocation_token=alloc_token
        )
        raise HTTPException(exc.status_code, str(exc)) from exc
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
    new_findings = list(session.findings) + list(response.findings)
    new_cohorts_combined = list(session.cohorts) + list(
        extract_cohorts(response.findings, turn_index=turn_index)
    )
    new_anchors = list(session.chart_anchors) + [
        c.html_anchor for c in response.charts
    ]
    session.findings = new_findings
    session.cohorts = new_cohorts_combined
    session.chart_anchors = new_anchors
    _finalise_turn(
        session.id,
        turn_index,
        question=clean_question,
        is_refusal=response.is_refusal,
        allocation_token=alloc_token,
    )
    return response


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
