"""Planner — turn a natural-language question into a typed `Plan`.

Flow:
  1. Build a system prompt that describes the available ops and the
     register convention.
  2. Send {system, user (question + table preview)} to the LLM.
  3. Parse JSON, validate against `Plan`, return.
  4. On schema-validation failure, retry up to 2 more times, feeding
     the validation error back to the model so it can self-correct.

The system prompt lives in `_PLANNER_PROMPT`. Keep it terse — the
hackathon LLMs have token budgets, and a long prompt eats into the
plan's max_tokens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
from pydantic import ValidationError

from app.spreadsheet.llm import ChatClient
from app.spreadsheet.schema import Plan

# Maximum number of retries when the LLM's output fails Plan validation.
# Each retry includes the validation error in the conversation so the model
# can self-correct. 2 retries (3 attempts total) is empirically enough for
# qwen3.6-plus on simple questions.
MAX_PLAN_RETRIES = 2


@dataclass
class PlanRequest:
    question: str
    # Tables visible in the workspace, in upload order. The first entry is
    # the "primary" table (used by the refusal heuristic and as the default
    # Evidence.table for downstream rows that don't carry per-table
    # provenance). Subsequent entries enable cross-table joins — the
    # planner is expected to emit one `load_csv` / `load_excel` per table
    # and a `join` op stitching them together.
    #
    # Each entry is `(filename, preview_df)`. `preview_df` is the first 5
    # rows already read; we serialise it into the user prompt so the LLM
    # sees the actual columns without having to guess from the filename.
    tables: list[tuple[str, pd.DataFrame]]
    # Optional prelude — the follow-up route prepends a session prompt
    # (parent question, named cohorts, prior findings) so the LLM can
    # resolve pronouns without us having to graft session awareness into
    # the planner core. `None` keeps single-turn analyze unchanged.
    prelude: str | None = None

    @property
    def primary_filename(self) -> str:
        """Convenience accessor for callers that still want a single file
        (refusal heuristic, default Evidence.table). The first uploaded
        file is the primary; subsequent files are auxiliary join sources."""
        if not self.tables:
            raise ValueError("PlanRequest.tables must contain at least one entry")
        return self.tables[0][0]


class PlannerError(Exception):
    """LLM never produced a valid Plan after all retries."""


_PLANNER_PROMPT = """\
You translate a user's question about a tabular file into a typed JSON Plan.

## Plan shape

{
  "ops": [ { "kind": "...", "out": "<unique-name>", ... }, ... ],
  "answer": "<name of the op whose output is shown to the user>"
}

Each op produces a register slot named `out`. Later ops reference earlier
outputs by name (`src`, `left`, `right`). Op order in the list IS the
execution order — never reference a slot before it's produced.

## Op kinds (use only these)

- load_csv  { kind, out, path }
- load_excel { kind, out, path, sheet? }
- select_columns { kind, out, src, columns: [..] }
- filter_rows { kind, out, src, where: <expr> }
- add_column { kind, out, src, name, expr: <expr> }
- group_by { kind, out, src, by: [..] }    # output feeds into `aggregate`
- aggregate { kind, out, src, aggs: [{ column, fn, as }] }
    fn ∈ {sum, mean, count, min, max, median, nunique}
- sort { kind, out, src, by: [..], desc?: [bool] }
- head { kind, out, src, n }
- tail { kind, out, src, n }
- join { kind, out, left, right, on: [..], how?: inner|left|right|outer }
- pivot { kind, out, src, index: [..], columns, values, aggfn? }
- melt { kind, out, src, id_vars: [..], value_vars?, var_name?, value_name? }
- to_table { kind, out, src, title? }
- to_chart { kind, out, src, chart: bar|line|pie|scatter, x, y, title? }

## Expression DSL (for filter_rows.where and add_column.expr)

  Literal:  { "lit": <number|string|bool|null> }
  Column :  { "col": "<name>" }
  BinOp  :  { "op": "+|-|*|/|==|!=|<|<=|>|>=|and|or", "args": [<expr>, <expr>] }
  Call   :  { "fn": "abs|round|min|max|lower|upper|len|if", "args": [<expr>, ...] }

Do NOT emit raw Python expressions. Always use the DSL above.

## CRITICAL RULE

The plan MUST end with a `to_table` or `to_chart` op. The `answer` field
MUST reference this render op. Raw DataFrames cannot be returned to the
user — they must be wrapped in a render op. Example ending:

  { "kind": "to_table", "out": "result", "src": "filtered", "title": "Results" }

If the question asks for a chart, end with `to_chart`. Otherwise end with `to_table`.

## Output format

Return ONLY the JSON Plan. No prose, no markdown fences. Start with `{`.
"""


def _user_message(req: PlanRequest) -> str:
    """Render the per-request user message: every table's columns + 5-row
    preview, then the user's question.

    Single-table requests render compactly (header + columns + preview);
    multi-table requests prepend a "you have N tables, choose loads + joins"
    sentence so the LLM understands it's allowed (and expected) to emit
    multiple `load_*` ops and stitch them with `join`.
    """

    if not req.tables:
        raise ValueError("PlanRequest.tables must contain at least one entry")

    chunks: list[str] = []
    if len(req.tables) > 1:
        names = ", ".join(name for name, _ in req.tables)
        chunks.append(
            f"{len(req.tables)} files are available in the workspace: {names}.\n"
            f"Emit one `load_csv` or `load_excel` per file, then `join` "
            f"them on shared keys before further analysis if the question "
            f"requires data from more than one file."
        )
    for name, preview in req.tables:
        # `columns` may be non-string (int, tuple from MultiIndex flattening,
        # etc.) — coerce defensively so the prompt never crashes on weird
        # CSV headers.
        columns = ", ".join(str(c) for c in preview.columns)
        preview_csv = preview.head(5).to_csv(index=False)
        chunks.append(
            f"--- File: {name} ---\n"
            f"Columns: {columns}\n"
            f"First 5 rows (CSV):\n{preview_csv}"
        )
    chunks.append(
        f"User question: {req.question}\n"
        f"Emit the JSON Plan now."
    )
    return "\n".join(chunks)


async def make_plan(client: ChatClient, req: PlanRequest) -> Plan:
    """Ask the LLM for a plan, retrying on schema-validation failure."""

    # When the follow-up route hands us a session prelude, splice it in
    # as a second system message — keeps the canonical planner system
    # prompt unchanged so the schema/op rules don't get diluted.
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _PLANNER_PROMPT},
    ]
    if req.prelude:
        messages.append({"role": "system", "content": req.prelude})
    messages.append({"role": "user", "content": _user_message(req)})

    last_error: str | None = None
    for attempt in range(MAX_PLAN_RETRIES + 1):
        raw = await client.chat(
            messages,
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = f"output was not valid JSON: {exc}"
        else:
            try:
                return Plan.model_validate(data)
            except ValidationError as exc:
                last_error = f"plan failed schema validation: {exc.errors()}"

        if attempt < MAX_PLAN_RETRIES:
            # Feed the failure back so the model can self-correct.
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    f"That output was rejected: {last_error}\n"
                    "Emit a corrected JSON Plan now. JSON only, no prose."
                ),
            })

    raise PlannerError(
        f"LLM did not produce a valid Plan after {MAX_PLAN_RETRIES + 1} attempts: "
        f"{last_error}"
    )
