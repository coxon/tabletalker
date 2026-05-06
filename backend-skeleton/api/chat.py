"""对话流式接口（SSE）。

设计稿 chat.jsx 直接对接此接口。事件协议：
  trace_step(running) -> trace_step(done)  ×14
  answer_chunk × N（流式 typewriter）
  chart × M
  insight × K
  citation × 1
  followups × 1
  done × 1
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from agent.orchestrator import run_agent
from agent.mock import mock_stream
from api.cache import cache_enabled, is_cached, replay_cached

router = APIRouter()


@router.post("/stream")
async def chat_stream(request: Request):
    """SSE 流式对话接口。

    用 raw Request 接收，绕过 Pydantic 严格校验——只要是合法 JSON 就接。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    session_id = body.get("session_id") or f"sess_{uuid.uuid4().hex[:8]}"
    message_id = f"msg_{uuid.uuid4().hex[:10]}"
    question = (body.get("question") or "").strip() or "（空问题）"
    mode = body.get("mode") if body.get("mode") in ("business", "expert") else "business"
    dataset_hint = body.get("dataset_hint")

    async def event_gen() -> AsyncGenerator[dict, None]:
        try:
            # ↓↓↓ 优化 #1：演示问题缓存预热（命中即秒回）
            # 命中：~3 秒内回放完整 trace + chart + answer
            # 未命中：穿透到真实 LLM 路径
            if cache_enabled() and is_cached(question):
                async for ev in replay_cached(question):
                    yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False)}
                return

            # Mock 模式：直接返回与 design-source/data.js 一致的演示数据
            if os.getenv("MOCK_MODE", "false") == "true":
                async for ev in mock_stream(question, mode, message_id):
                    yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False)}
                return

            # 真实模式：跑 Agent
            async for ev in run_agent(
                question=question,
                mode=mode,
                session_id=session_id,
                message_id=message_id,
                dataset_hint=dataset_hint,
            ):
                yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False)}

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e), "message_id": message_id}, ensure_ascii=False),
            }
        finally:
            yield {
                "event": "done",
                "data": json.dumps({"type": "done", "message_id": message_id}, ensure_ascii=False),
            }

    return EventSourceResponse(event_gen())


@router.get("/conversations")
async def list_conversations():
    """会话历史列表（演示返回与 data.js 一致的 7 条）。"""
    from agent.mock import MOCK_HISTORY
    return {"conversations": MOCK_HISTORY}


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """单个会话详情（用于左侧栏点击切换）。"""
    from agent.mock import MOCK_CONVERSATIONS
    if conv_id not in MOCK_CONVERSATIONS:
        return {"error": "not found"}
    return MOCK_CONVERSATIONS[conv_id]


@router.get("/citation/{message_id}")
async def get_citation(message_id: str):
    """引用溯源详情（点击消息底部"引用"展开）。"""
    from agent.mock import MOCK_CITATION
    return MOCK_CITATION
