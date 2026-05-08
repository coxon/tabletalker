"""多模型 A/B 演示接口。

同一个问题，5 个国产模型并行回答，前端并排展示对比。
Mock 模式下用预设差异化答案；真实模式下并行调真模型。
"""
from __future__ import annotations

import asyncio
import os
import random
import time
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class MultiModelRequest(BaseModel):
    question: str
    models: list[str] | None = None
    mode: str = "business"


# Mock 答案库（演示用，差异化体现各模型"特点"）
MOCK_MODEL_ANSWERS = {
    "aliyun/qwen3.6-plus": {
        "style": "balanced",
        "answer": "华南区 Q1 同比下滑 12%，主因是 BU-3 的客户经理流失（−18%）拖累签单链路。建议本季度优先稳定 BU-3 团队、并将渠道激励向直销倾斜。",
        "latency_ms": 4200, "tokens": 156, "characteristics": "稳健、商业语言自然、可直接给老板看",
    },
    "aliyun/deepseek-v3.2": {
        "style": "analytical",
        "answer": "华南 Q1 销售下滑 12%（-152万）。归因分析：BU-3 贡献度从 32%→22%（-10pp），相关性 r=0.81。建议：稳定 BU-3、调整渠道结构、监控 2026-01 突变点的延续影响。",
        "latency_ms": 3100, "tokens": 142, "characteristics": "数据精准、含统计量、适合分析师",
    },
    "aliyun/kimi-k2.5": {
        "style": "verbose",
        "answer": "经过对华南区 Q1 销售数据的详细分析，我们发现整体环比下滑 12 个百分点，从 1268 万降至 1116 万。核心原因可以归结为以下几个方面：(1) BU-3 团队的客户经理流失率达到 18%，造成签单链路断裂；(2) 资深客户经理 Top3 在 2026-01 同期离职形成时间窗口冲击；(3) 财务预算偏差 +15% 主因留任奖金和招聘外包，形成短期成本压力。综合建议：本季度优先稳定 BU-3 团队，配合渠道激励向直销倾斜。",
        "latency_ms": 5800, "tokens": 245, "characteristics": "细节丰富、长上下文友好、适合写报告",
    },
    "aliyun/MiniMax-M2.5": {
        "style": "concise",
        "answer": "下滑 12% 主因 BU-3 客户经理流失。建议：稳定 BU-3、调整激励。",
        "latency_ms": 2400, "tokens": 38, "characteristics": "简洁直接、适合 chatbot 一句话回复",
    },
    "aliyun/glm-5": {
        "style": "structured",
        "answer": "【现象】华南 Q1 销售 -12% YoY\n【根因】① BU-3 流失率 18% ② 客户经理 Top3 离职 ③ 渠道结构失衡\n【建议】① 稳定 BU-3 团队 ② 调整激励政策 ③ 监控延续影响",
        "latency_ms": 3600, "tokens": 98, "characteristics": "结构化、用 emoji 和列表、适合 PPT 摘抄",
    },
}


@router.post("/compare")
async def multi_model_compare(req: MultiModelRequest):
    """5 模型并行回答同一个问题。"""
    is_mock = os.getenv("MOCK_MODE", "false").lower() == "true"
    models = req.models or list(MOCK_MODEL_ANSWERS.keys())

    if is_mock:
        # 模拟并行调用，加 0.3-0.6s 延迟做出"真在跑"的感觉
        await asyncio.sleep(0.3 + random.random() * 0.3)
        results = []
        for m in models:
            data = MOCK_MODEL_ANSWERS.get(m, MOCK_MODEL_ANSWERS["aliyun/qwen3.6-plus"])
            # 给每个模型加入小幅随机抖动
            results.append({
                "model": m,
                "answer": data["answer"],
                "style": data["style"],
                "characteristics": data["characteristics"],
                "latency_ms": data["latency_ms"] + random.randint(-200, 300),
                "tokens": data["tokens"] + random.randint(-5, 10),
                "agreement_score": round(random.uniform(0.78, 0.96), 2),
                "ok": True,
            })
        # 一致性总评（5 答案的语义相似度均值）
        consistency = round(sum(r["agreement_score"] for r in results) / len(results), 3)
        return {
            "question": req.question,
            "models_used": models,
            "results": results,
            "consistency_score": consistency,
            "winner": "aliyun/qwen3.6-plus",
            "winner_reason": "综合考虑准确性、可读性、商业语言自然度",
            "_mock": True,
        }

    # 真实模式：并行调 5 模型
    from llm.adapter import chat_complete

    async def call_one(model: str):
        t0 = time.time()
        try:
            ans = await chat_complete(
                messages=[{"role": "user", "content": req.question}],
                model_override=model, max_tokens=300,
            )
            return {"model": model, "answer": ans, "latency_ms": int((time.time() - t0) * 1000), "ok": True}
        except Exception as e:
            return {"model": model, "error": str(e)[:200], "latency_ms": int((time.time() - t0) * 1000), "ok": False}

    results = await asyncio.gather(*[call_one(m) for m in models])
    return {"question": req.question, "models_used": models, "results": results, "_mock": False}


@router.get("/models")
async def list_models():
    """所有可用模型清单 + 描述。"""
    from llm.adapter import list_available_models
    return {
        "models": [
            {"name": m, **MOCK_MODEL_ANSWERS.get(m, {"characteristics": ""})}
            for m in list_available_models()
        ],
    }
