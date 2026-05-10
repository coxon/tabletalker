"""Follow-up prompt assembly — the LLM context handed off between turns.

`docs/session-state.md` §3 specifies the exact shape: original question,
the running list of findings, named cohorts in scope, charts already
rendered, and finally the new follow-up question. Keeping the assembler
in its own module lets us unit-test the string output deterministically
without firing a real LLM call.

The output is a *system prompt* in Chinese (matching the planner and
finalise prompts elsewhere). The follow-up route prepends it to the
planner's normal `system + user` message pair.
"""

from __future__ import annotations

from app.analyze.schema import Finding
from app.session.cohort import CohortDef
from app.session.store import Session

_SCOPED_REFERENCE_TERMS = (
    "其中",
    "这些",
    "这类",
    "这群",
    "他们",
    "它们",
    "该地区",
    "上述地区",
    "该国家",
    "上述国家",
    "这个国家",
    "这个地区",
    "上述",
)

_WHOLE_DATASET_TERMS = (
    "全量",
    "全部数据",
    "全数据",
    "整体数据",
    "整个数据集",
    "所有数据",
    "不限定",
    "不限",
)


def render_followup_system_prompt(session: Session, follow_up_question: str) -> str:
    """Build the prelude that briefs the planner about the parent turn.

    See `docs/session-state.md` §3 for the canonical layout.
    """

    if session.refused:
        # Refusal carries through — cohorts are empty, no findings to
        # reference. The planner's job here is to politely re-state the
        # refusal in the follow-up's id, not invent new analysis.
        return _refusal_prelude(session, follow_up_question)

    sections: list[str] = [
        "你是数据分析助手。用户已经完成过一次分析；现在他们要追问。",
        f"\n**原始问题**：{session.original_question.strip()}",
    ]

    if session.findings:
        sections.append("\n**已确认的发现（直接引用，不要重新推导）**：")
        sections.append(_render_findings(session.findings))

    if session.cohorts:
        sections.append(
            "\n**已命名的群体（可按名称引用，不必重写过滤条件）**："
        )
        for cohort in session.cohorts:
            sections.append(
                f"- 「{cohort.name}」 := filter `{cohort.filters}`，n={cohort.row_count}"
            )

    if session.chart_anchors:
        sections.append("\n**已渲染的图表 anchor（不要重复绘制，引用即可）**：")
        for anchor in session.chart_anchors:
            sections.append(f"- {anchor}")

    default_scope = _default_followup_scope(session.cohorts, follow_up_question)
    if default_scope is not None:
        sections.append("\n**当前追问默认作用域（强约束）**：")
        sections.append(
            "追问包含指代词且未明确要求全量分析；生成 Plan 时，"
            "必须在加载数据后先应用以下过滤条件，再计算新的排序、聚合或指标："
        )
        sections.append(f"- filter `{default_scope.filters}`，n={default_scope.row_count}")
        sections.append(
            "不要静默回退到全表；只有当该过滤条件无法在当前表中执行时，"
            "才说明限制并拒绝或改用可核验的替代分析。"
        )

    sections.append(
        "\n请基于上述上下文回答下面的追问。"
        "代词「他们」「这群」「其中」「该地区」「上述地区」「这个国家/地区」等"
        "优先解析为已命名群体或上一轮最重要发现中的实体范围；"
        "若上一轮发现是按某维度排名/Top1（例如美国地区贡献首位），"
        "追问必须先沿用该实体过滤后再分析新指标，除非用户明确要求全量；"
        "如果追问涉及新的维度，按通常方式生成新的 Plan。"
    )
    sections.append(f"\n**追问**：{follow_up_question.strip()}")
    return "\n".join(sections)


def _default_followup_scope(
    cohorts: list[CohortDef], follow_up_question: str
) -> CohortDef | None:
    if not cohorts:
        return None
    question = follow_up_question.strip()
    if not question:
        return None
    if any(term in question for term in _WHOLE_DATASET_TERMS):
        return None
    if not any(term in question for term in _SCOPED_REFERENCE_TERMS):
        return None

    latest_turn = max(cohort.introduced_in_turn for cohort in cohorts)
    for cohort in cohorts:
        if cohort.introduced_in_turn == latest_turn:
            return cohort
    return cohorts[-1]


def _render_findings(findings: list[Finding]) -> str:
    """Numbered list. We trim each detail so the prompt stays compact —
    the planner only needs the *gist* of prior findings, not the full
    paragraph."""

    lines: list[str] = []
    for idx, finding in enumerate(findings, start=1):
        title = finding.title.strip()
        detail = finding.detail.strip().replace("\n", " ")
        if len(detail) > 160:
            detail = detail[:157] + "…"
        lines.append(f"{idx}. {title} —— {detail}")
    return "\n".join(lines)


def _refusal_prelude(session: Session, follow_up_question: str) -> str:
    """Static prelude used when the parent was a refusal.

    `docs/session-state.md` §5 is unambiguous: a refused parent locks
    the session into the canonical refusal narrative — there's no path
    from "we couldn't analyze that" to "let me try harder".
    """

    return (
        "上一轮分析无法基于现有数据完成；本次追问也将沿用同样的拒答理由。\n"
        f"原始问题：{session.original_question.strip()}\n"
        f"追问：{follow_up_question.strip()}\n"
        "请按拒答口径礼貌回应，不要尝试重新分析。"
    )
