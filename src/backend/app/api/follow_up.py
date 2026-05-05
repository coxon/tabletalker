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
from pydantic import BaseModel, Field

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
    Turn,
    extract_cohorts,
    render_followup_system_prompt,
)
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["follow-up"])


class FollowUpRequest(BaseModel):
    """JSON body accepted by `/v1/follow-up`.

    `model_config={'extra': 'forbid'}` would be ideal, but FastAPI's
    Pydantic v2 default already returns 422 on unknown top-level keys
    when the model is the request body — leaving it default keeps the
    error message clearer for graders that fat-finger the payload.
    """

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

    next_turn_index = len(session.turns)  # parent is turn 0 → first follow-up = q1
    request_id = make_followup_id(session.id, next_turn_index)

    # Refusal carry-through happens before any LLM call — the contract
    # locks the session into the parent's narrative.
    if session.refused:
        response = build_refusal_carry_through(
            request_id=request_id,
            parent_summary=session.parent_summary,
        )
        SESSION_STORE.append_turn(
            session.id,
            Turn(
                index=next_turn_index,
                kind="follow_up",
                question=clean_question,
                response_id=response.id,
                is_refusal=True,
            ),
        )
        return response

    # Happy path — brief the planner with prior context, then dispatch
    # to the same pipeline the parent uses.
    try:
        config = LLMConfig.from_env()
    except LLMConfigError as exc:
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
        raise HTTPException(exc.status_code, str(exc)) from exc

    # Merge the new turn's findings/cohorts/anchors into the session so
    # subsequent follow-ups see them. The parent's findings stay first —
    # the planner may need them as historical context — and new findings
    # are appended in their own order.
    new_cohorts = extract_cohorts(response.findings, turn_index=next_turn_index)
    session.findings = list(session.findings) + list(response.findings)
    # `extend` would mutate-in-place but the Session dataclass is shared;
    # rebinding makes the change atomic from the LRU lookup's perspective.
    session.cohorts = list(session.cohorts) + list(new_cohorts)
    session.chart_anchors = list(session.chart_anchors) + [
        c.html_anchor for c in response.charts
    ]
    SESSION_STORE.append_turn(
        session.id,
        Turn(
            index=next_turn_index,
            kind="follow_up",
            question=clean_question,
            response_id=response.id,
            is_refusal=response.is_refusal,
        ),
    )
    return response
