"""Table-Talker FastAPI 主入口。

启动方式：
    cd backend-skeleton
    pip install -r requirements.txt --break-system-packages
    cp .env.example .env  # 改 QWEN_API_KEY
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

文档：http://localhost:8000/docs
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

load_dotenv()

from api.chat import router as chat_router  # noqa: E402
from api.datasets import router as datasets_router  # noqa: E402
from api.eval import router as eval_router  # noqa: E402
from api.dashboard import router as dashboard_router  # noqa: E402
from api.report import router as report_router  # noqa: E402
from api.health import router as health_router  # noqa: E402
from api.auth import router as auth_router  # noqa: E402
from api.metrics import router as metrics_router  # noqa: E402
from api.multi_model import router as multi_model_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Table-Talker 后端启动")
    logger.info(f"Mock 模式: {os.getenv('MOCK_MODE', 'false')}")
    logger.info(f"LLM 提供方: {os.getenv('LLM_PROVIDER', 'qwen')}")

    # 离线 schema 加载
    schemas_path = Path(os.getenv("SCHEMAS_FILE", "./schemas.json"))
    if schemas_path.exists():
        logger.info(f"已加载 schema 缓存：{schemas_path}")
    else:
        logger.warning(f"schema 缓存不存在：{schemas_path}（首次运行需 `python tools/extract_schema.py`）")

    # 初始化 SQLite 持久化
    try:
        from db.storage import init_db
        init_db()
        logger.info("SQLite 表已就绪（dashboards / dashboard_cards / reports）")
    except Exception as e:
        logger.warning(f"SQLite 初始化失败：{e}")

    yield
    logger.info("Table-Talker 后端关闭")


app = FastAPI(
    title="Table-Talker API",
    description="对话式企业数据分析与洞察平台",
    version="1.0.0",
    lifespan=lifespan,
)

# 中间件：请求 ID + 访问日志 + Rate limit + 错误处理
from middleware.request_id import RequestIDMiddleware  # noqa: E402
from middleware.error_handler import install_error_handlers  # noqa: E402
from middleware.rate_limit import install_rate_limit  # noqa: E402

app.add_middleware(RequestIDMiddleware)
install_rate_limit(app)
install_error_handlers(app)

# CORS（前端可能在不同端口）
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由挂载
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(datasets_router, prefix="/api/datasets", tags=["datasets"])
app.include_router(eval_router, prefix="/api/eval", tags=["eval"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(report_router, prefix="/api/report", tags=["report"])
app.include_router(metrics_router, prefix="/api/metrics", tags=["metrics"])
app.include_router(multi_model_router, prefix="/api/multi-model", tags=["multi-model"])

# 可选：静态托管前端（生产部署时启用）
frontend_dist = Path("./frontend")
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8000)), reload=True)
