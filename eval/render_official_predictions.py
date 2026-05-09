"""§5.2 offline-fallback CLI: read official Public_Analysis_Requirements.jsonl,
fan out through the same `handle_analyze` entry point the HTTP route uses,
write `predictions.jsonl + reports/{id}.html` to a target directory.

The intended scenario, per 赛题4 README §5.2, is "评委侧网络异常" — the
operator gets the requirements file from the grader, can't expose the
HTTP endpoint to them, runs this tool locally instead, and ships back
the resulting bundle.

Usage:
    python eval/render_official_predictions.py \\
        --requirements path/to/Public_Analysis_Requirements.jsonl \\
        --data-dir path/to/datasets/ \\
        --out path/to/predictions/

Inputs:
    --requirements  jsonl per §4.1 / §4.2 — one task per line.
    --data-dir      directory containing the data files referenced by
                    each task. Each task is expected to declare a
                    `file` (and optional `extra_files`) basename, OR
                    rely on the `dataset` fallback (filename = dataset
                    label). The matching logic is the same as the
                    `/v1/batch` route.
    --out           output directory; gets `predictions.jsonl`,
                    `reports/{id}.html`, and `MANIFEST.txt`.

Outputs:
    {out}/predictions.jsonl   one line per task (AnalyzeResponse JSON)
    {out}/reports/{id}.html   one HTML per task that produced a report
    {out}/MANIFEST.txt        plain-text summary

Reads `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` from the
environment via the same `LLMConfig.from_env()` the HTTP path uses;
copy `.env.example` to `.env` first or export them directly.

Concurrency: defaults to `BATCH_CONCURRENCY` from env (default 4) just
like the HTTP route. Each task gets its own subprocess of work; the
LLM gateway is the bottleneck so 4 typically saturates it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_SRC = REPO_ROOT / "src" / "backend"
sys.path.insert(0, str(BACKEND_SRC))

# Load .env from the repo root before any LLMConfig.from_env() call.
# The HTTP backend does this via app.main; the CLI is its own entry
# point and has to opt in explicitly. Silently no-ops when .env is
# absent so CI / docker-style env-var-only setups still work.
try:
    from dotenv import load_dotenv  # noqa: E402

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    # python-dotenv is a backend dep; if the CLI is run outside the
    # backend venv, fall back to whatever the shell exported.
    pass

# These imports require BACKEND_SRC on path — must come after the sys.path edit.
from app.batch import parse_manifest, run_batch  # noqa: E402
from app.batch.official_output import render_official_bundle  # noqa: E402
from app.spreadsheet.llm import HttpChatClient, LLMConfig, LLMConfigError  # noqa: E402


def _ensure_workspace(
    requirements_path: Path, data_dir: Path
) -> tuple[Path, list[str]]:
    """Build a workspace directory that contains every file each task
    references, copying from `data_dir` so the runner sees a flat layout.

    Returns `(workspace_path, missing_files)`. The workspace is a fresh
    tempdir we own; the caller is responsible for `shutil.rmtree` on
    completion (we hand a real path, not an mkdtemp context manager,
    so the CLI can keep it on a debug failure).

    `missing_files` is the union of file basenames referenced by tasks
    that don't exist under `data_dir`. The caller decides whether to
    abort (we recommend yes).
    """

    raw = requirements_path.read_bytes()
    tasks = parse_manifest(raw, requirements_path.name)
    referenced: set[str] = set()
    for t in tasks:
        referenced.add(t.file)
        referenced.update(t.extra_files)

    workspace = Path(tempfile.mkdtemp(prefix="tabletalker-cli-"))
    missing: list[str] = []
    for name in sorted(referenced):
        src = data_dir / name
        if not src.exists():
            missing.append(name)
            continue
        shutil.copy2(src, workspace / name)
    return workspace, missing


async def _run(args: argparse.Namespace) -> int:
    requirements: Path = args.requirements
    data_dir: Path = args.data_dir
    out_dir: Path = args.out

    if not requirements.is_file():
        print(f"requirements file not found: {requirements}", file=sys.stderr)
        return 2
    if not data_dir.is_dir():
        print(f"data dir not found: {data_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = LLMConfig.from_env()
    except LLMConfigError as exc:
        print(f"LLM not configured: {exc}", file=sys.stderr)
        print(
            "Hint: copy .env.example to .env, fill LLM_BASE_URL / LLM_API_KEY / LLM_MODEL.",
            file=sys.stderr,
        )
        return 3
    chat_client = HttpChatClient(config)

    workspace, missing = _ensure_workspace(requirements, data_dir)
    try:
        if missing:
            print(
                f"warning: {len(missing)} referenced file(s) missing from data dir; "
                f"those tasks will fail. Missing: {missing[:10]}{'...' if len(missing) > 10 else ''}",
                file=sys.stderr,
            )

        tasks = parse_manifest(requirements.read_bytes(), requirements.name)
        print(f"→ tasks: {len(tasks)}", file=sys.stderr)

        results = await run_batch(
            tasks,
            workspace=workspace,
            chat_client=chat_client,
            base_url=None,  # CLI: report URLs render with relative paths
        )

        # Write the bundle directly into the out dir rather than as a
        # zip — the operator already has filesystem access (otherwise
        # they'd be using the HTTP endpoint), and an unzipped layout
        # is friendlier to grep / diff than peeking inside an archive.
        zip_bytes = render_official_bundle(results, archive_name=out_dir.name)

        # We get back a zip with `{out_dir.name}/...` prefix — extract
        # the inner files into out_dir/ to land at the documented paths.
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for member in zf.namelist():
                # Strip the archive_name/ prefix before writing.
                relative = member.split("/", 1)[1] if "/" in member else member
                if not relative:
                    continue  # the directory entry itself
                target = out_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.endswith("/"):
                    target.mkdir(exist_ok=True)
                    continue
                with zf.open(member) as src, target.open("wb") as dst:
                    dst.write(src.read())

        ok = sum(1 for r in results if r.status == "ok")
        err = sum(1 for r in results if r.status == "error")
        skipped = sum(1 for r in results if r.status == "skipped")
        print(
            f"\n→ done: {ok} ok / {err} error / {skipped} skipped (out: {out_dir})",
            file=sys.stderr,
        )
        # Always return 0 on a complete run (per-task failures are
        # documented in predictions.jsonl); only return non-zero on
        # infrastructure failure that aborted the whole run.
        return 0
    finally:
        # Keep the workspace on hard failure so the operator can
        # inspect the staged uploads; remove on a clean run to avoid
        # /tmp clutter.
        shutil.rmtree(workspace, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements",
        type=Path,
        required=True,
        help="Path to Public_Analysis_Requirements.jsonl (one task per line).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Directory holding data files referenced by tasks.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory; predictions.jsonl + reports/ land here.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
