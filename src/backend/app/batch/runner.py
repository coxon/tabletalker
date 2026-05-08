"""Batch runner — fan tasks out to `handle_analyze`, capture results.

Concurrent dispatch with a configurable concurrency cap. Each task runs
through the same `handle_analyze` pipeline as `/v1/analyze`. An asyncio
semaphore gates the parallelism so we don't overload the LLM gateway.

Errors are captured per-task — a failure on row 4 must not abort rows
5..N. The output sheet shows status/error so the evaluator can see
which cases need re-running rather than getting nothing back.
"""

from __future__ import annotations

import asyncio
import logging
import os
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

_CONCURRENCY = int(os.environ.get("BATCH_CONCURRENCY", "4"))


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
    extra: dict[str, Any] = field(default_factory=dict)


async def _run_one(
    task: BatchTask,
    *,
    workspace: Path,
    chat_client: ChatClient,
    base_url: str | None,
    semaphore: asyncio.Semaphore,
) -> BatchResult:
    async with semaphore:
        started = time.perf_counter()
        # Follow-ups are explicitly out-of-scope for offline batch per
        # 赛题4 §4.2 ("追问题在标准分析题的报告生成完成后由评委即时发起").
        # We surface them as `status="skipped"` rather than dispatch them
        # as a fresh standard_analysis (which would silently lose the
        # parent context the follow-up depends on). The output bundle
        # documents the skip so the operator knows to handle these
        # interactively.
        if task.task_type == "follow_up":
            return BatchResult(
                task=task,
                response=None,
                status="skipped",
                error=(
                    "follow-up tasks are not run by the offline batch path; "
                    "they must be exercised against the live /v1/follow-up "
                    "endpoint while the parent session is still in memory "
                    "(see 赛题4 README §4.2)."
                ),
                elapsed_ms=0.0,
            )
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
            return BatchResult(
                task=task,
                response=response,
                status="ok",
                elapsed_ms=elapsed,
                extra={"id": response.id},
            )
        except AnalyzeFailure as exc:
            elapsed = (time.perf_counter() - started) * 1000
            logger.warning(
                "batch task %s failed: %s (status=%d)",
                task.id, exc, exc.status_code,
            )
            return BatchResult(
                task=task,
                response=None,
                status="error",
                error=f"{exc.status_code}: {exc}",
                elapsed_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            logger.exception("batch task %s crashed", task.id)
            error_label = (
                f"unexpected error ({type(exc).__name__}; see server logs)"
            )
            return BatchResult(
                task=task,
                response=None,
                status="error",
                error=error_label,
                elapsed_ms=elapsed,
            )


async def run_batch(
    tasks: list[BatchTask],
    *,
    workspace: Path,
    chat_client: ChatClient,
    base_url: str | None = None,
) -> list[BatchResult]:
    """Run tasks concurrently (up to BATCH_CONCURRENCY), return in input order."""

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    coros = [
        _run_one(
            task,
            workspace=workspace,
            chat_client=chat_client,
            base_url=base_url,
            semaphore=semaphore,
        )
        for task in tasks
    ]
    return list(await asyncio.gather(*coros))
