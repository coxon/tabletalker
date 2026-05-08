"""Manifest parser for batch evaluation.

The evaluator describes their test cases in one of two formats:

  - **JSONL**: one task per line, each a JSON object. Most ergonomic
    for programmatic submission.
  - **CSV**: one task per row with fixed column headers. Most ergonomic
    for evaluators editing in Excel/Numbers (which is the dominant
    workflow on the hackathon side).

Both materialise into the same `BatchTask` shape so the rest of the
pipeline doesn't care which format came in.

A manifest task references its data files **by basename**. The route
layer is responsible for saving every uploaded data file into the same
workspace, so when the runner dispatches to `handle_analyze` the file
the task names is already on disk under that name.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

# Keep the optional fields aligned with `app.api.analyze`'s Form params
# so a manifest row reads like a function call to /v1/analyze. Renames
# here force a manifest re-export, so we deliberately mirror the route.
#
# Two manifest dialects are supported, auto-detected per row:
#   1. **Native** — the original tabletalker shape with `question` + `file`
#      + optional `extra_files` / `dataset` / `sampling_*`.
#   2. **Organizer-official** (赛题4 §4) — `user_query` instead of
#      `question`, `type` ∈ {standard_analysis, follow_up, unanswerable},
#      `parent_id` for follow-ups, optional `dataset` / `files`. Reference
#      fields (`reference_findings`, `reference_charts`, `scoring_hints`,
#      `expected_behavior`, `acceptable_response_keywords`,
#      `forbidden_keywords`) are accepted but ignored — they're hints to
#      the evaluator, not inputs to the agent.
# The parser normalises both into the same `BatchTask`; the batch route
# uses the presence of `user_query` / `type` to decide whether to render
# the §5.2-style `predictions.jsonl + reports/` output bundle vs xlsx.
_REQUIRED_NATIVE = {"question", "file"}
_REQUIRED_OFFICIAL = {"user_query"}
_NATIVE_KEYS = _REQUIRED_NATIVE | {
    "id",          # caller-supplied task id; defaults to row index
    "extra_files", # auxiliary file names (list[str] in JSONL, ; or , in CSV)
    "dataset",
    "sampling_rate",
    "sampling_note",
}
_OFFICIAL_KEYS = _REQUIRED_OFFICIAL | {
    "id",
    "type",                          # standard_analysis | follow_up | unanswerable
    "parent_id",                     # only meaningful when type == follow_up
    "dataset",                       # organizer dataset label, also used as filename hint
    "file",                          # tabletalker extension: explicit primary file basename
    "files",                         # alternative: list whose first element is primary
    "extra_files",
    "sampling_rate",
    "sampling_note",
    # Reference / scoring hint fields — accepted, never consumed.
    "reference_findings",
    "reference_charts",
    "scoring_hints",
    "expected_behavior",
    "acceptable_response_keywords",
    "forbidden_keywords",
}


_OFFICIAL_TYPES = {"standard_analysis", "follow_up", "unanswerable"}


class ManifestError(ValueError):
    """Manifest is malformed; raised before any task runs."""


@dataclass(frozen=True)
class BatchTask:
    """One row of the manifest, ready to dispatch.

    `id` is what the output sheet keys on; if the manifest didn't supply
    one, the parser fills in a 1-based row index so duplicates can't
    collide. `file` + `extra_files` are basenames; the runner trusts
    that the workspace already contains them (the route saved them).

    `task_type` and `parent_id` carry the official-§4 dialect through to
    the runner so it can fan a follow-up out via `/v1/follow-up` rather
    than as an independent analysis. Native-dialect tasks default to
    `task_type="standard_analysis"` and `parent_id=None`.
    """

    id: str
    question: str
    file: str  # primary file basename
    extra_files: tuple[str, ...] = ()
    dataset: str | None = None
    sampling_rate: float | None = None
    sampling_note: str | None = None
    task_type: str = "standard_analysis"
    parent_id: str | None = None


def parse_manifest(content: bytes, filename: str) -> list[BatchTask]:
    """Parse a manifest from raw bytes, choosing JSONL vs CSV by suffix.

    `filename` only contributes its lowercase suffix; the actual content
    is what gets parsed. Falls back to JSONL (the default) if we can't
    tell from the suffix — JSONL is line-oriented and easier to surface
    a sensible error from than a misidentified CSV.

    Raises `ManifestError` with a row-numbered message on any structural
    problem so the route can surface a 400 with actionable diagnostics
    rather than dumping a stack trace.
    """

    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    # CodeRabbit #16 round-2: decode strictly so a manifest with a
    # bad encoding fails closed (with a helpful error) rather than
    # silently corrupting task fields via U+FFFD replacements.
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ManifestError(
            f"manifest {filename!r}: not valid UTF-8 "
            f"(byte {exc.start}: {exc.reason}); save as UTF-8 and retry"
        ) from exc

    if suffix == "csv":
        tasks = _parse_csv(text)
    else:
        # JSONL is the default — covers `.jsonl`, `.ndjson`, no-extension uploads.
        tasks = _parse_jsonl(text)

    # CodeRabbit #16 round-2: surface duplicate task ids before they
    # cause ambiguous downstream state (the result xlsx keys per id
    # and the runner indexes by id). One ManifestError listing every
    # collision is friendlier than letting the evaluator hunt.
    _validate_unique_ids(tasks)
    return tasks


def _validate_unique_ids(tasks: list[BatchTask]) -> None:
    """Raise ManifestError if any `BatchTask.id` is reused.

    A duplicate id means `run_batch`'s per-task results would shadow
    each other in any id-keyed downstream view (xlsx rows are
    distinct, but a future caller indexing by id would silently lose
    data). Fail closed so the manifest gets fixed before submission.
    """
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for task in tasks:
        if task.id in seen:
            duplicates.append(task.id)
        else:
            seen[task.id] = 1
    if duplicates:
        # `dict.fromkeys` preserves first-seen order while deduping —
        # the same id repeated 3× shows up once in the message.
        unique = list(dict.fromkeys(duplicates))
        raise ManifestError(
            f"manifest has duplicate task id(s): {unique}"
        )


# ---------------------------------------------------------------------------
# JSONL
# ---------------------------------------------------------------------------


def _parse_jsonl(text: str) -> list[BatchTask]:
    tasks: list[BatchTask] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ManifestError(
                f"line {line_no}: invalid JSON ({exc.msg})"
            ) from exc
        if not isinstance(obj, dict):
            raise ManifestError(
                f"line {line_no}: expected JSON object, got {type(obj).__name__}"
            )
        tasks.append(_to_task(obj, row_label=f"line {line_no}", index=line_no))
    if not tasks:
        raise ManifestError("manifest is empty (no non-blank lines)")
    return tasks


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def _parse_csv(text: str) -> list[BatchTask]:
    """Parse a CSV manifest. Header row is required.

    Multi-value cells (`extra_files`) accept either `;` or `,` as
    inner separators — `,` is fragile inside a CSV but the dialect's
    quoting handles it; `;` is the friendlier choice for evaluators.
    """

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ManifestError("CSV manifest is empty (no header row)")
    missing = [k for k in _REQUIRED_NATIVE if k not in reader.fieldnames]
    if missing:
        raise ManifestError(
            f"CSV header missing required columns: {missing} "
            f"(present: {reader.fieldnames})"
        )
    tasks: list[BatchTask] = []
    for row_no, row in enumerate(reader, start=2):  # +1 for 1-based, +1 header
        # Skip wholly-blank rows so trailing newlines / template padding
        # don't blow up the manifest.
        #
        # csv.DictReader surfaces extra-column overflow as ``{None: [...]}``
        # — a list, not a string — so the predicate has to be type-safe
        # or a stray trailing comma in a row crashes the whole endpoint
        # with an AttributeError(500). Treat strings via .strip(),
        # lists/tuples as "any element stripped is non-empty", and fall
        # back to `str(v).strip()` for anything else. `None` → empty.
        if all(_is_blank_manifest_value(v) for v in row.values()):
            continue
        # Normalise CSV quirks: dict values are str | None when columns
        # are missing on a row. Empty string → None for optional fields,
        # split for list-shaped fields.
        normalised: dict[str, object] = {}
        for key, raw in row.items():
            if key is None:
                continue
            value = (raw or "").strip()
            if key == "extra_files":
                normalised[key] = _split_extra(value)
            else:
                normalised[key] = value or None
        tasks.append(
            _to_task(normalised, row_label=f"row {row_no}", index=row_no - 1)
        )
    if not tasks:
        raise ManifestError("CSV manifest has a header but no data rows")
    return tasks


def _split_extra(raw: str) -> list[str]:
    if not raw:
        return []
    # Prefer `;` so a comma in a filename (rare but possible) doesn't
    # silently split the cell. Fall back to `,` only if there's no `;`.
    sep = ";" if ";" in raw else ","
    return [tok.strip() for tok in raw.split(sep) if tok.strip()]


def _is_blank_manifest_value(value: object) -> bool:
    """Treat missing / empty / whitespace-only as blank across all csv shapes.

    DictReader yields `str | None` for regular cells but packs extra-column
    overflow under the ``None`` key as `list[str]`. A row that is otherwise
    empty except for a trailing comma would crash the old
    ``(v or "").strip()`` predicate with ``AttributeError: 'list' object
    has no attribute 'strip'`` — a 500 in response to malformed user
    input. The predicate below is total: strings, lists/tuples, None,
    and anything else reduce to a clean bool.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return not any(
            str(item).strip() for item in value if item is not None
        )
    return not str(value).strip()


