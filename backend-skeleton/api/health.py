"""健康检查与版本信息。"""
import os
from datetime import datetime

from fastapi import APIRouter

from llm.adapter import health_check, list_available_models

router = APIRouter()


@router.get("/health")
async def health():
    """轻量健康检查：不调 LLM，只返回配置摘要。"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "mock_mode": os.getenv("MOCK_MODE", "false") == "true",
        "llm_base_url": os.getenv("LLM_BASE_URL", "https://aigw.asiainfo.com/v1"),
        "models_configured": list_available_models(),
        "ts": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/health/llm")
async def health_llm():
    """深度健康检查：实际调用每个模型 1 次，返回联通状态。

    注意：会消耗 token，不要频繁调用。
    """
    if os.getenv("MOCK_MODE", "false") == "true":
        return {"ok": True, "skipped": "mock mode"}
    return await health_check()
