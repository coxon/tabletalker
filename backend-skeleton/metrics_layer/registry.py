"""指标库（Metric Layer）。

业务指标统一定义、版本控制、口径一致。
对标：dbt Metrics / Cube.dev / LookML / Apache Calcite。

使用：
    from metrics_layer.registry import get_metric, list_metrics, search_metrics

    m = get_metric("GMV")
    print(m.sql_expression)   # → "SUM(amount)"

    # NL 词触发匹配指标
    matched = search_metrics("营收")  # → [Net_Revenue, GMV]
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Metric:
    name: str
    display_name: str
    category: str
    type: str            # additive / ratio / average / count_distinct
    unit: str
    description: str = ""
    datasets: list[str] = None
    sql_expression: str = ""
    filter: Optional[str] = None
    synonyms: list[str] = None
    owner: Optional[str] = None
    freshness_sla: Optional[str] = None
    depends_on: list[str] = None
    thresholds: Optional[dict] = None

    def render_sql(self, where_extra: str = "") -> str:
        """生成可执行 SQL 表达式（含 filter）。"""
        expr = self.sql_expression
        wh = []
        if self.filter:
            wh.append(self.filter)
        if where_extra:
            wh.append(where_extra)
        if wh:
            return f"{expr} -- where: {' AND '.join(wh)}"
        return expr


_REGISTRY: dict[str, Metric] | None = None


def _load() -> dict[str, Metric]:
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY

    p = Path(os.getenv("METRICS_DEFINITIONS_FILE", "./metrics_definitions.json"))
    if not p.exists():
        _REGISTRY = {}
        return _REGISTRY

    raw = json.loads(p.read_text())
    _REGISTRY = {}
    for name, data in raw.get("metrics", {}).items():
        _REGISTRY[name] = Metric(
            name=data.get("name", name),
            display_name=data.get("display_name", name),
            category=data.get("category", ""),
            type=data.get("type", "additive"),
            unit=data.get("unit", ""),
            description=data.get("description", ""),
            datasets=data.get("datasets", []),
            sql_expression=data.get("sql_expression", ""),
            filter=data.get("filter"),
            synonyms=data.get("synonyms", []),
            owner=data.get("owner"),
            freshness_sla=data.get("freshness_sla"),
            depends_on=data.get("depends_on", []),
            thresholds=data.get("thresholds"),
        )
    return _REGISTRY


def get_metric(name: str) -> Optional[Metric]:
    """按 name 查指标（支持 display_name 和 synonyms 模糊匹配）。"""
    reg = _load()
    if name in reg:
        return reg[name]
    # display_name 匹配
    for m in reg.values():
        if m.display_name == name:
            return m
    # 同义词匹配
    for m in reg.values():
        if name in (m.synonyms or []):
            return m
    return None


def list_metrics(category: Optional[str] = None) -> List[Metric]:
    reg = _load()
    if not category:
        return list(reg.values())
    return [m for m in reg.values() if m.category == category]


def search_metrics(query: str, top_k: int = 5) -> List[Metric]:
    """根据用户问题里的关键词模糊匹配可用指标。"""
    reg = _load()
    scored = []
    for m in reg.values():
        score = 0
        # 优先级 3：精确名匹配
        if m.name in query or m.display_name in query:
            score += 10
        # 优先级 2：同义词匹配
        for syn in (m.synonyms or []):
            if syn in query:
                score += 5
                break
        # 优先级 1：description 词命中
        for word in (m.description or "").split():
            if len(word) > 1 and word in query:
                score += 1
        if score > 0:
            scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:top_k]]


def categories() -> dict:
    """返回类别字典（含 icon 和显示名）。"""
    p = Path(os.getenv("METRICS_DEFINITIONS_FILE", "./metrics_definitions.json"))
    if not p.exists():
        return {}
    return json.loads(p.read_text()).get("categories", {})


def stats() -> dict:
    """指标库统计信息。"""
    reg = _load()
    by_cat = {}
    for m in reg.values():
        by_cat[m.category] = by_cat.get(m.category, 0) + 1
    return {
        "total": len(reg),
        "by_category": by_cat,
        "datasets_referenced": list(set(d for m in reg.values() for d in (m.datasets or []))),
    }
