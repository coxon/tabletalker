"""JWT 鉴权骨架 + 评委 token 兜底。

V0：MVP 用 magic-link token（评委账号在 .env 配 JUDGE_TOKENS=...）。
V1：后续接 OIDC / SSO，JWT signed by HS256。
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from loguru import logger

try:
    import jwt
except ImportError:
    jwt = None

JWT_SECRET = os.getenv("JWT_SECRET", "table-talker-dev-secret-change-in-prod")
JWT_ALGO = "HS256"
JWT_EXP_MINUTES = int(os.getenv("JWT_EXP_MINUTES", "60"))


# ============ JWT 签发与校验 ============

def issue_token(user_id: str, role: str = "user", extra: dict | None = None) -> str:
    """业务调用：登录成功后签发 JWT。"""
    if jwt is None:
        raise RuntimeError("PyJWT 未安装")
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int((datetime.utcnow() + timedelta(minutes=JWT_EXP_MINUTES)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict | None:
    if jwt is None:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        logger.warning("JWT 已过期")
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT 无效：{e}")
    return None


# ============ 评委 token 白名单 ============

def is_judge_token(token: str) -> bool:
    """评委专用 token，写在 .env JUDGE_TOKENS=token1,token2"""
    allowed = os.getenv("JUDGE_TOKENS", "").split(",")
    return bool(token) and token.strip() in [a.strip() for a in allowed if a.strip()]


# ============ FastAPI 依赖：从 header 取 user ============

def current_user_optional(
    authorization: Optional[str] = Header(None),
    x_judge_token: Optional[str] = Header(None),
) -> dict | None:
    """非强制鉴权：能识别就识别，识别不出 None。

    用于评测页等"评委可访问"接口。
    """
    # 评委 token 优先
    if x_judge_token and is_judge_token(x_judge_token):
        return {"sub": "judge", "role": "judge", "via": "judge-token"}

    # JWT
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        payload = decode_token(token)
        if payload:
            payload["via"] = "jwt"
            return payload
    return None


def current_user_required(user: dict | None = Depends(current_user_optional)) -> dict:
    """强制鉴权：未登录返回 401。"""
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或 token 无效")
    return user


def require_admin(user: dict = Depends(current_user_required)) -> dict:
    """要求 admin 角色。"""
    if user.get("role") not in ("admin", "tenant_admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    return user
