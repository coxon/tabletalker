"""鉴权接口：账密登录 + 评委 token 验证 + 当前用户。

V0：内置演示账号（admin / 巧玲 / 评委）；生产需对接 SSO/LDAP。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.auth import (
    current_user_optional,
    current_user_required,
    is_judge_token,
    issue_token,
)

router = APIRouter()


# 演示账号（生产连 LDAP/OIDC，这里只是 mock）
DEMO_USERS = {
    "qiaoling@asiainfo.com": {"password": "qiaoling123", "role": "power_user", "name": "巧玲"},
    "admin@asiainfo.com": {"password": "admin123", "role": "tenant_admin", "name": "管理员"},
    "judge@asiainfo.com": {"password": "judge123", "role": "judge", "name": "评委"},
}


class LoginRequest(BaseModel):
    email: str
    password: str


class JudgeTokenRequest(BaseModel):
    token: str


@router.post("/login")
async def login(req: LoginRequest):
    """账密登录，返回 JWT token。"""
    user = DEMO_USERS.get(req.email)
    if not user or user["password"] != req.password:
        raise HTTPException(401, "账号或密码错误")
    token = issue_token(req.email, role=user["role"], extra={"name": user["name"]})
    return {
        "ok": True,
        "token": token,
        "user": {"email": req.email, "role": user["role"], "name": user["name"]},
    }


@router.post("/judge-login")
async def judge_login(req: JudgeTokenRequest):
    """评委专用：用 magic-link token 一键进入评测页。"""
    if not is_judge_token(req.token):
        raise HTTPException(401, "评委 token 无效")
    token = issue_token("judge", role="judge", extra={"name": "评委"})
    return {
        "ok": True,
        "token": token,
        "user": {"email": "judge", "role": "judge", "name": "评委"},
        "redirect": "/eval",
    }


@router.get("/me")
async def me(user: dict = Depends(current_user_required)):
    """当前登录用户。"""
    return {"user": user}


@router.get("/me-or-anon")
async def me_or_anon(user: dict | None = Depends(current_user_optional)):
    """非强制鉴权（看板分享等场景）。"""
    return {"user": user, "anonymous": user is None}


@router.post("/logout")
async def logout():
    """logout 是无状态的：客户端删 token 即可。"""
    return {"ok": True, "message": "已登出（请前端清除 localStorage 中的 token）"}
