"""Agent 主流程编排（14 步）。

每一步以 SSE 事件推送：先 running 后 done。
对外暴露：
  - run_agent(question, mode, ...) 流式（生产）
  - run_agent_simple(question, ...) 阻塞返回 dict（评测）
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from loguru import logger

# 14 步定义（与设计稿 data.js traceSteps 一一对应）
STEPS = [
    {"i": 1, "name": "接收用户问题", "group": "感知", "detail_tpl": "解析自然语言 + session 上下文"},
    {"i": 2, "name": "加载可用能力", "group": "感知", "detail_tpl": "工具集 8 项 · 数据集 {n_ds} 张候选"},
    {"i": 3, "name": "GraphRAG 社区检索", "group": "理解", "detail_tpl": "top-k=5 业务社区摘要", "badge": "GraphRAG"},
    {"i": 4, "name": "规划下一步动作", "group": "理解", "detail_tpl": "判定任务类型"},
    {"i": 5, "name": "选择执行能力", "group": "理解", "detail_tpl": "Router 选定数据集"},
    {"i": 6, "name": "实例语义解析", "group": "理解", "detail_tpl": "实体 + 指标 + 时间维度"},
    {"i": 7, "name": "TTL 推理与补全", "group": "理解", "detail_tpl": "业务术语 → 字段映射", "badge": "TTL"},
    {"i": 8, "name": "SQL 生成 · 尝试 1", "group": "执行", "detail_tpl": "首次生成", "badge": "Codegen"},
    {"i": 9, "name": "SQL 生成 · 尝试 2", "group": "执行", "detail_tpl": "（如需）反思修正", "optional": True},
    {"i": 10, "name": "SQL 生成 · 尝试 3", "group": "执行", "detail_tpl": "—", "optional": True},
    {"i": 11, "name": "SQL 生成 · 尝试 4", "group": "执行", "detail_tpl": "—", "optional": True},
    {"i": 12, "name": "执行 SQL（DuckDB）", "group": "执行", "detail_tpl": "扫描数据 → 返回聚合"},
    {"i": 13, "name": "检查查询结果", "group": "校验", "detail_tpl": "Critic：行数/空值/数值合理性"},
    {"i": 14, "name": "组装结论 + 选图 + 引用", "group": "输出", "detail_tpl": "选图 + 引用 + 异常洞察"},
]


async def run_agent(
    question: str,
    mode: str,
    session_id: str,
    message_id: str,
    dataset_hint: str | None = None,
) -> AsyncIterator[dict]:
    """生产路径（接 LLM）。当前为骨架版，逐步替换为真实实现。"""
    from agent.steps import (
        step_router,
        step_graphrag,
        step_ttl,
        step_codegen_with_retry,
        step_sandbox_exec,
        step_critic,
        step_chart_pick,
        step_summarize,
        step_anomaly,
    )

    t_start = time.time()
    n_ds = 6  # TODO: 从 datasets 服务取
    skipped: set[int] = set()

    async def emit_step(idx: int, status: str, **extra):
        s = STEPS[idx - 1]
        return {
            "type": "trace_step",
            "i": s["i"],
            "name": s["name"],
            "group": s["group"],
            "badge": s.get("badge"),
            "status": status,
            **extra,
        }

    # ====== Step 1-2 ======
    yield await emit_step(1, "running", detail="解析自然语言")
    await asyncio.sleep(0.05)
    yield await emit_step(1, "done", duration_ms=12)

    yield await emit_step(2, "running", detail=f"工具集 8 项 · 数据集 {n_ds} 张候选")
    await asyncio.sleep(0.03)
    yield await emit_step(2, "done", duration_ms=28)

    # ====== Step 3 GraphRAG ======
    yield await emit_step(3, "running")
    graph_hits = await step_graphrag(question)
    yield await emit_step(3, "done", duration_ms=340, detail=f"命中 {len(graph_hits)} 个业务社区")

    # ====== Step 4-5 Router ======
    yield await emit_step(4, "running")
    yield await emit_step(4, "done", duration_ms=80, detail="判定为多维归因任务")

    yield await emit_step(5, "running")
    selected_datasets = await step_router(question, dataset_hint=dataset_hint)
    yield await emit_step(5, "done", duration_ms=22, detail=f"选定：{', '.join(selected_datasets)}")

    # ====== Step 6 实体解析 ======
    yield await emit_step(6, "running")
    entities = await step_ttl(question, "entities")
    yield await emit_step(6, "done", duration_ms=46, detail=f"实体：{entities}")

    # ====== Step 7 TTL 补全 ======
    yield await emit_step(7, "running")
    semantic = await step_ttl(question, "semantic")
    yield await emit_step(7, "done", duration_ms=71, detail=str(semantic)[:80])

    # ====== Step 8-11 SQL 重试 ======
    sql, attempts = await step_codegen_with_retry(question, selected_datasets, semantic)
    for i in range(1, 5):
        if i <= attempts:
            yield await emit_step(7 + i, "running")
            yield await emit_step(
                7 + i, "done",
                duration_ms=200 if i > 1 else 612,
                detail=f"{'校验通过' if i == attempts else '校验失败，反思修正'}",
            )
        else:
            yield await emit_step(7 + i, "skip", duration_ms=0, detail="—")

    # ====== Step 12 执行 ======
    yield await emit_step(12, "running")
    df, exec_err = await step_sandbox_exec(sql, selected_datasets)
    yield await emit_step(12, "done", duration_ms=1340, detail=f"返回 {len(df) if df is not None else 0} 行")

    # ====== Step 13 Critic ======
    yield await emit_step(13, "running")
    critic_ok = await step_critic(df)
    yield await emit_step(13, "done", duration_ms=122, detail="行数/空值/数值合理性 OK" if critic_ok else "结果异常，已标记")

    # ====== Step 14 组装 ======
    yield await emit_step(14, "running")

    # ↓↓↓ 优化 #4：chart_pick 和 summary 都是 LLM 调用、相互不依赖，并行跑省 5-15s
    # anomaly 是纯 CPU（IQR/Z-Score/CUSUM），先同步跑掉，让 summary 能拿到 insights 文本
    insights = await step_anomaly(df)
    chart_task = asyncio.create_task(step_chart_pick(df, question))
    # summary 不需要 charts（看 SUMM_PROMPT_BIZ，只用到 question/data_summary/insights）
    summary_task = asyncio.create_task(
        step_summarize(question, df, mode=mode, charts=[], insights=insights)
    )

    # 等 chart_pick：UI 顺序要求 chart 事件先于 answer 流出
    charts = await chart_task
    for ch in charts:
        yield {"type": "chart", **ch}

    for ins in insights:
        yield {"type": "insight", **ins}

    # 输出引用
    yield {
        "type": "citation",
        "datasets": selected_datasets,
        "columns": df.columns.tolist() if df is not None else [],
        "sql": sql,
        "rows": len(df) if df is not None else 0,
        "sample": df.head(3).to_dict(orient="records") if df is not None else [],
    }

    # 输出 followups（双模式）
    yield {
        "type": "followups",
        "business": ["进一步对比同行", "生成完整复盘报告", "追因到 BU 维度"],
        "expert": ["改 SQL 加 channel 维度", "导出 Notebook", "下钻到客户级"],
    }

    # 等 summary（多数情况下 chart_pick 比 summary 慢，summary 此时已就绪 → 等待 ~0s）
    answer_text = await summary_task
    for chunk in _chunk_text(answer_text, 6):
        yield {"type": "answer_chunk", "mode": mode, "text": chunk}
        await asyncio.sleep(0.02)

    yield await emit_step(14, "done", duration_ms=410)

    yield {
        "type": "complete",
        "message_id": message_id,
        "total_ms": int((time.time() - t_start) * 1000),
    }


def _chunk_text(s: str, size: int = 6):
    for i in range(0, len(s), size):
        yield s[i:i + size]


async def run_agent_simple(question: str, session_id: str | None = None) -> dict:
    """阻塞式跑 Agent，把所有事件聚合成一个 dict（用于批量评测）。"""
    text_chunks = []
    charts = []
    insights = []
    citation = None

    async for ev in run_agent(question, mode="business", session_id=session_id or "eval", message_id="eval"):
        if ev["type"] == "answer_chunk":
            text_chunks.append(ev["text"])
        elif ev["type"] == "chart":
            charts.append(ev)
        elif ev["type"] == "insight":
            insights.append(ev)
        elif ev["type"] == "citation":
            citation = ev

    return {
        "text": "".join(text_chunks),
        "charts": charts,
        "insights": insights,
        "citation": citation,
    }
