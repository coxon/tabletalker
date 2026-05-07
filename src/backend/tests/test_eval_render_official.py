"""Contract tests for `eval/render_official_metrics.py`.

These lock in the round-3 CodeRabbit fix on PR #17: the §2 grid scores
multi-file & Excel from measured signal (not hardcoded True), §5 errors
and §7 hallucination rows do not piggy-back on `main_success_rate` /
`refusal_accuracy_on_traps`, and §9's conclusion paragraph reflects the
computed score rather than a static "全覆盖" claim.

The renderer lives in `eval/`, which is not a package — we vendor the
import via `sys.path` like the eval CLI does.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.render_official_metrics import (  # type: ignore[import-not-found]  # noqa: E402
    CAP_DATA_INGEST,
    HALLUCINATION_THRESHOLD,
    PASS_THRESHOLD,
    _section_data_ingest,
    _section_interact,
    _section_root_cause,
    _section_statistics,
    _section_trend,
    render,
)

# ---------------------------------------------------------------------------
# §2 data-ingest: multi-file & Excel must be measured, not hardcoded True
# ---------------------------------------------------------------------------


def _csv_only_case() -> dict:
    """A baseline 200 case with no extras / Excel signal."""
    return {
        "case_id": "01",
        "main": {
            "label": "analyze",
            "status_code": 200,
            "body": {"findings": []},
        },
    }


def test_data_ingest_marks_multi_file_no_when_unmeasured() -> None:
    """Eval suite without an `extra_files` request must not score 是.

    Round-2 hardcoded `multi_file_capable = True`; this would let the
    renderer claim 5 free points for a capability the eval pass did not
    exercise — a violation of the file's honesty rule (header §1).
    """
    sec = _section_data_ingest({"main_success_rate": 1.0}, [_csv_only_case()])
    by_label = dict(sec.rows)
    assert by_label["是否支持多个文件上传"] == "否"
    assert by_label["是否支持 Excel 格式"] == "否"
    # -5 each from CAP_DATA_INGEST(20) for multi & Excel — single CSV
    # path only earns 10/20 instead of the original false 20/20.
    assert sec.score == CAP_DATA_INGEST - 10
    assert any("多文件" in d for d in sec.deductions)
    assert any("Excel" in d for d in sec.deductions)


def test_data_ingest_honors_explicit_metrics_flag() -> None:
    """A future eval that publishes `multi_file_capable=True` flips the row."""
    metrics = {
        "main_success_rate": 1.0,
        "multi_file_capable": True,
        "excel_capable": True,
    }
    sec = _section_data_ingest(metrics, [_csv_only_case()])
    by_label = dict(sec.rows)
    assert by_label["是否支持多个文件上传"] == "是"
    assert by_label["是否支持 Excel 格式"] == "是"
    assert sec.score == CAP_DATA_INGEST


def test_data_ingest_honors_request_shape_for_multi_file() -> None:
    """A case whose recorded request shipped `extra_files` flips multi-file."""
    case = _csv_only_case()
    case["main"]["request"] = {"extra_files": ["sales_q2.csv"]}
    sec = _section_data_ingest({"main_success_rate": 1.0}, [case])
    by_label = dict(sec.rows)
    assert by_label["是否支持多个文件上传"] == "是"


def test_data_ingest_honors_request_shape_for_excel() -> None:
    """A case whose recorded request uploaded `.xlsx` flips Excel."""
    case = _csv_only_case()
    case["main"]["request"] = {"filenames": ["q3_attrition.xlsx"]}
    sec = _section_data_ingest({"main_success_rate": 1.0}, [case])
    by_label = dict(sec.rows)
    assert by_label["是否支持 Excel 格式"] == "是"


def test_data_ingest_ignores_failed_multi_file_attempt() -> None:
    """Round-4: a non-200 case that *attempted* multi-file upload doesn't
    prove the path works; it just proves we ran it. The row must stay 否.
    """
    case = _csv_only_case()
    case["main"]["status_code"] = 422
    case["main"]["request"] = {"extra_files": ["sales_q2.csv"]}
    sec = _section_data_ingest({"main_success_rate": 1.0}, [case])
    by_label = dict(sec.rows)
    assert by_label["是否支持多个文件上传"] == "否"


def test_data_ingest_ignores_failed_excel_attempt() -> None:
    """Round-4 symmetric: a 500 on an .xlsx upload doesn't prove Excel works."""
    case = _csv_only_case()
    case["main"]["status_code"] = 500
    case["main"]["request"] = {"filenames": ["q3_attrition.xlsx"]}
    sec = _section_data_ingest({"main_success_rate": 1.0}, [case])
    by_label = dict(sec.rows)
    assert by_label["是否支持 Excel 格式"] == "否"


