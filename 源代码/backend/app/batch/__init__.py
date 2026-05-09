"""Batch evaluation pipeline.

The hackathon evaluators run their grader by submitting many test cases
at once, expecting an xlsx of results back. This package exposes the
machinery for that flow:

  - `manifest`: parse a JSONL or CSV manifest into typed `BatchTask`s.
  - `runner`: fan tasks out into the same `handle_analyze` pipeline the
    public `/v1/analyze` route uses, capturing per-task results + errors.
  - `xlsx`: render a workbook (summary + evidence sheets) the evaluator
    can import directly into their grading tool.

The route layer (`app.api.batch`) is the thin glue: receive multipart
upload (manifest + data files) → save into a workspace → run → stream
back the xlsx.
"""

from app.batch.manifest import BatchTask, ManifestError, parse_manifest
from app.batch.runner import BatchResult, run_batch
from app.batch.xlsx import render_xlsx

__all__ = [
    "BatchResult",
    "BatchTask",
    "ManifestError",
    "parse_manifest",
    "render_xlsx",
    "run_batch",
]
