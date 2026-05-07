"""Batch runner — fan tasks out to `handle_analyze`, capture results.

Sequential dispatch by design: the LLM gateway is the bottleneck and we
don't want a single batch to swamp it. Each task runs against the same
shared workspace, so the route layer must save every referenced data
file there before calling us.

Errors are captured per-task — a failure on row 4 must not abort rows
5..N. The output sheet shows status/error so the evaluator can see
which cases need re-running rather than getting nothing back.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.analyze.handler import (
    AnalyzeFailure,
    AnalyzeRequest,
    AnalyzeResponse,
    handle_analyze,
)
from app.batch.manifest import BatchTask
from app.spreadsheet.llm import ChatClient

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """One task's outcome — the input that produced it, the response (or
    error), and the wall-clock time the run took.

    `response` is None on failure; `status` / `error` carry the diagnostic
    so the xlsx renderer can present a sensible row instead of crashing
    on a missing field.
    """

    task: BatchTask
    response: AnalyzeResponse | None = None
    status: str = "ok"   # ok | error
    error: str | None = None
    elapsed_ms: float = 0.0
    # `extra` lets the route stash the per-task `request_id` for log
    # correlation without baking it into the schema.
    extra: dict[str, Any] = field(default_factory=dict)


async def run_batch(
    tasks: list[BatchTask],
    *,
    workspace: Path,
    chat_client: ChatClient,
    base_url: str | None = None,
) -> list[BatchResult]:
    """Run every task sequentially, return results in input order.

    `workspace` already contains every file the manifest references —
    enforcement happens at the route layer where the uploads are saved.
    The runner just trusts the contract: if `task.file` isn't on disk,
    the underlying `handle_analyze` will raise `AnalyzeFailure(422)` and
    we record that in the result rather than aborting.
    """

    results: list[BatchResult] = []
    for task in tasks:
        started = time.perf_counter()
        try:
            request = AnalyzeRequest(
                workspace=workspace,
                filename=task.file,
                dataset=task.dataset or Path(task.file).stem,
                question=task.question,
                base_url=base_url,
                sampling_rate=task.sampling_rate,
                sampling_note=task.sampling_note,
                extra_filenames=task.extra_files,
            )
            response = await handle_analyze(request, chat_client=chat_client)
            elapsed = (time.perf_counter() - started) * 1000
            results.append(
                BatchResult(
                    task=task,
                    response=response,
                    status="ok",
                    elapsed_ms=elapsed,
                    extra={"id": response.id},
                )
            )
        except AnalyzeFailure as exc:
            elapsed = (time.perf_counter() - started) * 1000
            logger.warning(
                "batch task %s failed: %s (status=%d)",
                task.id, exc, exc.status_code,
            )
            results.append(
                BatchResult(
                    task=task,
                    response=None,
                    status="error",
                    error=f"{exc.status_code}: {exc}",
                    elapsed_ms=elapsed,
                )
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            # Keep only the exception class name in the user-visible row
            # — `repr(exc)` can spill temp paths, LLM URLs, or config
            # values that shouldn't ride out in the xlsx a grader gets
            # handed. Full traceback / message stays in the server log
            # via `logger.exception` below for ops triage.
            logger.exception("batch task %s crashed", task.id)
            error_label = (
                f"unexpected error ({type(exc).__name__}; see server logs)"
            )
            results.append(
                BatchResult(
                    task=task,
                    response=None,
                    status="error",
                    error=error_label,
                    elapsed_ms=elapsed,
                )
            )
    return results