# ---------------------------------------------------------------------------
# §5 statistics: has_errors must NOT come from main_success_rate
# ---------------------------------------------------------------------------


def test_statistics_does_not_treat_main_failure_as_stat_error() -> None:
    """A 422 on a main turn is a request failure, not a wrong statistic.

    Round-2: `has_errors = main_success_rate < PASS_THRESHOLD` would
    deduct §5 for a flaky upload. Round-3: only flag when the metrics
    block carries an explicit stat-error signal.
    """
    metrics = {
        "evidence_completeness": 1.0,
        # Below threshold — would have flagged "是" pre-round-3.
        "main_success_rate": 0.5,
        # No explicit stat-error metrics → row stays 否.
    }
    sec = _section_statistics(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在明显统计错误"] == "否"
    assert not any("统计错误" in d for d in sec.deductions)


def test_statistics_flags_explicit_stat_error_count() -> None:
    metrics = {
        "evidence_completeness": 1.0,
        "main_success_rate": 1.0,
        "statistical_error_count": 2,
    }
    sec = _section_statistics(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在明显统计错误"] == "是"
    assert any("统计错误" in d for d in sec.deductions)


def test_statistics_flags_explicit_stat_error_samples() -> None:
    metrics = {
        "evidence_completeness": 1.0,
        "main_success_rate": 1.0,
        "stat_error_samples": [{"case": "07", "expected": 5, "got": 7}],
    }
    sec = _section_statistics(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在明显统计错误"] == "是"


# ---------------------------------------------------------------------------
# §7 root-cause: has_hallucination must NOT come from refusal accuracy
# ---------------------------------------------------------------------------


def test_root_cause_does_not_treat_low_refusal_accuracy_as_hallucination() -> None:
    """Refusal on out-of-scope traps is orthogonal to in-scope hallucination."""
    metrics = {
        "evidence_completeness": 1.0,
        # Round-2 path: would have flipped this row to 是 with a -6
        # deduction. Round-3: refusal_accuracy is no longer a signal here.
        "refusal_accuracy_on_traps": 0.0,
    }
    sec = _section_root_cause(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在逻辑错误或幻觉"] == "否"
    assert not any("幻觉" in d for d in sec.deductions)


def test_root_cause_flags_explicit_hallucination_rate() -> None:
    metrics = {
        "evidence_completeness": 1.0,
        "hallucination_rate": HALLUCINATION_THRESHOLD + 0.01,
    }
    sec = _section_root_cause(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在逻辑错误或幻觉"] == "是"
    assert any("幻觉" in d or "逻辑" in d for d in sec.deductions)


def test_root_cause_does_not_flag_below_threshold_hallucination_rate() -> None:
    metrics = {
        "evidence_completeness": 1.0,
        # Just below the trip-wire — must not flag.
        "hallucination_rate": HALLUCINATION_THRESHOLD - 0.001,
    }
    sec = _section_root_cause(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在逻辑错误或幻觉"] == "否"


# ---------------------------------------------------------------------------
# §9 conclusion: must reflect computed scores, not be a static claim
# ---------------------------------------------------------------------------


def test_conclusion_lists_gaps_when_data_ingest_incomplete(tmp_path: Path) -> None:
    """When §2 has 否 rows the §9 paragraph must surface them by name.

    Round-2 always rendered "覆盖完整 …" regardless of the table above
    it, producing an internally inconsistent report.
    """
    summary = {
        "started_at": "2026-05-07T01:00:00Z",
        "completed_at": "2026-05-07T01:30:00Z",
        "metrics": {
            "datasets_total": 5,
            "main_success_rate": 1.0,
            "followup_success_rate": 1.0,
            "session_carry_rate": 1.0,
            "refusal_accuracy_on_traps": 1.0,
            "evidence_completeness": 1.0,
            "distinct_chart_types": 3,
            "avg_summary_len_chars": 500,
            # multi_file_capable / excel_capable absent → §2 rows = 否
        },
        "cases": [
            {"case_id": "01", "main": {"status_code": 200, "body": {"findings": []}}},
        ],
    }
    run_dir = tmp_path / "fake-run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        __import__("json").dumps(summary), encoding="utf-8"
    )
    rendered = render(run_dir)
    # Conclusion paragraph must NOT claim "覆盖完整" when §2 has gaps.
    conclusion = rendered.split("## 9. 结论", 1)[1]
    assert "覆盖完整" not in conclusion
    # The specific gap labels from §2 must appear in the paragraph
    # (so the reader can trace the statement back to the table).
    assert "多个文件上传" in conclusion
    assert "Excel" in conclusion
    # Score totals must appear in the conclusion (audit trail back to §1).
    assert "/ 100" in conclusion or "/100" in conclusion


def test_conclusion_keeps_positive_wording_when_no_gaps(tmp_path: Path) -> None:
    """Symmetric: a fully-covered run keeps the original sentence."""
    summary = {
        "started_at": "2026-05-07T01:00:00Z",
        "completed_at": "2026-05-07T01:30:00Z",
        "metrics": {
            "datasets_total": 5,
            "main_success_rate": 1.0,
            "followup_success_rate": 1.0,
            "session_carry_rate": 1.0,
            "refusal_accuracy_on_traps": 1.0,
            "evidence_completeness": 1.0,
            "distinct_chart_types": 3,
            "avg_summary_len_chars": 500,
            "multi_file_capable": True,
            "excel_capable": True,
        },
        "cases": [
            {"case_id": "01", "main": {"status_code": 200, "body": {"findings": []}}},
        ],
    }
    run_dir = tmp_path / "fake-run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        __import__("json").dumps(summary), encoding="utf-8"
    )
    rendered = render(run_dir)
    conclusion = rendered.split("## 9. 结论", 1)[1]
    assert "覆盖完整" in conclusion


# ---------------------------------------------------------------------------
# Sanity: PASS_THRESHOLD vs HALLUCINATION_THRESHOLD must stay distinct
# ---------------------------------------------------------------------------


def test_thresholds_are_separate_constants() -> None:
    """Round-3 split: hallucination uses its own trip-wire."""
    assert HALLUCINATION_THRESHOLD != PASS_THRESHOLD
    assert 0.0 < HALLUCINATION_THRESHOLD < 1.0


# ---------------------------------------------------------------------------
# Round-4: section notes must reflect the same booleans that drive the rows
# ---------------------------------------------------------------------------


def test_interact_note_does_not_claim_compliance_when_refuse_fails() -> None:
    """Round-2 always tailed with "符合「数据不支持时显式说明原因」的要求"
    even when refuse_ok was False — directly contradicting the table row.
    Round-4 (CodeRabbit #17): branch the closing clause on refuse_ok.
    """
    metrics = {
        "main_success_rate": 1.0,
        "followup_success_rate": 1.0,
        "session_carry_rate": 1.0,
        "refusal_accuracy_on_traps": 0.4,  # below PASS_THRESHOLD
    }
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    assert by_label["是否能够对数据不支持的问题说明原因"] == "否"
    # The note must NOT claim compliance.
    assert "符合" not in sec.note
    # And it must mark the gap visibly.
    assert "未达" in sec.note or "扣分点" in sec.note


def test_interact_note_keeps_compliance_when_refuse_passes() -> None:
    """Symmetric: a fully-passing run keeps the original positive sentence."""
    metrics = {
        "main_success_rate": 1.0,
        "followup_success_rate": 1.0,
        "session_carry_rate": 1.0,
        "refusal_accuracy_on_traps": 1.0,
    }
    sec = _section_interact(metrics)
    assert "符合" in sec.note


def test_statistics_note_does_not_claim_consistency_when_errors_present() -> None:
    """Round-2's "保持一致" tail contradicted has_errors=True."""
    metrics = {
        "evidence_completeness": 1.0,
        "statistical_error_count": 3,
    }
    sec = _section_statistics(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在明显统计错误"] == "是"
    assert "保持一致" not in sec.note
    assert "存在统计错误" in sec.note or "扣分点" in sec.note


def test_statistics_note_keeps_consistency_when_no_errors() -> None:
    metrics = {
        "evidence_completeness": 1.0,
    }
    sec = _section_statistics(metrics, [])
    assert "保持一致" in sec.note


def test_trend_note_does_not_claim_dimension_when_absent() -> None:
    """Round-2's "结合分类维度" was hardcoded; if has_dimension=False
    the note now says "未观测到跨维度对比" instead.
    """
    # Empty cases → no findings → has_dimension = False
    metrics = {
        "distinct_chart_types": 1,
        "evidence_completeness": 1.0,
        "avg_summary_len_chars": 500,
    }
    sec = _section_trend(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否结合时间、类别或其他可比较维度分析变化"] == "否"
    assert "结合分类维度" not in sec.note
    assert "未观测到" in sec.note


def test_trend_note_drops_shallow_clause_when_summary_long() -> None:
    """Round-2 always appended "解释深度仍偏概括"; if avg_len ≥ 400 the
    sufficiency row is "否" and the clause must not appear.
    """
    case = {
        "case_id": "01",
        "main": {
            "status_code": 200,
            "body": {
                "findings": [
                    {
                        "evidence": [
                            {"row_count": 1, "value": 1, "filters": "a"},
                            {"row_count": 1, "value": 2, "filters": "b"},
                            {"row_count": 1, "value": 3, "filters": "c"},
                        ]
                    }
                ]
            },
        },
    }
    metrics = {
        "distinct_chart_types": 3,
        "evidence_completeness": 1.0,
        "avg_summary_len_chars": 800,  # ≥ 400 → sufficiency_partial = False
    }
    sec = _section_trend(metrics, [case])
    assert "解释深度仍偏概括" not in sec.note


def test_root_cause_note_does_not_claim_single_finding_when_closure_full() -> None:
    """Round-2 always tailed with "受限于单 finding 闭环占比偏高" even
    when avg_findings ≥ 1.5. Round-4: branch on closure_full.
    """
    cases = [
        {
            "case_id": str(i),
            "main": {
                "status_code": 200,
                "body": {
                    "findings": [{"evidence": []}] * 2,  # 2 findings per case
                    "recommendations": ["x"],
                },
            },
        }
        for i in range(3)
    ]
    metrics = {"evidence_completeness": 1.0}
    sec = _section_root_cause(metrics, cases)
    by_label = dict(sec.rows)
    assert by_label["是否形成完整分析闭环"] == "完整形成"
    assert "单 finding" not in sec.note
    assert "完整" in sec.note


def test_root_cause_note_surfaces_hallucination_when_flagged() -> None:
    metrics = {
        "evidence_completeness": 1.0,
        "hallucination_rate": HALLUCINATION_THRESHOLD + 0.01,
    }
    sec = _section_root_cause(metrics, [])
    by_label = dict(sec.rows)
    assert by_label["是否存在逻辑错误或幻觉"] == "是"
    assert "幻觉" in sec.note or "扣分点" in sec.note


# ---------------------------------------------------------------------------
# Round-5: refuse_ok prefers strict signal; filters set tolerates dicts/lists
# ---------------------------------------------------------------------------


def test_interact_prefers_strict_refusal_signal_over_lenient() -> None:
    """CodeRabbit #17 round-5: the row "对数据不支持的问题说明原因"
    should reflect the canonical (strict) refusal envelope, not the
    lenient signal that counts a 4xx as "effective refusal" (an HTTP
    error code is not an explanation).

    Round-4 only checked `refusal_accuracy_on_traps` (lenient). With a
    100% lenient + 0% strict run, the row used to flip 是 — round-5
    inverts it.
    """
    metrics = {
        "main_success_rate": 1.0,
        "followup_success_rate": 1.0,
        "session_carry_rate": 1.0,
        "refusal_accuracy_on_traps": 1.0,  # lenient pass
        "refusal_strict_accuracy": 0.0,    # strict fails
    }
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    assert by_label["是否能够对数据不支持的问题说明原因"] == "否"


def test_interact_falls_back_to_lenient_when_strict_absent() -> None:
    """Old summary.json files (pre-`refusal_strict_accuracy`) must
    still render — fall back to the lenient key so historical runs
    don't suddenly score 0 on this row.
    """
    metrics = {
        "main_success_rate": 1.0,
        "followup_success_rate": 1.0,
        "session_carry_rate": 1.0,
        "refusal_accuracy_on_traps": 1.0,
        # refusal_strict_accuracy intentionally absent
    }
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    assert by_label["是否能够对数据不支持的问题说明原因"] == "是"


def test_root_cause_factor_set_tolerates_non_string_filters() -> None:
    """`ev.get("filters")` may be a dict / list for structured filter
    specs — `set()` would raise `TypeError: unhashable type` and 500
    the entire renderer for one malformed case. Round-5: coerce to a
    JSON-stable key so any payload survives.
    """
    cases = [
        {
            "case_id": "01",
            "main": {
                "status_code": 200,
                "body": {
                    "findings": [
                        {
                            "evidence": [
                                # Mixed payload types — would crash pre-round-5.
                                {"filters": {"col": "Age", "op": ">=", "val": 55}},
                                {"filters": ["Age >= 55", "OverTime == 'Yes'"]},
                                {"filters": "JobRole == 'Sales'"},
                                {"filters": None},
                            ]
                        }
                    ]
                },
            },
        }
    ]
    metrics = {"evidence_completeness": 1.0}
    # Must not raise.
    sec = _section_root_cause(metrics, cases)
    by_label = dict(sec.rows)
    # 4 distinct filter payloads ≥ 3 → has_factors = True
    assert by_label["是否围绕问题拆解影响因素"] == "是"


def test_root_cause_factor_set_skips_blank_filters() -> None:
    """Round-9: empty / null / whitespace filters don't count toward the
    factor-cardinality threshold. Pre-round-9, ``{"filters": None}`` and
    ``{"filters": ""}`` each contributed a *distinct* JSON-key (``"null"``,
    ``'""'``) that would push a no-real-factors finding over the ``≥ 3``
    threshold, falsely flagging the run as "tore down impact factors".

    The new ``_is_meaningful_filter`` predicate excludes None, blank
    strings, and empty containers before the set is built.
    """
    cases = [
        {
            "case_id": "01",
            "main": {
                "status_code": 200,
                "body": {
                    "findings": [
                        {
                            "evidence": [
                                {"filters": None},
                                {"filters": ""},
                                {"filters": "   "},
                                {"filters": []},
                                {"filters": {}},
                                # Only one truly meaningful filter remains.
                                {"filters": "Age >= 55"},
                            ]
                        }
                    ]
                },
            },
        }
    ]
    metrics = {"evidence_completeness": 1.0}
    sec = _section_root_cause(metrics, cases)
    by_label = dict(sec.rows)
    # 1 meaningful payload < 3 → has_factors = False.
    assert by_label["是否围绕问题拆解影响因素"] == "否"


def test_root_cause_factor_set_dedupes_equivalent_dict_payloads() -> None:
    """Equal dicts with reordered keys must collapse to one entry —
    `json.dumps(..., sort_keys=True)` makes the key stable.
    """
    cases = [
        {
            "case_id": "01",
            "main": {
                "status_code": 200,
                "body": {
                    "findings": [
                        {
                            "evidence": [
                                {"filters": {"col": "Age", "op": ">="}},
                                # Same payload, different key order.
                                {"filters": {"op": ">=", "col": "Age"}},
                                {"filters": {"col": "Tenure"}},
                            ]
                        }
                    ]
                },
            },
        }
    ]
    metrics = {"evidence_completeness": 1.0}
    sec = _section_root_cause(metrics, cases)
    by_label = dict(sec.rows)
    # Only 2 distinct payloads → has_factors = False (need ≥ 3)
    assert by_label["是否围绕问题拆解影响因素"] == "否"


# ---------------------------------------------------------------------------
# Round-6: null-safety on numeric reads (CodeRabbit #17 round-6)
#
# `metrics.get(key, 0)` returns the *stored* value when the key is present
# but its value is `null` in summary.json — the default only kicks in for
# missing keys. `None >= 0.9` and `None * 100` then raise `TypeError` and
# 500 the renderer. `_safe_rate()` coerces None / non-numeric / non-finite
# values to 0.0 so every comparison and f-string survives.
#
# Round-14 (CodeRabbit #17): the lenient rate is now emitted under BOTH
# `refusal_correct_accuracy` (preferred, matches the `refusal_correct_count`
# sibling) AND `refusal_accuracy_on_traps` (legacy alias) in `eval/run.py`.
# The renderer reads the preferred key first; legacy summary.json artifacts
# that only have `refusal_accuracy_on_traps` continue to render unchanged.
# See `test_interact_prefers_refusal_correct_accuracy_over_legacy_alias`
# below for the pin.
# ---------------------------------------------------------------------------


def test_interact_tolerates_explicit_null_metrics() -> None:
    """Every numeric read in §3 survives a `null`-valued key.

    Historical summary.json files serialised missing counters as explicit
    `null` rather than dropping the key; the default-arg form
    `metrics.get("k", 0)` returns `None` in that case and blows up the
    `>=` comparison and the `* 100` percentage in the note.
    """
    metrics: dict = {
        "main_success_rate": None,
        "followup_success_rate": None,
        "session_carry_rate": None,
        "refusal_accuracy_on_traps": None,
        "refusal_strict_accuracy": None,
    }
    # Must not raise — all four verdicts collapse to 否 at 0.0.
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    assert by_label["是否支持单轮交互"] == "否"
    assert by_label["是否支持多轮交互"] == "否"
    assert by_label["是否能够基于上一轮分析继续追问"] == "否"
    assert by_label["是否能够对数据不支持的问题说明原因"] == "否"
    # Note must render without a TypeError from `None * 100`.
    assert "0%" in sec.note


def test_statistics_tolerates_explicit_null_error_counters() -> None:
    """`stat_error_rate: null` must not crash the `> 0` comparison."""
    metrics: dict = {
        "evidence_completeness": 1.0,
        "statistical_error_count": None,
        "stat_error_rate": None,
        "stat_error_samples": None,
    }
    cases = [_csv_only_case()]
    sec = _section_statistics(metrics, cases)
    by_label = dict(sec.rows)
    # Null counters → "no errors observed".
    assert by_label["是否存在明显统计错误"] == "否"


def test_trend_tolerates_explicit_null_chart_and_length_metrics() -> None:
    """`distinct_chart_types: null` and `avg_summary_len_chars: null` must
    not crash `>= 1` / `< 400`.
    """
    metrics: dict = {
        "distinct_chart_types": None,
        "evidence_completeness": None,
        "avg_summary_len_chars": None,
    }
    cases = [_csv_only_case()]
    # Must not raise; all rows degrade to 否 / 部分存在 as appropriate.
    sec = _section_trend(metrics, cases)
    by_label = dict(sec.rows)
    assert by_label["是否输出趋势分析结果"] == "否"
    assert by_label["是否提供数据支撑"] == "否"


def test_root_cause_tolerates_explicit_null_hallucination_metrics() -> None:
    """`hallucination_rate: null` and `logical_error_rate: null` must not
    crash `>= HALLUCINATION_THRESHOLD`.
    """
    metrics: dict = {
        "evidence_completeness": 1.0,
        "hallucination_rate": None,
        "logical_error_rate": None,
        "hallucination_samples": None,
    }
    cases = [_csv_only_case()]
    sec = _section_root_cause(metrics, cases)
    by_label = dict(sec.rows)
    # Null rates → no hallucination claim.
    assert by_label["是否存在逻辑错误或幻觉"] == "否"


def test_interact_tolerates_non_numeric_string_metrics() -> None:
    """Garbage string values (e.g. `"N/A"`) must coerce to 0.0 rather
    than propagate `ValueError` from `float("N/A")`.
    """
    metrics: dict = {
        "main_success_rate": "N/A",
        "followup_success_rate": "oops",
        "session_carry_rate": "—",
        "refusal_strict_accuracy": "null",
    }
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    assert by_label["是否支持单轮交互"] == "否"
    assert "0%" in sec.note


# ---------------------------------------------------------------------------
# Round-7: non-finite floats + render-level datasets_total null fallback
#
# CR on PR #17 round-7 flagged two contract gaps in the round-6 work:
#   1. `_safe_rate` only guards `None` and `ValueError` from `float()` —
#      `float("nan")` and `float("inf")` survive unchanged. `nan * 100`
#      formats as "nan%" in the §3 note (not user-visible-but-wrong) and
#      `inf >= 0.9` is True (silently flips a fail to a pass — *very*
#      wrong). Round-7 adds an `isfinite` clamp.
#   2. `metrics.get("datasets_total") or len(cases)` works locally, but
#      no test exercises it through the full `render()` path. Without
#      one, a future inversion of the fallback would slip through.
#
# We deliberately skip the third nitpick (`stat_error_count` short
# alias) — `_section_statistics` only reads `statistical_error_count`,
# adding a test for an alias we don't honour would lock in a fictional
# contract (same reasoning as the `refusal_correct_*` skip in round-6).
# ---------------------------------------------------------------------------


def test_safe_rate_clamps_non_finite_floats() -> None:
    """`_safe_rate` collapses NaN / +inf / -inf to 0.0 alongside None.

    `nan >= PASS_THRESHOLD` is False (silently fails the row), but
    `nan * 100` formats as "nan%" in the §3 note — visible garbage.
    `inf >= PASS_THRESHOLD` is True — silently passes the row when the
    upstream metric is broken. The fix routes both through the same
    "no-signal" floor as None.
    """
    from eval.render_official_metrics import (  # type: ignore[import-not-found]
        _safe_rate,
    )

    assert _safe_rate(float("nan")) == 0.0
    assert _safe_rate(float("inf")) == 0.0
    assert _safe_rate(float("-inf")) == 0.0
    # Sanity: finite values still pass through unchanged.
    assert _safe_rate(0.85) == 0.85
    assert _safe_rate(1) == 1.0


def test_interact_tolerates_non_finite_float_metrics() -> None:
    """End-to-end: NaN / inf values in metrics flow cleanly through §3.

    Without the round-7 isfinite clamp, the note would render literal
    "nan%"/"inf%" cells (the f-string `{x * 100:.0f}%` produces "nan%"
    for NaN and "inf%" for infinity).
    """
    import math

    metrics: dict = {
        "main_success_rate": math.nan,
        "followup_success_rate": math.inf,
        "session_carry_rate": -math.inf,
        "refusal_strict_accuracy": math.nan,
    }
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    # All four rows degrade to 否 (no-signal floor).
    assert by_label["是否支持单轮交互"] == "否"
    assert by_label["是否支持多轮交互"] == "否"
    assert by_label["是否能够基于上一轮分析继续追问"] == "否"
    assert by_label["是否能够对数据不支持的问题说明原因"] == "否"
    # Note must NOT contain "nan%" or "inf%" — the cells render as 0%.
    assert "nan" not in sec.note.lower()
    assert "inf" not in sec.note.lower()
    assert "0%" in sec.note


def test_render_treats_null_datasets_total_as_len_cases(tmp_path: Path) -> None:
    """Top-level contract: an explicit `null` for `datasets_total` in
    `summary.json` must fall back to `len(cases)`, not render as the
    literal string `None`.

    Helper-level coercion only catches numeric reads; the report header
    embeds `datasets_total` directly via f-string. A regression that
    drops the fallback would surface as CJK `(None)` in the data-source
    line and break grader parsing — this test pins the render-level
    contract independently of the helpers.
    """
    summary = {
        "started_at": "2026-05-07T01:00:00Z",
        "completed_at": "2026-05-07T01:30:00Z",
        "metrics": {
            # Explicit null — what eval/run.py emits if the counter wasn't set.
            "datasets_total": None,
            "main_success_rate": 1.0,
            "followup_success_rate": 1.0,
            "session_carry_rate": 1.0,
            "refusal_accuracy_on_traps": 1.0,
            "evidence_completeness": 1.0,
            "distinct_chart_types": 3,
            "avg_summary_len_chars": 500,
            "multi_file_capable": True,
            "excel_capable": True,
        },
        "cases": [
            {"case_id": "01", "main": {"status_code": 200, "body": {"findings": []}}},
            {"case_id": "02", "main": {"status_code": 200, "body": {"findings": []}}},
        ],
    }
    run_dir = tmp_path / "fake-run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        __import__("json").dumps(summary), encoding="utf-8"
    )
    rendered = render(run_dir)
    # The data-source line must surface `len(cases) == 2`, not `None`.
    assert "（2 个用例）" in rendered
    assert "（None 个用例）" not in rendered
    # Score totals still render — the conclusion paragraph isn't
    # short-circuited by the fallback.
    assert "/ 100" in rendered or "/100" in rendered




# ---------------------------------------------------------------------------
# Round-12 (CodeRabbit #17): evidence predicates only see ok-main cases
#
# A failed turn (e.g. 422 with structured error envelope) can still
# carry a `body.findings` array. Pre-round-12 the four evidence-presence
# verdicts (`has_breakdown`, `has_dimension`, `has_conclusion`,
# `has_factors`) scanned all cases unconditionally and would flip to
# "是" off failure-payload artefacts even when the run had a 1/5 main
# success rate. Now they only see status_code==200 cases.
# ---------------------------------------------------------------------------


def _failed_case_with_phantom_evidence(case_id: str = "01") -> dict:
    """A 422 case carrying a `body` shaped like a successful response.

    Real failure envelopes don't always carry `findings`/
    `recommendations`, but a regression in the route layer (or an
    older saved run JSON) plausibly could. The pre-round-12 renderer
    treated any `body` it found as analysis evidence — we pin the new
    contract that says "no, only `status_code == 200` cases count".
    """
    return {
        "case_id": case_id,
        "main": {
            "status_code": 422,
            "body": {
                "findings": [
                    {
                        "evidence": [
                            {"row_count": 100, "value": 5.0, "filters": "x == 'A'"},
                            {"row_count": 100, "value": 5.0, "filters": "x == 'B'"},
                            {"row_count": 100, "value": 5.0, "filters": "x == 'C'"},
                        ]
                    }
                ],
                "recommendations": ["do something"],
            },
        },
    }


def test_section_statistics_ignores_failed_main_evidence() -> None:
    metrics = {"main_success_rate": 0.0, "evidence_completeness": 1.0}
    sec = _section_statistics(metrics, [_failed_case_with_phantom_evidence()])
    by_label = dict(sec.rows)
    # Failure-only run → no breakdown/value evidence credit.
    assert by_label["是否包含字段分布、数量、占比等统计信息"] == "否"


def test_section_trend_ignores_failed_main_evidence() -> None:
    metrics = {"evidence_completeness": 1.0, "avg_summary_len_chars": 600}
    sec = _section_trend(metrics, [_failed_case_with_phantom_evidence()])
    by_label = dict(sec.rows)
    assert by_label["是否结合时间、类别或其他可比较维度分析变化"] == "否"


def test_section_root_cause_ignores_failed_main_evidence() -> None:
    metrics = {"evidence_completeness": 1.0, "avg_summary_len_chars": 600}
    sec = _section_root_cause(metrics, [_failed_case_with_phantom_evidence()])
    by_label = dict(sec.rows)
    assert by_label["是否输出根因分析结论"] == "否"
    assert by_label["是否围绕问题拆解影响因素"] == "否"


def test_interact_prefers_refusal_correct_accuracy_over_legacy_alias() -> None:
    """Round-14 (CodeRabbit #17): the renderer must read the new
    preferred key `refusal_correct_accuracy` when present, and only
    fall back to the legacy `refusal_accuracy_on_traps` when the new
    key is absent. A summary.json that ships both with DIFFERENT
    values would otherwise be ambiguous — we pin the preferred
    reading.
    """
    metrics = {
        "main_success_rate": 1.0,
        "followup_success_rate": 1.0,
        "session_carry_rate": 1.0,
        # Legacy alias says refuse_ok=0.0 (would fail the row),
        # preferred key says 1.0 (passes). If the renderer honours
        # the preferred key, the row verdict is 是.
        "refusal_accuracy_on_traps": 0.0,
        "refusal_correct_accuracy": 1.0,
    }
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    assert by_label["是否能够对数据不支持的问题说明原因"] == "是"


def test_interact_falls_back_to_legacy_refusal_key_when_preferred_missing() -> None:
    """Back-compat: old summary.json files have only
    `refusal_accuracy_on_traps`; the renderer must still render them."""
    metrics = {
        "main_success_rate": 1.0,
        "followup_success_rate": 1.0,
        "session_carry_rate": 1.0,
        "refusal_accuracy_on_traps": 1.0,
        # No `refusal_correct_accuracy` — the old path.
    }
    sec = _section_interact(metrics)
    by_label = dict(sec.rows)
    assert by_label["是否能够对数据不支持的问题说明原因"] == "是"
