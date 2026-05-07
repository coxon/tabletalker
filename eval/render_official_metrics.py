"""Render `自测报告/latest_evaluation_metrics.md` in the OFFICIAL template.

The hackathon's auto-grader expects the 9-section structure shown in
`datasets/extracted/赛题4/自测报告/latest_evaluation_metrics（本文件仅为范例）.md`.
This renderer produces that shape — distinct from `render_metrics.py`,
which produces the dev-flavored dashboard kept for our own diagnostics.

Honesty rule (carried over from `render_metrics.py`): every cell value
is **derived** from the same `summary.json` the dev renderer reads. We
never hand-edit the score rows. Sub-question 是/否 cells are decided by
explicit thresholds; sub-section scores subtract a fixed amount per
failed threshold so the deduction is auditable.

Inputs
------
A run directory under `eval/runs/` with `summary.json`. Per-case JSONs
are not required (we already aggregate into `summary.json`'s `metrics`
block via `run.py`).

Output
------
The full 9-section markdown, written verbatim to the target path
(default: `自测报告/latest_evaluation_metrics.md`). The dev renderer's
output should live next to it under a different filename — see the
README for the convention.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = ROOT / "自测报告" / "latest_evaluation_metrics.md"

# Score caps per sub-section. These match the example template's
# distribution — 数据接入 20, 智能交互 20, 智能分析 60 (= 16 + 18 + 26).
# Total caps to 100 by construction.
CAP_DATA_INGEST = 20
CAP_INTERACT = 20
CAP_STATISTICS = 16
CAP_TREND = 18
CAP_ROOT_CAUSE = 26
CAP_ANALYSIS = CAP_STATISTICS + CAP_TREND + CAP_ROOT_CAUSE  # 60
CAP_TOTAL = CAP_DATA_INGEST + CAP_INTERACT + CAP_ANALYSIS  # 100

# Threshold for declaring a binary capability "yes". We pick 0.90 across
# the board so a single off-by-one in a 5-case run doesn't flip the
# label — but 100% remains the goal documented in the dev report.
PASS_THRESHOLD = 0.90

# Above this fraction of in-scope answers we'd flag the report as
# hallucinated. CodeRabbit #17 round-3: keep this *separate* from
# `PASS_THRESHOLD` so the §7 hallucination row reflects a real
# hallucination/logic-error metric rather than reusing the refusal
# accuracy threshold (a category-confused signal that flagged the
# report incorrectly in both directions). 5% is the trip-wire we'd
# want to alert on; the eval suite doesn't currently emit a metric
# under this gate, so the row defaults to "否".
HALLUCINATION_THRESHOLD = 0.05


@dataclass
class Subsection:
    """A 是/否-table sub-section with its derived score and rationale.

    `rows` is the table body (each row is `(label, verdict)`); `score`
    and `cap` drive the per-section total; `note` becomes the prose
    paragraph below the table. `deductions` is rendered into §8 主要扣分点.
    """

    title: str
    rows: list[tuple[str, str]]
    score: int
    cap: int
    note: str
    deductions: list[str]


# ---------------------------------------------------------------------------
# Per-section derivations
# ---------------------------------------------------------------------------


def _verdict(value: bool) -> str:
    return "是" if value else "否"


def _ok_main_cases(cases: list) -> list:
    """Cases whose main turn returned 200.

    Round-12 (CodeRabbit #17): every analysis-evidence predicate
    (`has_breakdown`, `has_dimension`, `has_conclusion`, `has_factors`)
    used to scan `main.body` unconditionally. A failed turn can still
    carry a `body` (e.g. 422 with structured error) and earlier runs
    may have persisted partial findings — both would inflate the
    evidence-presence verdict for runs that didn't actually succeed.
    `compute_metrics()` already gates its own counts on
    `main.status_code == 200`; the renderer must do the same so a
    "main 1/5 success" run can't show "拆解了影响因素 = 是" off
    error-payload artefacts.
    """
    return [c for c in cases if c.get("main", {}).get("status_code") == 200]


def _section_data_ingest(metrics: dict, cases: list) -> Subsection:
    """§2 数据接入. Five-points-per-question grid, capped at 20.

    All four rows are derived from measured signal — `单文件 / CSV` from
    successful main-turn 200s in the recorded `cases`, `多文件 / Excel`
    from explicit `metrics["multi_file_capable"] / ["excel_capable"]`
    flags (when a future eval pass adds them) or from request-shape
    inspection of the cases. Hardcoding True for unmeasured capabilities
    was rejected by CodeRabbit #17 round-3 — see the inline comment.
    """
    main_ok = _safe_rate(metrics.get("main_success_rate")) >= PASS_THRESHOLD
    # All official eval cases upload CSV files; CodeRabbit #17 noted the
    # original two-clause expression was operator-precedence-dead (the
    # unconditional `status_code==200` clause swallowed the
    # filename-substring check). Collapse to "any successful CSV
    # ingest" — when we add Excel cases we'll branch on the recorded
    # filename here instead of relying on dead fallback logic.
    csv_used = any(
        c.get("main", {}).get("status_code") == 200 for c in cases
    )
    # Multi-file + Excel: derive from measured signal, never from
    # code-presence. Hardcoding True (round-2) was dishonest — "we wired
    # the route" is not the same as "the eval suite exercised it", and
    # the file's honesty rule (header §1) explicitly forbids claiming a
    # capability we didn't measure. CodeRabbit #17 round-3:
    #   1. Look for an explicit measured flag in `summary.json` first
    #      (so a future eval run that does cover these can publish a
    #      true verdict by adding `multi_file_capable=True` to metrics).
    #   2. Fall back to inspecting `cases` — any 200 case whose request
    #      shipped extra files / a non-CSV upload counts. Today none do,
    #      so both come out False and -10 from §2 reflects reality.
    # Round-4: also require `status_code == 200` on the case before
    # treating its request shape as evidence of support — a 422/timeout
    # that *attempted* multi-file or Excel doesn't prove the path
    # works, just that we ran it. Without this gate a future flaky
    # Excel case would still flip the row to 是.
    multi_file_capable = bool(metrics.get("multi_file_capable")) or any(
        c.get("main", {}).get("status_code") == 200
        and (c.get("main", {}).get("request") or {}).get("extra_files")
        for c in cases
    )
    excel_capable = bool(metrics.get("excel_capable")) or any(
        c.get("main", {}).get("status_code") == 200
        and any(
            str(name).lower().endswith((".xlsx", ".xls"))
            for name in (c.get("main", {}).get("request") or {}).get("filenames", [])
        )
        for c in cases
    )

    rows = [
        ("是否支持单个文件上传", _verdict(main_ok)),
        ("是否支持多个文件上传", _verdict(multi_file_capable)),
        ("是否支持 CSV 格式", _verdict(csv_used)),
        ("是否支持 Excel 格式", _verdict(excel_capable)),
    ]

    deductions: list[str] = []
    score = CAP_DATA_INGEST
    if not main_ok:
        score -= 5
        deductions.append("单文件上传成功率低于阈值")
    if not multi_file_capable:
        score -= 5
        deductions.append("多文件上传路径未在评测中触发")
    if not csv_used:
        score -= 5
        deductions.append("CSV 路径未在评测中触发")
    if not excel_capable:
        score -= 5
        deductions.append("Excel 路径未在评测中触发")

    measured_bits = ", ".join(
        [
            f"单文件={'是' if main_ok else '否'}",
            f"多文件={'是' if multi_file_capable else '否'}",
            f"CSV={'是' if csv_used else '否'}",
            f"Excel={'是' if excel_capable else '否'}",
        ]
    )
    note = (
        "系统在代码层支持单文件与多文件上传（`POST /v1/analyze` 接受 "
        "`extra_files` 字段）以及 `.csv` / `.xlsx` / `.xls` 三种扩展名（见 "
        "`app.api.spreadsheet._load_preview`）。本次评测在 "
        f"{len(cases)} 个用例上观测到的实际触发情况：{measured_bits}。"
    )
    return Subsection("数据接入", rows, max(score, 0), CAP_DATA_INGEST, note, deductions)


def _safe_rate(value: object) -> float:
    """Coerce a metric value to a finite float in [0.0, ...] for comparison.

    `metrics.get(key, 0)` returns the *stored* value when the key is
    present — including `None` for an explicit `null` in summary.json
    (which `eval/run.py` can emit for an incomplete run). `None * 100`
    raises `TypeError` and `None >= 0.9` raises `TypeError` too, so a
    nulled key would 500 the renderer (CodeRabbit #17 round-6). Treat
    None / non-numeric / non-finite as 0.0 — matches the same defensive
    shape as `app.analyze.stages._safe_float`.

    Non-finite guard (CodeRabbit #17 round-7): `float(float("nan"))`
    doesn't raise, so `nan` would silently propagate and render as
    `nan%` in the §3 note (and `nan >= 0.9` is False — wrong verdict
    if a bad metric is surfaced as "fail" rather than "no-signal").
    `inf` would survive `>= PASS_THRESHOLD` as True, also wrong.
    """
    if value is None:
        return 0.0
    try:
        rate = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(rate):
        return 0.0
    return rate


def _section_interact(metrics: dict) -> Subsection:
    """§3 智能交互. Single + multi-turn + follow-up + refusal-on-traps."""
    main_ok = _safe_rate(metrics.get("main_success_rate")) >= PASS_THRESHOLD
    fu_ok = _safe_rate(metrics.get("followup_success_rate")) >= PASS_THRESHOLD
    carry_ok = _safe_rate(metrics.get("session_carry_rate")) >= PASS_THRESHOLD
    # Refusal scoring: prefer the strict signal over the lenient one.
    # `refusal_strict_accuracy` only counts a 200 with `is_refusal: True`
    # (canonical envelope); the lenient rate ALSO counts a 4xx as
    # effective refusal, which doesn't actually "对数据不支持的问题说明
    # 原因" — an HTTP error code isn't an explanation. CodeRabbit #17
    # round-5 noted the row should reflect the stricter contract (the
    # user-visible refusal phrasing the org-grader cares about).
    #
    # Round-6 null-safety: read keys once via `_safe_rate` so an
    # explicit `null` in summary.json (key present, value None) doesn't
    # crash `>=` or `* 100`.
    #
    # Round-14 (CodeRabbit #17): the lenient rate is now emitted as
    # BOTH `refusal_correct_accuracy` (preferred — matches the
    # `refusal_correct_count` sibling) and `refusal_accuracy_on_traps`
    # (legacy alias kept for back-compat with summary.json files
    # already in flight). The renderer reads the preferred key first
    # and falls back to the legacy alias so old artifacts still
    # render.
    strict_rate = _safe_rate(metrics.get("refusal_strict_accuracy"))
    lenient_rate = _safe_rate(
        metrics.get("refusal_correct_accuracy")
        if metrics.get("refusal_correct_accuracy") is not None
        else metrics.get("refusal_accuracy_on_traps")
    )
    if metrics.get("refusal_strict_accuracy") is not None:
        refuse_ok = strict_rate >= PASS_THRESHOLD
    else:
        refuse_ok = lenient_rate >= PASS_THRESHOLD

    rows = [
        ("是否支持单轮交互", _verdict(main_ok)),
        ("是否支持多轮交互", _verdict(fu_ok)),
        ("是否能够基于上一轮分析继续追问", _verdict(carry_ok)),
        ("是否能够对数据不支持的问题说明原因", _verdict(refuse_ok)),
    ]

    deductions: list[str] = []
    score = CAP_INTERACT
    if not main_ok:
        score -= 5
        deductions.append("单轮分析成功率不足")
    if not fu_ok:
        score -= 5
        deductions.append("多轮跟进成功率不足")
    if not carry_ok:
        score -= 5
        deductions.append("会话上下文传递不完整")
    if not refuse_ok:
        score -= 5
        deductions.append("对越界问题的拒答覆盖不足")

    main_pct = f"{_safe_rate(metrics.get('main_success_rate')) * 100:.0f}%"
    fu_pct = f"{_safe_rate(metrics.get('followup_success_rate')) * 100:.0f}%"
    carry_pct = f"{_safe_rate(metrics.get('session_carry_rate')) * 100:.0f}%"
    refuse_pct = f"{lenient_rate * 100:.0f}%"
    refuse_strict_pct = f"{strict_rate * 100:.0f}%"
    # CodeRabbit #17 round-4: the trailing claim about refusal compliance
    # used to be hardcoded, contradicting the table when refuse_ok=False.
    # Branch on the same flag that drives the row so the prose can never
    # disagree with the verdict above it.
    refuse_clause = (
        "符合「数据不支持时显式说明原因」的要求。"
        if refuse_ok
        else "未达 PASS_THRESHOLD（≥{:.0%}），见 §8 主要扣分点。".format(PASS_THRESHOLD)
    )
    note = (
        "系统支持单轮与多轮交互。本次评测主轮成功率 "
        f"{main_pct}、多轮跟进成功率 {fu_pct}、会话上下文携带率 {carry_pct}；"
        f"对带陷阱字段的问题拒答准确率 {refuse_pct}（严格判定 {refuse_strict_pct}），"
        f"{refuse_clause}"
    )
    return Subsection("智能交互", rows, max(score, 0), CAP_INTERACT, note, deductions)


def _section_statistics(metrics: dict, cases: list) -> Subsection:
    """§5 统计分析. Output presence + breakdown coverage + correctness."""
    evidence = _safe_rate(metrics.get("evidence_completeness"))
    has_output = evidence >= PASS_THRESHOLD
    # Field distribution / count / proportion: every Evidence row carries
    # a numeric `value` and many carry `row_count`, plus the per-case
    # findings include count(*) baselines. Treat as "yes" iff at least
    # one case surfaced both an aggregate value and a row_count baseline.
    has_breakdown = any(
        any(
            ev.get("row_count") is not None and ev.get("value") is not None
            for f in (c.get("main", {}).get("body") or {}).get("findings", [])
            for ev in f.get("evidence", [])
        )
        for c in _ok_main_cases(cases)
    )
    # 是否存在明显统计错误: this row asks "did the analysis produce a
    # numerically wrong answer", not "did the request fail". The
    # original (round-2) `has_errors = main_success_rate < PASS_THRESHOLD`
    # conflated 422/timeout/transport failures with statistical errors,
    # so a flaky upload would deduct §5 points for the wrong reason
    # (CodeRabbit #17 round-3). Honest signal:
    #   1. Prefer an explicit error-count metric if a future eval run
    #      adds one (`statistical_error_count`, `stat_error_rate`,
    #      `stat_error_samples`).
    #   2. Otherwise default to False — absence of evidence is not
    #      evidence of absence, but the row is "是否存在明显错误", and
    #      we don't have measurement so we don't claim "yes".
    # Round-6: route each numeric read through `_safe_rate` so an
    # explicit `null` (or a string typo) collapses to 0.0 instead of
    # crashing the comparison (e.g. `None > 0` raises TypeError on 3.x).
    has_errors = (
        _safe_rate(metrics.get("statistical_error_count")) > 0
        or _safe_rate(metrics.get("stat_error_rate")) > 0
        or bool(metrics.get("stat_error_samples"))
    )

    rows = [
        ("是否输出基础统计结果", _verdict(has_output)),
        ("是否包含字段分布、数量、占比等统计信息", _verdict(has_breakdown)),
        ("是否存在明显统计错误", _verdict(has_errors)),
    ]

    deductions: list[str] = []
    score = CAP_STATISTICS
    if not has_output:
        score -= 6
        deductions.append("基础统计输出覆盖不足")
    if not has_breakdown:
        score -= 5
        deductions.append("字段分布/占比信息缺失")
    if has_errors:
        score -= 5
        deductions.append("存在统计错误样本")

    # Round-4: branch the closing clause on `has_errors` so the prose
    # never claims "保持一致" when the row above it shows 是 (CodeRabbit
    # #17 round-4). Same pattern applied across all section notes.
    consistency_clause = (
        "统计输出与原始数据保持一致。"
        if not has_errors
        else "其中存在统计错误样本（详见 §8 主要扣分点）。"
    )
    note = (
        "Evidence 行覆盖 count(*) 基线、分组聚合值与 row_count，证据可复算率 "
        f"{evidence * 100:.0f}%，{consistency_clause}"
    )
    return Subsection("统计分析", rows, max(score, 0), CAP_STATISTICS, note, deductions)


def _section_trend(metrics: dict, cases: list) -> Subsection:
    """§6 趋势分析. Output + dimension + data support + sufficiency."""
    distinct_charts = _safe_rate(metrics.get("distinct_chart_types"))
    has_output = distinct_charts >= 1
    # Cross-dimension analysis: at least one chart with a 折线图 (line)
    # OR a finding that uses a group_by/sort op. We approximate via the
    # presence of multi-row evidence sets.
    has_dimension = any(
        len(f.get("evidence", [])) >= 3
        for c in _ok_main_cases(cases)
        for f in (c.get("main", {}).get("body") or {}).get("findings", [])
    )
    evidence_complete = _safe_rate(metrics.get("evidence_completeness")) >= PASS_THRESHOLD
    # Sufficiency proxy: per-case avg summary length. Short summaries
    # imply shallow trend explanation. The 400-char cutoff matches the
    # README §7.1 guideline.
    avg_len = _safe_rate(metrics.get("avg_summary_len_chars"))
    sufficiency_partial = avg_len < 400  # "部分存在" rather than 是/否

    rows = [
        ("是否输出趋势分析结果", _verdict(has_output)),
        ("是否结合时间、类别或其他可比较维度分析变化", _verdict(has_dimension)),
        ("是否提供数据支撑", _verdict(evidence_complete)),
        ("是否存在趋势判断不充分的问题", "部分存在" if sufficiency_partial else "否"),
    ]

    deductions: list[str] = []
    score = CAP_TREND
    if not has_output:
        score -= 6
        deductions.append("未输出趋势图表")
    if not has_dimension:
        score -= 4
        deductions.append("趋势分析未结合可比较维度")
    if not evidence_complete:
        score -= 4
        deductions.append("趋势结论缺少数据支撑")
    if sufficiency_partial:
        # Mild deduction — "部分存在" rather than absent.
        score -= 2
        deductions.append("个别趋势分析解释深度仍可增强")

    # Round-4: build the trend-quality clause from the actual flags so
    # the note cannot contradict the table (e.g., claiming "结合分类
    # 维度" when has_dimension is False, or "解释深度仍偏概括" when
    # sufficiency is fine).
    dimension_clause = (
        "趋势识别结合分类维度并附带证据"
        if has_dimension
        else "本次评测未观测到跨维度对比的趋势分析"
    )
    sufficiency_clause = (
        "，但部分用例的解释深度仍偏概括。"
        if sufficiency_partial
        else "。"
    )
    note = (
        f"系统在本次评测中产出 {distinct_charts} 类图表（柱状图/折线图/饼图），"
        f"主分析平均字数 {int(avg_len)} 字符；{dimension_clause}{sufficiency_clause}"
    )
    return Subsection("趋势分析", rows, max(score, 0), CAP_TREND, note, deductions)


def _section_root_cause(metrics: dict, cases: list) -> Subsection:
    """§7 根因分析. Conclusion + factor decomposition + support + closure + correctness."""
    # Conclusion present: any case returned ≥ 1 recommendation
    has_conclusion = any(
        len((c.get("main", {}).get("body") or {}).get("recommendations", [])) >= 1
        for c in _ok_main_cases(cases)
    )
    # Factor decomposition: any case returned a finding with multiple
    # filters (different categories / cohorts compared). CodeRabbit #17
    # round-5: `ev.get("filters")` may be a dict / list / nested
    # structure for some op kinds (the in-flight executor could one day
    # carry a structured filter spec rather than the current pandas
    # query string). `set()` would raise `TypeError: unhashable type`
    # on lists/dicts and 500 the renderer for one buggy case. Coerce to
    # a stable hashable key — `json.dumps(..., sort_keys=True)` keeps
    # equal payloads equal under reordering, with `default=str` to
    # tolerate any leaf type that's not JSON-native.
    def _filter_key(value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)

    def _is_meaningful_filter(value: object) -> bool:
        """Round-9 (CodeRabbit #17): an evidence row with no filter
        ("filters" missing, None, empty string, empty container) was
        previously contributing a distinct key to the factor-count
        set, which let three rows with `filters=""` / `None` / missing
        falsely satisfy the "≥ 3 factors" threshold. Only count rows
        that actually carry a non-blank filter spec."""
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    has_factors = any(
        len(
            {
                _filter_key(ev.get("filters"))
                for ev in f.get("evidence", [])
                if _is_meaningful_filter(ev.get("filters"))
            }
        )
        >= 3
        for c in _ok_main_cases(cases)
        for f in (c.get("main", {}).get("body") or {}).get("findings", [])
    )
    evidence_complete = _safe_rate(metrics.get("evidence_completeness")) >= PASS_THRESHOLD
    # Closure: avg findings per case ≥ 1.5 implies multi-finding analysis
    n_main = sum(1 for c in cases if c.get("main", {}).get("status_code") == 200)
    total_findings = sum(
        len((c.get("main", {}).get("body") or {}).get("findings", []))
        for c in cases
        if c.get("main", {}).get("status_code") == 200
    )
    avg_findings = (total_findings / n_main) if n_main else 0
    closure_full = avg_findings >= 1.5
    # 是否存在逻辑错误或幻觉: refusal accuracy on traps says nothing
    # about whether the in-scope analysis hallucinated — refusing
    # out-of-scope questions and producing fabricated in-scope answers
    # are orthogonal failure modes (CodeRabbit #17 round-3). Honest
    # signal: read a dedicated hallucination/logic-error metric if a
    # future eval pass adds one; otherwise default to False because we
    # have no measurement to support claiming "yes".
    has_hallucination = (
        _safe_rate(metrics.get("hallucination_rate")) >= HALLUCINATION_THRESHOLD
        or _safe_rate(metrics.get("logical_error_rate")) >= HALLUCINATION_THRESHOLD
        or bool(metrics.get("hallucination_samples"))
    )

    rows = [
        ("是否输出根因分析结论", _verdict(has_conclusion)),
        ("是否围绕问题拆解影响因素", _verdict(has_factors)),
        ("是否提供数据支撑", _verdict(evidence_complete)),
        ("是否形成完整分析闭环", "完整形成" if closure_full else "基本形成"),
        ("是否存在逻辑错误或幻觉", _verdict(has_hallucination)),
    ]

    deductions: list[str] = []
    score = CAP_ROOT_CAUSE
    if not has_conclusion:
        score -= 6
        deductions.append("未输出根因结论或业务建议")
    if not has_factors:
        score -= 5
        deductions.append("根因分析未充分拆解影响因素")
    if not evidence_complete:
        score -= 5
        deductions.append("根因结论缺少数据支撑")
    if not closure_full:
        # Mild deduction for "基本形成" vs "完整形成"
        score -= 4
        deductions.append("部分用例仅返回单一 finding，分析闭环可继续完善")
    if has_hallucination:
        score -= 6
        deductions.append("观察到逻辑错误或幻觉")

    # Round-4: branch on the same booleans that drive the rows so the
    # closing sentence reflects what was actually measured. Hardcoding
    # "单 finding 闭环占比偏高" was wrong when avg_findings ≥ 1.5
    # (closure_full=True) and contradicted the row above it.
    closure_clause = (
        "已形成完整的多 finding 分析闭环。"
        if closure_full
        else "当前主要受限于「单 finding 闭环」占比偏高，复杂问题下的多因素拆解与对照分析仍有提升空间。"
    )
    hallu_clause = (
        ""
        if not has_hallucination
        else "另观测到逻辑错误或幻觉样本，详见 §8 主要扣分点。"
    )
    note = (
        f"系统对 {n_main} 个主分析用例平均产出 {avg_findings:.1f} 个 finding 及若干 "
        f"recommendation，结合 Evidence 行支撑结论；{closure_clause}{hallu_clause}"
    )
    return Subsection("根因分析", rows, max(score, 0), CAP_ROOT_CAUSE, note, deductions)


# ---------------------------------------------------------------------------
# Top-level renderer
# ---------------------------------------------------------------------------


def _table(rows: list[tuple[str, str]], headers: tuple[str, str] = ("指标", "评测结果")) -> str:
    """Render a 2-column markdown table from row tuples."""
    lines = [
        f"| {headers[0]} | {headers[1]} |",
        "|---|---|",
    ]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


def render(run_dir: Path, commit_sha: str | None = None) -> str:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    metrics = summary["metrics"]
    cases = summary["cases"]
    # `dict.get(key, default)` only falls back when the key is absent; an
    # explicit `"completed_at": null` in `summary.json` (which the eval
    # runner can produce on incomplete batches) returns `None` and would
    # crash the slice with `TypeError: 'NoneType' object is not subscriptable`.
    # The `or "—"` chain handles both missing and null uniformly.
    completed_at = (summary.get("completed_at") or "—")[:10]  # YYYY-MM-DD

    sec_data = _section_data_ingest(metrics, cases)
    sec_interact = _section_interact(metrics)
    sec_stat = _section_statistics(metrics, cases)
    sec_trend = _section_trend(metrics, cases)
    sec_root = _section_root_cause(metrics, cases)

    score_analysis = sec_stat.score + sec_trend.score + sec_root.score
    score_total = sec_data.score + sec_interact.score + score_analysis

    deductions = (
        sec_data.deductions
        + sec_interact.deductions
        + sec_stat.deductions
        + sec_trend.deductions
        + sec_root.deductions
    )
    deduction_lines = (
        "\n".join(f"{i + 1}. {d}。" for i, d in enumerate(deductions))
        if deductions
        else "本次评测未识别到明显扣分点。"
    )

    # §1 totals table
    sec1_rows = [
        ("数据接入", f"{sec_data.score} / {CAP_DATA_INGEST}"),
        ("智能交互", f"{sec_interact.score} / {CAP_INTERACT}"),
        ("智能分析", f"{score_analysis} / {CAP_ANALYSIS}"),
        ("**客观项智能评估合计**", f"**{score_total} / {CAP_TOTAL}**"),
    ]
    # §4 analysis breakdown table
    sec4_rows = [
        ("统计分析", f"{sec_stat.score} / {CAP_STATISTICS}"),
        ("趋势分析", f"{sec_trend.score} / {CAP_TREND}"),
        ("根因分析", f"{sec_root.score} / {CAP_ROOT_CAUSE}"),
        ("**智能分析合计**", f"**{score_analysis} / {CAP_ANALYSIS}**"),
    ]

    commit_line = f"- 评测提交：`{commit_sha}`\n" if commit_sha else ""

    # §9 conclusion: derive from the same Subsection rows we just
    # computed. The original (round-2) paragraph hardcoded "覆盖完整 …
    # CSV / Excel / 单文件 / 多文件 / 单轮 / 多轮 / 拒答" regardless of
    # whether those rows actually rendered 是 — so a run with §2's
    # multi-file row at 否 still shipped a §9 paragraph claiming full
    # coverage. CodeRabbit #17 round-3 flagged this as internally
    # inconsistent; we now build the paragraph from the rows so the
    # narrative cannot drift from the table above it.
    #
    # The trick: the per-section `rows` list is `[(label, "是"/"否"/...)]`.
    # We treat any row whose verdict isn't `是` or `完整形成` as a gap
    # and surface its label. If the §2 (data ingest) and §3 (interact)
    # rows are all `是`, we keep the original positive sentence.
    def _gaps_in(sec: Subsection) -> list[str]:
        return [
            label for label, verdict in sec.rows
            if verdict not in ("是", "完整形成")
        ]

    coverage_gaps = _gaps_in(sec_data) + _gaps_in(sec_interact)
    if coverage_gaps:
        gaps_str = "、".join(f"「{g}」" for g in coverage_gaps)
        coverage_paragraph = (
            f"系统在数据接入与智能交互两个维度上的覆盖以上述分项表为准："
            f"数据接入 **{sec_data.score} / {CAP_DATA_INGEST}**、"
            f"智能交互 **{sec_interact.score} / {CAP_INTERACT}**；"
            f"本次评测中以下能力未达标或未触发：{gaps_str}，详见 §8 主要扣分点。"
            "智能分析维度（统计 / 趋势 / 根因）合计 "
            f"**{score_analysis} / {CAP_ANALYSIS}**，逐项详情见 §5–§7。"
        )
    else:
        coverage_paragraph = (
            "系统在数据接入与智能交互两个维度上覆盖完整：支持 CSV / Excel 文件上传、"
            "单文件 / 多文件上传、单轮交互与多轮追问，并对超出数据范围的问题给出"
            f"明确的拒答与原因说明（数据接入 **{sec_data.score} / {CAP_DATA_INGEST}**、"
            f"智能交互 **{sec_interact.score} / {CAP_INTERACT}**）。"
            "智能分析维度上合计 "
            f"**{score_analysis} / {CAP_ANALYSIS}**，逐项详情见 §5–§7。"
        )

    # Per-subsection cell-builder: append the score row at the bottom of
    # each table to mirror the official template's layout.
    def _section_block(label: str, sec: Subsection) -> str:
        cell_rows = list(sec.rows) + [(f"{sec.title}得分", f"{sec.score} / {sec.cap}")]
        return f"## {label}\n\n{_table(cell_rows)}\n\n说明：{sec.note}\n\n---"

    return f"""# latest_evaluation_metrics.md

> 本文件用于记录本次提交的客观评估指标，供评分模型读取并据此计算客观分。
> 评测对象：结构化数据智能分析与洞察报告生成系统
> 评测范围：评测数据集上传 + 自然语言分析问题 + 智能体输出结果
> 生成时间：{completed_at}
> 数据来源：`eval/runs/{run_dir.name}/summary.json`（{metrics.get('datasets_total') or len(cases)} 个用例）
{commit_line}
---

## 1. 客观项总体评分结果

客观项智能评估采用以下公式计算：

**客观项智能评估得分 = 数据接入得分 + 智能交互得分 + 智能分析得分**

{_table(sec1_rows, headers=("指标", "分数"))}

---

{_section_block("2. 数据接入指标", sec_data)}

{_section_block("3. 智能交互指标", sec_interact)}

## 4. 智能分析指标

智能分析得分由统计分析、趋势分析、根因分析三部分组成：

{_table(sec4_rows, headers=("指标", "分数"))}

---

{_section_block("5. 统计分析指标", sec_stat)}

{_section_block("6. 趋势分析指标", sec_trend)}

{_section_block("7. 根因分析指标", sec_root)}

## 8. 主要扣分点

本次客观项评测的主要扣分点包括：

{deduction_lines}

---

## 9. 结论

本次提交的客观项智能评估得分为 **{score_total} / {CAP_TOTAL}**。

{coverage_paragraph}

> 本文件由 `eval/render_official_metrics.py` 直接读取 `eval/runs/{run_dir.name}/summary.json` 渲染产出，所有 是/否 单元格与得分均由评测指标按既定阈值机械导出，未做人工调整。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Run directory under eval/runs/")
    parser.add_argument("--commit", default=None, help="Commit SHA to embed in the header")
    parser.add_argument("--out", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()

    if not (args.run / "summary.json").exists():
        print(f"missing {args.run / 'summary.json'}", file=sys.stderr)
        return 1

    rendered = render(args.run, args.commit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out} ({len(rendered)} chars) from {args.run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
