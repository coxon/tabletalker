"""Session ↔ JSON serde for SQLite persistence.

Why a dedicated module: the resume flow needs to round-trip a `Session`
through SQLite (parent restart loses the in-memory dict) plus a
workspace dir on disk. The dataclass holds a few non-trivial nested
shapes (`Finding`, `Evidence`, `CohortDef`, `Turn`) that don't have
their own ``to_dict`` helpers; centralising the conversion here keeps
SessionRecorder / the resume endpoint from each reaching into the
internals.

Symmetry: `session_to_dict(s)` and `session_from_dict(d, workspace)`
are inverses for the fields that matter to follow-up planning. We
explicitly do NOT round-trip the `_follow_up_lock` (a fresh lock is
fine after a process restart) or `created_at` / `last_used_at` (the
new in-memory copy gets stamped at resume time so TTL eviction works
relative to when the session was *re-bound*, not when it was first
created — otherwise an old session would be evicted on the very next
TTL sweep and the resume would be pointless).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from app.analyze.schema import Evidence, Finding
from app.session.cohort import CohortDef
from app.session.store import Session, Turn


def _evidence_to_dict(ev: Evidence) -> dict[str, Any]:
    return {
        "dataset": ev.dataset,
        "table": ev.table,
        "columns": list(ev.columns),
        "filters": ev.filters,
        "aggregation": ev.aggregation,
        "value": ev.value,
        "row_count": ev.row_count,
    }


def _evidence_from_dict(d: dict[str, Any]) -> Evidence:
    # `value` is required by the schema (`...`), but a legacy session
    # row from before this field was strict could still be missing it
    # — coerce to "" rather than crash the resume path.
    raw_value = d.get("value")
    if raw_value is None:
        raw_value = ""
    return Evidence(
        dataset=str(d.get("dataset", "")),
        table=str(d.get("table", "")),
        columns=[str(c) for c in (d.get("columns") or [])],
        filters=str(d.get("filters", "")),
        aggregation=str(d.get("aggregation", "")),
        value=raw_value,
        row_count=d.get("row_count"),
    )


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "title": f.title,
        "detail": f.detail,
        "evidence": [_evidence_to_dict(ev) for ev in f.evidence],
    }


def _finding_from_dict(d: dict[str, Any]) -> Finding:
    return Finding(
        title=str(d.get("title", "")),
        detail=str(d.get("detail", "")),
        evidence=[_evidence_from_dict(ev) for ev in (d.get("evidence") or [])],
    )


def _cohort_to_dict(c: CohortDef) -> dict[str, Any]:
    return {
        "name": c.name,
        "filters": c.filters,
        "columns_used": list(c.columns_used),
        "row_count": c.row_count,
        "introduced_in_turn": c.introduced_in_turn,
    }


def _cohort_from_dict(d: dict[str, Any]) -> CohortDef:
    return CohortDef(
        name=str(d.get("name", "")),
        filters=str(d.get("filters", "")),
        columns_used=[str(c) for c in (d.get("columns_used") or [])],
        row_count=int(d.get("row_count", 0)),
        introduced_in_turn=int(d.get("introduced_in_turn", 0)),
    )


def _turn_to_dict(t: Turn) -> dict[str, Any]:
    return {
        "index": t.index,
        "kind": t.kind,
        "question": t.question,
        "response_id": t.response_id,
        "is_refusal": t.is_refusal,
    }


def _turn_from_dict(d: dict[str, Any]) -> Turn:
    return Turn(
        index=int(d.get("index", 0)),
        kind=d.get("kind", "parent"),
        question=str(d.get("question", "")),
        response_id=str(d.get("response_id", "")),
        is_refusal=bool(d.get("is_refusal", False)),
    )


def session_to_dict(s: Session) -> dict[str, Any]:
    """Snapshot of a Session as plain primitives for JSON storage.

    Excludes `workspace_dir` (resolved at resume time from the session
    id), `_follow_up_lock` (fresh lock on resume), and the timestamps
    (re-stamped on resume). Everything else the planner prelude
    depends on round-trips here.
    """

    return {
        "id": s.id,
        "filename": s.filename,
        "dataset": s.dataset,
        "original_question": s.original_question,
        "findings": [_finding_to_dict(f) for f in s.findings],
        "parent_summary": s.parent_summary,
        "cohorts": [_cohort_to_dict(c) for c in s.cohorts],
        "chart_anchors": list(s.chart_anchors),
        "refused": s.refused,
        "sampling_rate": s.sampling_rate,
        "sampling_note": s.sampling_note,
        "extra_filenames": list(s.extra_filenames),
        "turns": [_turn_to_dict(t) for t in s.turns],
    }


def session_from_dict(d: dict[str, Any], workspace_dir: Path) -> Session:
    """Rebuild a Session from `session_to_dict` output + a workspace dir.

    The caller is expected to have ensured `workspace_dir` exists and
    contains the original uploaded files (primary + any extras). On a
    persistent-workspace deploy this is just `make_workspace(s.id)`;
    on a tempdir deploy resume is impossible and the caller should
    refuse before reaching this function.
    """

    now = time.time()
    return Session(
        id=str(d.get("id", "")),
        workspace_dir=workspace_dir,
        filename=str(d.get("filename", "")),
        dataset=str(d.get("dataset", "")),
        original_question=str(d.get("original_question", "")),
        findings=[_finding_from_dict(f) for f in (d.get("findings") or [])],
        parent_summary=str(d.get("parent_summary", "")),
        cohorts=[_cohort_from_dict(c) for c in (d.get("cohorts") or [])],
        chart_anchors=[str(a) for a in (d.get("chart_anchors") or [])],
        refused=bool(d.get("refused", False)),
        sampling_rate=d.get("sampling_rate"),
        sampling_note=d.get("sampling_note"),
        extra_filenames=tuple(d.get("extra_filenames") or ()),
        turns=[_turn_from_dict(t) for t in (d.get("turns") or [])],
        created_at=now,
        last_used_at=now,
        _follow_up_lock=threading.Lock(),
    )
