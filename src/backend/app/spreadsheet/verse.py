"""TableVerse — the user-facing render of a Plan step.

Internal naming is `Op` / `Plan` (engineering-clear). What the *user*
sees in the report is a sequence of `TableVerse`s — each verse is one
human-readable line in the trace, like a stanza in a long poem.

Why this lives in its own file: when we change the user-facing wording
(verse → step → stanza → whatever), it's a single-file edit. The engine
never imports the rendering layer.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.spreadsheet.schema import Op, OpResult

# Map op kind → user-friendly verb shown in the trace.
# Keep these short and lowercase — they read like song titles, not API names.
_VERB: dict[str, str] = {
    "load_csv": "load",
    "load_excel": "load",
    "select_columns": "select",
    "filter_rows": "filter",
    "add_column": "derive",
    "group_by": "group",
    "aggregate": "aggregate",
    "sort": "sort",
    "head": "take",
    "tail": "take",
    "join": "join",
    "pivot": "pivot",
    "melt": "melt",
    "to_table": "render",
    "to_chart": "render",
}


class TableVerse(BaseModel):
    """One stanza of the report — one op's worth of human-facing trace."""

    n: int  # 1-indexed verse number
    verb: str
    label: str  # short human-readable phrasing of *what* this verse did
    out: str  # which register slot it produced (lets the UI link verses)
    ms: float
    rows_out: int | None = None
    cols_out: int | None = None


def render_label(op: Op) -> str:
    """Best-effort human label for an op. Kept deliberately terse."""

    kind = op.kind
    if kind == "load_csv":
        return op.path  # type: ignore[union-attr]
    if kind == "load_excel":
        sheet = getattr(op, "sheet", 0)
        path = op.path  # type: ignore[union-attr]
        return f"{path} [sheet={sheet}]"
    if kind == "select_columns":
        cols = getattr(op, "columns", [])
        return ", ".join(cols)
    if kind == "filter_rows":
        return "where …"  # full expr would clutter the trace
    if kind == "add_column":
        return f"{getattr(op, 'name', '?')} = …"
    if kind == "group_by":
        return "by " + ", ".join(getattr(op, "by", []))
    if kind == "aggregate":
        aggs = getattr(op, "aggs", [])
        return ", ".join(f"{a.fn}({a.column})" for a in aggs)
    if kind == "sort":
        by = getattr(op, "by", [])
        desc = getattr(op, "desc", None) or [False] * len(by)
        return ", ".join(f"{c}{' desc' if d else ''}" for c, d in zip(by, desc, strict=False))
    if kind in ("head", "tail"):
        n = getattr(op, "n", 10)
        return f"{kind} {n}"
    if kind == "join":
        on = ", ".join(getattr(op, "on", []))
        how = getattr(op, "how", "inner")
        return f"{getattr(op, 'left', '?')} ⋈ {getattr(op, 'right', '?')} on {on} ({how})"
    if kind == "pivot":
        return f"{getattr(op, 'index', '?')} × {getattr(op, 'columns', '?')}"
    if kind == "melt":
        return "wide → long"
    if kind == "to_table":
        return getattr(op, "title", None) or "table"
    if kind == "to_chart":
        return f"{getattr(op, 'chart', '?')} chart"
    return kind


def to_verse(n: int, op: Op, result: OpResult) -> TableVerse:
    return TableVerse(
        n=n,
        verb=_VERB.get(op.kind, op.kind),
        label=render_label(op),
        out=op.out,
        ms=result.ms,
        rows_out=result.rows,
        cols_out=result.cols,
    )
