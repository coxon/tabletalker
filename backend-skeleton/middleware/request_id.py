"""请求 ID + 访问日志中间件。

每个请求挂一个唯一 X-Request-ID，便于跨服务追踪：
  - 进入时：生成或读取上游传来的 X-Request-ID
  - 处理时：注入到 request.state.request_id（业务可读）
  - 响应头：附带 X-Request-ID 给客户端
  - 日志：每条请求日志带 request_id
"""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

# 跨 async 任务安全的请求 ID 上下文（业务代码可以 import 取）
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 接受上游传入或自生成
        rid = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
        token = request_id_ctx.set(rid)
        request.state.request_id = rid

        t0 = time.time()
        try:
            response = await call_next(request)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            logger.bind(request_id=rid).error(
                f"⚠ {request.method} {request.url.path} → 500 · {ms}ms · {type(exc).__name__}: {exc}"
            )
            request_id_ctx.reset(token)
            raise
        ms = int((time.time() - t0) * 1000)

        # 加响应头
        response.headers["X-Request-ID"] = rid
        # 性能日志（5xx 用 error 级，其他 info）
        sc = response.status_code
        log_fn = logger.error if sc >= 500 else (logger.warning if sc >= 400 else logger.info)
        log_fn(f"[{rid}] {request.method} {request.url.path} → {sc} · {ms}ms")

        request_id_ctx.reset(token)
        return response


def get_request_id() -> str:
    """业务代码取当前请求 ID。"""
    return request_id_ctx.get()
