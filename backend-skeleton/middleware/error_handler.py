"""统一错误处理 - 让所有 500 都包含 request_id 和友好的 JSON 结构。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException


def install_error_handlers(app: FastAPI):
    """挂载到 app 启动时。"""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", "-")
        body = None
        try:
            body = (await request.body()).decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        logger.warning(f"[{rid}] 422 on {request.url.path}: errors={exc.errors()} body={body}")
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "code": "validation_error",
                "message": "请求参数校验失败",
                "request_id": rid,
                "detail": exc.errors(),
                "raw_body": body,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        rid = getattr(request.state, "request_id", "-")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "code": f"http_{exc.status_code}",
                "message": str(exc.detail),
                "request_id": rid,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", "-")
        logger.exception(f"[{rid}] 500 on {request.url.path}: {type(exc).__name__}: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "code": "internal_error",
                "message": f"{type(exc).__name__}: {exc}",
                "request_id": rid,
            },
        )
