"""Session state — parent analysis context kept across follow-up turns.

`docs/session-state.md` is the design source of truth. This package
implements the in-memory store, the cohort extractor, and the prompt
assembler the follow-up handler uses to brief the LLM about prior turns.
"""

from app.session.cohort import CohortDef, extract_cohorts
from app.session.prompt import render_followup_system_prompt
from app.session.store import (
    SESSION_STORE,
    Session,
    SessionStore,
    Turn,
    session_from_response,
)

__all__ = [
    "SESSION_STORE",
    "CohortDef",
    "Session",
    "SessionStore",
    "Turn",
    "extract_cohorts",
    "render_followup_system_prompt",
    "session_from_response",
]