# ---------------------------------------------------------------------------
# Shared validator
# ---------------------------------------------------------------------------


def _to_task(obj: dict, *, row_label: str, index: int) -> BatchTask:
    """Validate one manifest row → BatchTask.

    Strict-but-tolerant: required fields raise, unknown fields warn (we
    just ignore them) so a manifest written for a future schema doesn't
    fail wholesale on minor field-name drift. Both native (`question`/
    `file`) and organizer-official (`user_query`/`type`) dialects are
    accepted in the same row.
    """

    # ---- Detect dialect ----
    is_official = "user_query" in obj or "type" in obj or "parent_id" in obj
    if is_official and "question" not in obj:
        # Pull `user_query` into `question` for unified downstream handling.
        obj = {**obj, "question": obj.get("user_query", "")}

    # ---- Resolve primary `file` ----
    # Native dialect requires `file` outright. Official dialect may
    # supply `file` (preferred when present), `files` (a list whose
    # first element is the primary), or — as a last resort — derive
    # the filename from `dataset`. Resolution order is least-magic
    # first so a manifest that explicitly names files isn't second-
    # guessed.
    if "file" not in obj or not obj.get("file"):
        files_field = obj.get("files")
        if isinstance(files_field, list) and files_field:
            primary = str(files_field[0]).strip()
            extras_from_files = files_field[1:]
            obj = {
                **obj,
                "file": primary,
                "extra_files": list(obj.get("extra_files") or []) + list(extras_from_files),
            }
        elif is_official and obj.get("dataset"):
            # Convention fallback: dataset label IS the basename. The CLI
            # tool documents this requirement; the route layer should
            # already have aliased uploaded files into matching basenames.
            obj = {**obj, "file": str(obj["dataset"]).strip()}

    missing = [k for k in _REQUIRED_NATIVE if not obj.get(k)]
    if missing:
        raise ManifestError(
            f"{row_label}: missing required fields {missing} "
            f"(accept either native `question`/`file` or official "
            f"`user_query` + `file`/`files`/`dataset`)"
        )

    question = str(obj["question"]).strip()
    file = str(obj["file"]).strip()
    if not question:
        raise ManifestError(f"{row_label}: question must not be blank")
    if not file:
        raise ManifestError(f"{row_label}: file must not be blank")

    raw_extras = obj.get("extra_files") or ()
    if isinstance(raw_extras, str):
        raw_extras = _split_extra(raw_extras)
    elif not isinstance(raw_extras, (list, tuple, set)):
        # A non-string truthy value that isn't list-like (e.g. `123` or
        # `{"foo": 1}`) would otherwise raise `TypeError` from the
        # generator expression below — surface it as a clean 400 with
        # the row label so the grader can fix the manifest, not as a
        # 500 stack trace.
        raise ManifestError(
            f"{row_label}: extra_files must be a string or list of strings; "
            f"got {type(raw_extras).__name__}"
        )
    extras = tuple(str(x).strip() for x in raw_extras if str(x).strip())

    dataset_raw = obj.get("dataset")
    dataset = str(dataset_raw).strip() if dataset_raw not in (None, "") else None

    sampling_rate = _parse_optional_float(
        obj.get("sampling_rate"), label=f"{row_label}.sampling_rate"
    )
    if sampling_rate is not None and not (0.0 < sampling_rate <= 1.0):
        raise ManifestError(
            f"{row_label}: sampling_rate must be in (0, 1]; got {sampling_rate}"
        )

    note_raw = obj.get("sampling_note")
    sampling_note = str(note_raw).strip() if note_raw not in (None, "") else None

    task_id_raw = obj.get("id")
    # Whitespace-only IDs (e.g. ``"   "``) used to slip through the
    # `not in (None, "")` check, producing a BatchTask with id=""
    # downstream. Normalise first, then fall back to the synthetic id
    # if the stripped form is empty.
    task_id_stripped = (
        str(task_id_raw).strip() if task_id_raw is not None else ""
    )
    task_id = task_id_stripped if task_id_stripped else f"task_{index}"

    # ---- Official-only fields ----
    type_raw = obj.get("type")
    if type_raw is None:
        task_type = "standard_analysis"
    else:
        task_type = str(type_raw).strip().lower()
        if task_type not in _OFFICIAL_TYPES:
            raise ManifestError(
                f"{row_label}: type {type_raw!r} not in {sorted(_OFFICIAL_TYPES)}"
            )

    parent_id_raw = obj.get("parent_id")
    parent_id = (
        str(parent_id_raw).strip() if parent_id_raw not in (None, "") else None
    )
    if task_type == "follow_up" and not parent_id:
        raise ManifestError(
            f"{row_label}: type=follow_up requires non-empty `parent_id`"
        )
    if task_type != "follow_up" and parent_id is not None:
        # Defensive: a `parent_id` on a non-follow-up task means the
        # manifest author confused the dialect. Better to reject here
        # than silently ignore the field and produce a wrong response.
        raise ManifestError(
            f"{row_label}: parent_id is only valid for type=follow_up "
            f"(got type={task_type!r})"
        )

    return BatchTask(
        id=task_id,
        question=question,
        file=file,
        extra_files=extras,
        dataset=dataset,
        sampling_rate=sampling_rate,
        sampling_note=sampling_note,
        task_type=task_type,
        parent_id=parent_id,
    )


def _parse_optional_float(value: object, *, label: str) -> float | None:
    if value in (None, "", "null"):
        return None
    # Round-8 (CodeRabbit #16): `bool` is a subclass of `int`, so
    # without this short-circuit `"sampling_rate": true` would silently
    # become `1.0`. A boolean here is almost certainly a typo
    # (mis-cased `"True"` etc.) — fail closed.
    if isinstance(value, bool):
        raise ManifestError(
            f"{label}: must be a number, got boolean ({value!r})"
        )
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{label}: not a number ({value!r})") from exc
