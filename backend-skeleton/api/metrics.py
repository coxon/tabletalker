"""指标库 API · Metric Layer。

让前端 / Agent 在 NL→SQL 之前先查询指标库，确保口径一致。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from metrics_layer.registry import (
    categories,
    get_metric,
    list_metrics,
    search_metrics,
    stats,
)

router = APIRouter()


@router.get("/")
async def list_all(category: str | None = Query(None)):
    """列出所有指标（可按 category 过滤）。"""
    metrics = list_metrics(category)
    return {
        "total": len(metrics),
        "categories": categories(),
        "metrics": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "category": m.category,
                "type": m.type,
                "unit": m.unit,
                "description": m.description,
                "datasets": m.datasets,
                "synonyms": m.synonyms,
                "owner": m.owner,
            }
            for m in metrics
        ],
    }


@router.get("/stats")
async def get_stats():
    """指标库统计信息（用于看板首页摘要）。"""
    return stats()


@router.get("/search")
async def search(q: str, top_k: int = 5):
    """模糊搜索指标。"""
    matched = search_metrics(q, top_k)
    return {
        "query": q,
        "results": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "category": m.category,
                "unit": m.unit,
                "synonyms": m.synonyms,
                "sql_preview": m.sql_expression[:80],
            }
            for m in matched
        ],
    }


@router.get("/{metric_name}")
async def get_one(metric_name: str):
    """指标详情（含 SQL、口径、依赖）。"""
    m = get_metric(metric_name)
    if not m:
        raise HTTPException(404, f"指标 {metric_name} 未注册到指标库")
    return {
        "name": m.name,
        "display_name": m.display_name,
        "category": m.category,
        "type": m.type,
        "unit": m.unit,
        "description": m.description,
        "datasets": m.datasets,
        "sql_expression": m.sql_expression,
        "rendered_sql": m.render_sql(),
        "filter": m.filter,
        "synonyms": m.synonyms,
        "owner": m.owner,
        "freshness_sla": m.freshness_sla,
        "depends_on": m.depends_on,
        "thresholds": m.thresholds,
    }
