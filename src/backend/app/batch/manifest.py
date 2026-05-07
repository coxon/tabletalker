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
_REQUIRED = {"question", "file"}
_KNOWN_KEYS = _REQUIRED | {
    "id",          # caller-supplied task id; defaults to row index
    "extra_files", # auxiliary file names (list[str] in JSONL, ; or , in CSV)
    "dataset",
    "sampling_rate",
    "sampling_note",
}


class ManifestError(ValueError):
    """Manifest is malformed; raised before any task runs."""


@dataclass(frozen=True)
class BatchTask:
    """One row of the manifest, ready to dispatch.

    `id` is what the output sheet keys on; if the manifest didn't supply
    one, the parser fills in a 1-based row index so duplicates can't
    collide. `file` + `extra_files` are basenames; the runner trusts
    that the workspace already contains them (the route saved them).
    """

    id: str
    question: str
    file: str  # primary file basename
    extra_files: tuple[str, ...] = ()
    dataset: str | None = None
    sampling_rate: float | None = None
    sampling_note: str | None = None


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
    missing = [k for k in _REQUIRED if k not in reader.fieldnames]
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
    fail wholesale on minor field-name drift.
    """

    missing = [k for k in _REQUIRED if not obj.get(k)]
    if missing:
        raise ManifestError(f"{row_label}: missing required fields {missing}")

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

    return BatchTask(
        id=task_id,
        question=question,
        file=file,
        extra_files=extras,
        dataset=dataset,
        sampling_rate=sampling_rate,
        sampling_note=sampling_note,
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
