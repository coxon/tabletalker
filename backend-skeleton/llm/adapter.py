"""LLM Adapter：统一封装亚信 AI 网关，支持 5 个模型路由 + 流式 + 重试容错。

亚信网关：https://aigw.asiainfo.com/v1（OpenAI 兼容协议）
可用模型：
  - aliyun/qwen3.6-plus    （默认主模型）
  - aliyun/deepseek-v3.2   （小模型，Router/Critic）
  - aliyun/kimi-k2.5       （长上下文，报告生成）
  - aliyun/MiniMax-M2.5    （备用 1）
  - aliyun/glm-5           （备用 2）

任务 → 模型映射策略（在 get_model 中可调）：
  - router / critic / summary_short → SMALL（deepseek-v3.2）
  - codegen / summary / default     → DEFAULT（qwen3.6-plus）
  - long_report                     → LONG（kimi-k2.5）
"""
from __future__ import annotations

import os
import time
from typing import AsyncIterator

from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


# ============ 单例 client（统一走网关）============
_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("LLM_API_KEY") or os.getenv("QWEN_API_KEY"),  # 兼容旧名
            base_url=os.getenv("LLM_BASE_URL", "https://aigw.asiainfo.com/v1"),
            # qwen3.6-plus 在 codegen 700+ tokens 输出场景下经常 60-150s，
            # timeout 必须放宽，否则正常完成的请求也会被 client 提前掐断。
            timeout=float(os.getenv("LLM_HTTP_TIMEOUT", "180")),
        )
    return _client


def list_available_models() -> list[str]:
    """返回当前已配置的全部模型清单（来自 .env）。"""
    return [
        os.getenv("LLM_MODEL_DEFAULT", "aliyun/qwen3.6-plus"),
        os.getenv("LLM_MODEL_SMALL", "aliyun/deepseek-v3.2"),
        os.getenv("LLM_MODEL_LONG", "aliyun/kimi-k2.5"),
        os.getenv("LLM_MODEL_FALLBACK", "aliyun/MiniMax-M2.5"),
        os.getenv("LLM_MODEL_FALLBACK_2", "aliyun/glm-5"),
    ]


def get_model(task: str = "default") -> str:
    """根据任务类型路由模型。"""
    DEFAULT = os.getenv("LLM_MODEL_DEFAULT", "aliyun/qwen3.6-plus")
    SMALL = os.getenv("LLM_MODEL_SMALL", "aliyun/deepseek-v3.2")
    LONG = os.getenv("LLM_MODEL_LONG", "aliyun/kimi-k2.5")

    # codegen 实测在亚信网关上：
    #   qwen3.6-plus: 60-90s（输出 700+ tokens）→ 演示太慢
    #   deepseek-v3.2: 8-15s，SQL 质量基本一致
    # 默认走 deepseek 求速度，通过环境变量 LLM_MODEL_CODEGEN 可显式切回 qwen
    CODEGEN = os.getenv("LLM_MODEL_CODEGEN", SMALL)
    # summary 走 SMALL 同理（长上下文还是 LONG，不变）
    SUMMARY = os.getenv("LLM_MODEL_SUMMARY", SMALL)

    routing = {
        # 小任务 → 小模型
        "router": SMALL,
        "critic": SMALL,
        "summary_short": SMALL,
        "intent": SMALL,

        # 主任务 → 速度优先：用 deepseek-v3.2（SMALL）
        "codegen": CODEGEN,
        "summary": SUMMARY,
        "default": DEFAULT,

        # 长任务 → 长上下文模型
        "long_report": LONG,
        "report_outline": LONG,
    }
    return routing.get(task, DEFAULT)


def get_fallback_chain(task: str = "default") -> list[str]:
    """主模型失败时的回退顺序。"""
    primary = get_model(task)
    fallbacks = [
        os.getenv("LLM_MODEL_FALLBACK", "aliyun/MiniMax-M2.5"),
        os.getenv("LLM_MODEL_FALLBACK_2", "aliyun/glm-5"),
    ]
    chain = [primary] + [m for m in fallbacks if m != primary]
    return chain


# ============ 调用封装 ============

class LLMException(Exception):
    pass


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(min=1, max=4),
    retry=retry_if_exception_type(LLMException),
    reraise=True,
)
async def chat_complete(
    messages: list[dict],
    *,
    task: str = "default",
    temperature: float = 0.2,
    max_tokens: int = 2000,
    json_mode: bool = False,
    model_override: str | None = None,
) -> str:
    """非流式补全（用于 Router、Critic、CodeGen 等结构化输出）。

    自动按 fallback_chain 切模型；最后还是失败则抛 LLMException。
    """
    client = get_client()
    chain = [model_override] if model_override else get_fallback_chain(task)

    last_err: Exception | None = None
    for model in chain:
        if not model:
            continue
        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            t0 = time.time()
            logger.debug(f"LLM call: model={model} task={task} json_mode={json_mode}")
            resp = await client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content or ""
            logger.info(f"LLM ok: model={model} task={task} ms={int((time.time()-t0)*1000)} tokens_out={len(content)}")
            return content
        except Exception as e:
            last_err = e
            logger.warning(f"LLM fail: model={model} task={task} err={e}, trying next...")
            continue

    raise LLMException(f"All models failed for task={task}: {last_err}")


async def chat_stream(
    messages: list[dict],
    *,
    task: str = "default",
    temperature: float = 0.2,
    max_tokens: int = 2000,
    model_override: str | None = None,
) -> AsyncIterator[str]:
    """流式补全（用于答案 typewriter 效果）。

    流式不做 fallback 重试（避免吐到一半切模型导致内容割裂）；
    若主模型失败，由调用方降级到非流式。
    """
    client = get_client()
    model = model_override or get_model(task)
    logger.debug(f"LLM stream: model={model} task={task}")

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


# ============ 工具：检查 API 健康 ============

async def health_check() -> dict:
    """快速调一次 API，返回 {"ok": bool, "models_ok": [...], "models_failed": [...]}."""
    results = {"ok": True, "models_ok": [], "models_failed": []}
    for m in list_available_models():
        try:
            resp = await chat_complete(
                messages=[{"role": "user", "content": "say 'ok' in one word"}],
                model_override=m,
                max_tokens=10,
            )
            results["models_ok"].append({"model": m, "echo": resp.strip()[:20]})
        except Exception as e:
            results["models_failed"].append({"model": m, "error": str(e)[:120]})
            results["ok"] = False
    return results
