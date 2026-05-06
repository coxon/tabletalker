"""看板：钉住卡片、分组、分享、订阅。

使用 SQLite 真实持久化（db/storage.py）。
首次启动空库时返回 mock 数据兜底。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import storage

router = APIRouter()


class PinRequest(BaseModel):
    message_id: str | None = None
    dashboard_id: str | None = None  # None=新建
    title: str | None = None
    annotation: str | None = None
    chart_data: dict | None = None
    kind: str = "bars"
    source_conv_id: str | None = None


class ShareRequest(BaseModel):
    dashboard_id: str
    permission: str = "view"  # view / edit / chat


class SubscriptionRequest(BaseModel):
    dashboard_id: str
    cron: str
    channel: str = "email"  # email / feishu
    target: str


@router.get("/")
async def list_dashboards():
    """所有看板列表。空库时返回 mock 兜底（让前端 demo 不空白）。"""
    rows = storage.list_dashboards()
    if not rows:
        from agent.mock import MOCK_DASHBOARDS
        return {"dashboards": MOCK_DASHBOARDS, "_source": "mock"}
    return {"dashboards": rows, "_source": "db"}


@router.get("/{dashboard_id}")
async def get_dashboard(dashboard_id: str):
    """看板详情（含 cards）。"""
    d = storage.get_dashboard(dashboard_id)
    if d:
        return d
    # 兜底：从 mock 找
    from agent.mock import MOCK_DASHBOARDS
    for x in MOCK_DASHBOARDS:
        if x["id"] == dashboard_id:
            return x
    raise HTTPException(404, "dashboard not found")


@router.post("/pin")
async def pin_to_dashboard(req: PinRequest):
    """把一条消息"钉"到看板。

    - dashboard_id=null → 新建一个看板再加卡片
    - dashboard_id=有值 → 加到已有看板
    """
    dashboard_id = req.dashboard_id
    if not dashboard_id:
        title = req.title or "未命名看板"
        dashboard_id = storage.create_dashboard(
            title=title,
            owner="巧玲",
            source_conv_id=req.source_conv_id,
        )

    card_id = storage.add_card(
        dashboard_id=dashboard_id,
        message_id=req.message_id,
        title=req.title or "卡片",
        kind=req.kind,
        chart_data=req.chart_data,
        annotation=req.annotation or "",
    )
    return {
        "ok": True,
        "dashboard_id": dashboard_id,
        "card_id": card_id,
        "pinned_at": datetime.utcnow().isoformat() + "Z",
    }


@router.delete("/{dashboard_id}")
async def delete_dashboard(dashboard_id: str):
    storage.delete_dashboard(dashboard_id)
    return {"ok": True, "id": dashboard_id}


@router.post("/share")
async def share_dashboard(req: ShareRequest):
    return {
        "ok": True,
        "share_token": f"share_{uuid.uuid4().hex[:16]}",
        "url": f"http://table-talker.example.com/share/{uuid.uuid4().hex[:16]}",
        "permission": req.permission,
    }


@router.post("/subscribe")
async def subscribe(req: SubscriptionRequest):
    return {
        "ok": True,
        "subscription_id": f"sub_{uuid.uuid4().hex[:10]}",
        "next_run": "2026-05-04T09:00:00Z",
    }
