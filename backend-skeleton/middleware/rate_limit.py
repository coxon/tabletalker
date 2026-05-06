"""Rate limit 限流中间件（slowapi 实现）。

按 IP 限流，对 /api/chat/stream / /api/eval/run 这种贵接口默认 30/min。
评委 token / admin 自动豁免。
"""
from __future__ import annotations

import os
from typing import Callable

from fastapi import Request

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address
    SLOWAPI_AVAILABLE = True
except ImportError:
    SLOWAPI_AVAILABLE = False
    Limiter = None
    RateLimitExceeded = None
    _rate_limit_exceeded_handler = None
    get_remote_address = None


def _ratelimit_key(request: Request) -> str:
    """限流 key：评委 token 走单独配额；其他按 IP。"""
    judge = request.headers.get("x-judge-token")
    if judge:
        return f"judge:{judge[:8]}"
    auth = request.headers.get("authorization")
    if auth and auth.startswith("Bearer "):
        return f"jwt:{auth[7:][:8]}"
    return f"ip:{get_remote_address(request)}" if get_remote_address else "anon"


def install_rate_limit(app):
    """挂载到 FastAPI app。"""
    if not SLOWAPI_AVAILABLE:
        # 没装 slowapi 时降级为空的装饰器，不影响主流程
        class _NoLimiter:
            def limit(self, *a, **kw):
                return lambda f: f
        app.state.limiter = _NoLimiter()
        return app.state.limiter

    limiter = Limiter(key_func=_ratelimit_key, default_limits=["120/minute", "2000/hour"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    return limiter


# 业务用法（在 api/chat.py 等里）：
#   from middleware.rate_limit import get_limiter
#   limiter = get_limiter()
#   @limiter.limit("30/minute")
#   @router.post("/stream")
#   async def chat_stream(...): ...

def get_limiter():
    """从 app.state 取 limiter（若未初始化返回 noop）。"""
    from fastapi import FastAPI
    # 这里返回一个 placeholder；实际取要在 app context 内
    if not SLOWAPI_AVAILABLE:
        class _Noop:
            def limit(self, *a, **kw):
                return lambda f: f
        return _Noop()
    return None  # 实际由 app.state.limiter 提供，业务代码用 request.app.state.limiter
