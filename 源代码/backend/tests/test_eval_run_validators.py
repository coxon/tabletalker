"""Locks in PR #17 round-7 CodeRabbit fixes on `eval/run.py`.

Two pieces of hardening that don't have anywhere else to live:
  1. `_load_and_validate_cases` rejects malformed `cases.yaml` (not a
     list, items not mappings, missing required keys) at startup
     instead of dying mid-run with `KeyError`.
  2. `_resolve_dataset_path` rejects path-traversal in `case["id"]`
     (``../etc/passwd``, ``/abs``, separators, ``..``) and confirms the
     resolved CSV path is inside `data_dir/`.

`eval/` is not a package — we vendor the import via the same `sys.path`
trick used by `test_eval_render_official.py`.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.run import (  # type: ignore[import-not-found]  # noqa: E402
    _load_and_validate_cases,
    _post_analyze,
    _resolve_dataset_path,
    compute_metrics,
)

# ---------------------------------------------------------------------------
# _load_and_validate_cases
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, payload: object) -> Path:
    p = tmp_path / "cases.yaml"
    p.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return p


def test_load_validate_accepts_well_formed_cases(tmp_path: Path) -> None:
    cases = [
        {"id": "01_demo", "question": "Q1?"},
        {
            "id": "02_demo",
            "question": "Q2?",
            "primary_file": "02_demo.xlsx",
            "followup": "Tell me more.",
            "trap": {"expected_refusal": True, "question": "by race?"},
        },
    ]
    out = _load_and_validate_cases(_write_yaml(tmp_path, cases))
    assert out == cases


# ---------------------------------------------------------------------------
# Optional-key shape validation (PR #17 round-9)
# ---------------------------------------------------------------------------


def test_load_validate_rejects_non_string_followup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.followup must be a string"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [{"id": "x", "question": "q?", "followup": ["not", "a", "string"]}],
            )
        )


def test_load_validate_rejects_non_mapping_trap(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.trap must be a mapping"):
        _load_and_validate_cases(
            _write_yaml(tmp_path, [{"id": "x", "question": "q?", "trap": "yes"}])
        )


def test_load_validate_rejects_trap_missing_expected_refusal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'expected_refusal'"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [{"id": "x", "question": "q?", "trap": {"question": "q?"}}],
            )
        )


def test_load_validate_rejects_trap_missing_question(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'question'"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [{"id": "x", "question": "q?", "trap": {"expected_refusal": True}}],
            )
        )


# ---------------------------------------------------------------------------
# Required-field type validation (PR #17 round-10)
# ---------------------------------------------------------------------------


def test_load_validate_rejects_non_string_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.id must be a string"):
        _load_and_validate_cases(_write_yaml(tmp_path, [{"id": 123, "question": "q?"}]))


def test_load_validate_rejects_non_string_question(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.question must be a string"):
        _load_and_validate_cases(
            _write_yaml(tmp_path, [{"id": "x", "question": ["a", "b"]}])
        )


def test_load_validate_rejects_non_string_trap_question(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.trap\.question must be a string"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [
                    {
                        "id": "x",
                        "question": "q?",
                        "trap": {"expected_refusal": True, "question": 42},
                    }
                ],
            )
        )


def test_load_validate_rejects_non_bool_expected_refusal(tmp_path: Path) -> None:
    """`bool` is a subclass of `int`, so YAML `expected_refusal: 1` would
    pass an `isinstance(_, (bool, int))` check and silently score as
    `True`. Reject anything that isn't *exactly* a bool.

    Use integer `1` here specifically so the test exercises the
    `bool`-is-`int` edge — a string like `"true"` would also be rejected
    by a weaker check and wouldn't lock in the stricter contract.
    """
    with pytest.raises(ValueError, match=r"\.expected_refusal must be a boolean"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [
                    {
                        "id": "x",
                        "question": "q?",
                        "trap": {"expected_refusal": 1, "question": "q?"},
                    }
                ],
            )
        )


def test_load_validate_rejects_path_traversal_id(tmp_path: Path) -> None:
    """Round-11: hoist `_CASE_ID_PATTERN` up to manifest validation so
    malformed ids fail fast rather than the first time `_resolve_dataset_path`
    tries to compose `data_dir / f"{case_id}.csv"`. The lookup keeps the
    same check as a defensive double-layer.
    """
    with pytest.raises(ValueError, match=r"\.id must match"):
        _load_and_validate_cases(
            _write_yaml(tmp_path, [{"id": "../etc", "question": "q?"}])
        )


def test_load_validate_rejects_dotted_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.id must match"):
        _load_and_validate_cases(
            _write_yaml(tmp_path, [{"id": "foo.bar", "question": "q?"}])
        )


def test_load_validate_rejects_top_level_mapping(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be a YAML list"):
        _load_and_validate_cases(_write_yaml(tmp_path, {"not": "a list"}))


def test_load_validate_rejects_non_mapping_item(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\[1\] must be a mapping"):
        _load_and_validate_cases(
            _write_yaml(tmp_path, [{"id": "ok", "question": "q?"}, "stringly-typed"])
        )


def test_load_validate_rejects_missing_required_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"missing required key\(s\): \['question'\]"):
        _load_and_validate_cases(_write_yaml(tmp_path, [{"id": "x"}]))


# ---------------------------------------------------------------------------
# _resolve_dataset_path
# ---------------------------------------------------------------------------


def test_resolve_dataset_path_happy() -> None:
    with tempfile.TemporaryDirectory() as d:
        data_dir = Path(d)
        out = _resolve_dataset_path("01_demo", data_dir)
        assert out == (data_dir / "01_demo.csv").resolve()


def test_resolve_dataset_path_honors_primary_file() -> None:
    with tempfile.TemporaryDirectory() as d:
        data_dir = Path(d)
        out = _resolve_dataset_path("01_demo", data_dir, "01_demo.xlsx")
        assert out == (data_dir / "01_demo.xlsx").resolve()


def test_load_validate_rejects_primary_file_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="primary_file must be a basename"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [
                    {
                        "id": "01_demo",
                        "question": "Q?",
                        "primary_file": "../01_demo.xlsx",
                    }
                ],
            )
        )


@pytest.mark.parametrize(
    "bad_id",
    [
        "../etc/passwd",
        "/etc/passwd",
        "foo/bar",
        "foo\\bar",
        "..",
        "foo bar",   # whitespace
        "foo.bar",   # dot — would let the .csv suffix concat span dirs
        "",
        "中文",       # non-ASCII
    ],
)
def test_resolve_dataset_path_rejects_traversal(bad_id: str) -> None:
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError, match="case id must match"):
            _resolve_dataset_path(bad_id, Path(d))


def test_resolve_dataset_path_rejects_non_string() -> None:
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError, match="case id must match"):
            _resolve_dataset_path(123, Path(d))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Round-12: sampling_rate + duplicate-id (PR #17)
# ---------------------------------------------------------------------------


def test_load_validate_accepts_sampling_rate(tmp_path: Path) -> None:
    cases = [
        {
            "id": "01_demo",
            "question": "Q?",
            "sampling_rate": 0.25,
        }
    ]
    out = _load_and_validate_cases(_write_yaml(tmp_path, cases))
    assert out[0]["sampling_rate"] == 0.25


def test_load_validate_rejects_non_numeric_sampling_rate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.sampling_rate must be a number"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [{"id": "x", "question": "q?", "sampling_rate": "0.25"}],
            )
        )


def test_load_validate_rejects_bool_sampling_rate(tmp_path: Path) -> None:
    """bool subclass-of-int sneak — `sampling_rate: true` would coerce
    to 1.0 (full sample) under a naive `(int, float)` check."""
    with pytest.raises(ValueError, match=r"\.sampling_rate must be a number"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [{"id": "x", "question": "q?", "sampling_rate": True}],
            )
        )


def test_load_validate_rejects_out_of_range_sampling_rate(tmp_path: Path) -> None:
    for bad in (0, -0.1, 1.5, float("inf")):
        with pytest.raises(ValueError, match=r"\.sampling_rate must be in \(0, 1\]"):
            _load_and_validate_cases(
                _write_yaml(
                    tmp_path,
                    [{"id": "x", "question": "q?", "sampling_rate": bad}],
                )
            )


def test_load_validate_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"duplicates case id 'demo'"):
        _load_and_validate_cases(
            _write_yaml(
                tmp_path,
                [
                    {"id": "demo", "question": "Q1?"},
                    {"id": "demo", "question": "Q2?"},
                ],
            )
        )


# ---------------------------------------------------------------------------
# compute_metrics: refusal metric naming (round-14)
# ---------------------------------------------------------------------------


def _trap_case(
    *, case_id: str, trap_status: int, trap_is_refusal: bool, expected_refusal: bool
) -> object:
    """Build a minimal CaseResult with only the fields compute_metrics reads."""
    from eval.run import CaseResult, TurnResult  # type: ignore[import-not-found]

    main = TurnResult(label="main", status_code=200, latency_s=0.1, body={})
    trap = TurnResult(
        label="trap",
        status_code=trap_status,
        latency_s=0.1,
        body={"is_refusal": trap_is_refusal} if trap_status == 200 else None,
    )
    return CaseResult(
        case_id=case_id,
        main=main,
        trap=trap,
        trap_expected_refusal=expected_refusal,
    )


def test_compute_metrics_emits_refusal_correct_accuracy_and_alias() -> None:
    """Round-14 (CodeRabbit #17): the lenient rate must be emitted under
    BOTH `refusal_correct_accuracy` (preferred, matches
    `refusal_correct_count`) AND `refusal_accuracy_on_traps` (legacy
    alias). Back-compat in the key dict — a downstream reader that
    pinned either name keeps working.
    """
    # One correct 200 refusal trap.
    results = [
        _trap_case(
            case_id="t1",
            trap_status=200,
            trap_is_refusal=True,
            expected_refusal=True,
        ),
    ]
    metrics = compute_metrics(results)
    # Preferred key present.
    assert "refusal_correct_accuracy" in metrics
    # Legacy alias still present.
    assert "refusal_accuracy_on_traps" in metrics
    # Same value under both names — the two keys must not diverge.
    assert metrics["refusal_correct_accuracy"] == metrics["refusal_accuracy_on_traps"]
    # Both are 1.0 for a 1/1 trap case.
    assert metrics["refusal_correct_accuracy"] == 1.0


def test_compute_metrics_uses_recorded_upload_filenames_for_capabilities() -> None:
    from eval.run import CaseResult, TurnResult  # type: ignore[import-not-found]

    main = TurnResult(label="main", status_code=200, latency_s=0.1, body={})
    metrics = compute_metrics(
        [
            CaseResult(
                case_id="excel_smoke",
                main=main,
                primary_file="excel_smoke.xlsx",
            ),
            CaseResult(
                case_id="multi_file",
                main=main,
                primary_file="movies.csv",
                extra_file_count=1,
                extra_files=["credits.csv"],
            ),
        ]
    )

    assert metrics["excel_capable"] is True
    assert metrics["multi_file_capable"] is True


# ---------------------------------------------------------------------------
# _post_analyze: sampling_rate must be forwarded to /v1/analyze
# (CR #17 round-15 Major)
# ---------------------------------------------------------------------------


class _RecordingClient:
    """Minimal `httpx.AsyncClient` stand-in that captures the POST body.

    We only need to verify that `data["sampling_rate"]` reaches the wire;
    standing up the full httpx mock surface would dwarf the fix itself.
    """

    def __init__(self) -> None:
        self.last_data: dict[str, str] | None = None
        self.last_files: dict | None = None

    async def post(self, url: str, *, files=None, data=None):  # type: ignore[no-untyped-def]
        self.last_data = dict(data) if data else {}
        self.last_files = files
        # Mimic the bits of `httpx.Response` _post_analyze touches.
        class _Resp:
            status_code = 200
            text = '{"id": "eval_x", "is_refusal": false}'
            # ClassVar so ruff (RUF012) doesn't flag the empty dict as a
            # mutable default — `_parse_stage_timings()` reads
            # `response.headers` and we want it to be a no-op.
            headers: ClassVar[dict[str, str]] = {}

            def json(self):
                import json

                return json.loads(self.text)

        return _Resp()


@pytest.mark.asyncio
async def test_post_analyze_forwards_sampling_rate(tmp_path: Path) -> None:
    """The Major fix: when the case manifest declares `sampling_rate`,
    the eval harness must forward it as a form field on `/v1/analyze`.

    Without this guard the manifest's sampling_rate landed on the local
    `CaseResult` only — the backend never saw it, so every Evidence row
    was stamped with `sampling_rate=None` and the auto-grader judged the
    sampled run against full-population row-count expectations. The
    04_telecom_churn case (5k rows of a 100k source) would silently fail
    every Evidence check on the second run.
    """
    csv = tmp_path / "demo.csv"
    csv.write_text("region,amount\nA,1\n", encoding="utf-8")
    client = _RecordingClient()

    await _post_analyze(client, csv, "Q?", sampling_rate=0.25)
    assert client.last_data is not None
    assert client.last_data.get("sampling_rate") == "0.25", (
        f"sampling_rate must be forwarded as a string form field; "
        f"got {client.last_data!r}"
    )
    # And the question is still there alongside it (regression: a
    # buggy refactor that overrode `data` with the sampling block
    # would silently drop the question).
    assert client.last_data.get("question") == "Q?"


@pytest.mark.asyncio
async def test_post_analyze_omits_sampling_rate_when_none(tmp_path: Path) -> None:
    """Default path (no manifest declaration): the form must NOT carry
    a `sampling_rate` key at all — submitting an empty / "None" string
    would 400 at the backend (sampling_rate is parsed as a float).
    """
    csv = tmp_path / "demo.csv"
    csv.write_text("region,amount\nA,1\n", encoding="utf-8")
    client = _RecordingClient()

    await _post_analyze(client, csv, "Q?")
    assert client.last_data is not None
    assert "sampling_rate" not in client.last_data, (
        f"unsampled cases must not send a sampling_rate key; "
        f"got {client.last_data!r}"
    )
