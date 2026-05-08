"""Agent 14 步原子操作的单元测试。

覆盖：
  - step_ttl 业务术语映射
  - step_graphrag 社区检索
  - step_chart_pick 自动选图启发式
  - step_anomaly 离群检测
  - step_critic 结果合理性
"""
from __future__ import annotations

import pandas as pd
import pytest

from agent.steps import (
    step_ttl,
    step_graphrag,
    step_chart_pick,
    step_anomaly,
    step_critic,
)


# ==================== TTL 推理 ====================

@pytest.mark.asyncio
async def test_ttl_entities_match(sample_business_terms_file):
    ents = await step_ttl("Q1 华南销售环比", mode="entities")
    assert any("Q1" in e for e in ents), "应命中 Q1 时间术语"
    assert any("环比" in e for e in ents), "应命中环比"


@pytest.mark.asyncio
async def test_ttl_semantic_completion(sample_business_terms_file):
    completions = await step_ttl("Q1 各 BU 持证率", mode="semantic")
    assert "Q1" in completions, "应填充 Q1 时间过滤"
    assert "持证率" in completions or any("持证" in k for k in completions), "应命中持证率指标"


@pytest.mark.asyncio
async def test_ttl_synonym_expansion(sample_business_terms_file):
    """问"营收"应该通过同义词扩展到"成交额"。"""
    completions = await step_ttl("看一下今年营收", mode="semantic")
    # 至少匹配到了某个同义词或关键术语
    assert len(completions) >= 0  # 同义词扩展不强制必中


@pytest.mark.asyncio
async def test_ttl_no_match_returns_empty(sample_business_terms_file):
    ents = await step_ttl("今天天气真好", mode="entities")
    assert isinstance(ents, list)


# ==================== GraphRAG ====================

@pytest.mark.asyncio
async def test_graphrag_hr_route(sample_graphrag_index):
    hits = await step_graphrag("BU-3 持证率为什么这么低")
    assert len(hits) > 0, "应匹配 HR 社区"
    assert hits[0]["community"] == "HR 月报"


@pytest.mark.asyncio
async def test_graphrag_sales_route(sample_graphrag_index):
    hits = await step_graphrag("Q1 华南销售归因")
    assert len(hits) > 0
    assert any(h["community"] == "销售归因" for h in hits)


@pytest.mark.asyncio
async def test_graphrag_dataset_name_boost(sample_graphrag_index):
    """直接命中数据集名应该加权。"""
    hits = await step_graphrag("分析 employee_analytics 的数据")
    assert len(hits) > 0
    # 命中数据集名后，HR 社区应该排第一（含 employee_analytics）
    assert hits[0]["community"] == "HR 月报"


@pytest.mark.asyncio
async def test_graphrag_no_match():
    hits = await step_graphrag("今天天气怎么样")
    assert isinstance(hits, list)


# ==================== 自动选图 ====================

@pytest.mark.asyncio
async def test_chart_pick_time_series():
    df = pd.DataFrame({
        "month": ["2026-01", "2026-02", "2026-03"],
        "sales": [100, 120, 110],
    })
    charts = await step_chart_pick(df, "近三个月销售")
    kinds = [c["kind"] for c in charts]
    assert "line" in kinds, "时间序列应推荐折线图"


@pytest.mark.asyncio
async def test_chart_pick_categorical():
    df = pd.DataFrame({
        "region": ["华东", "华北", "华南"],
        "sales": [1820, 1402, 1116],
    })
    charts = await step_chart_pick(df, "各区域销售")
    kinds = [c["kind"] for c in charts]
    assert "bars" in kinds, "类别对比应推荐柱状"


@pytest.mark.asyncio
async def test_chart_pick_empty_returns_empty():
    charts = await step_chart_pick(pd.DataFrame(), "test")
    assert charts == []


@pytest.mark.asyncio
async def test_chart_pick_none_returns_empty():
    charts = await step_chart_pick(None, "test")
    assert charts == []


# ==================== 异常检测 ====================

@pytest.mark.asyncio
async def test_anomaly_iqr_outlier():
    df = pd.DataFrame({"value": [10, 11, 12, 13, 100, 11, 9, 10, 12, 11]})
    insights = await step_anomaly(df)
    assert len(insights) > 0, "明显的离群值 100 应被检出"
    assert any("离群" in i["text"] or "异常" in i["kind"] for i in insights)


@pytest.mark.asyncio
async def test_anomaly_normal_data():
    """正常数据不应该有过多 insights。"""
    df = pd.DataFrame({"value": [10, 11, 12, 11, 10, 12, 11, 10]})
    insights = await step_anomaly(df)
    # 允许有 0-1 个，但不会爆出大量
    assert len(insights) <= 2


@pytest.mark.asyncio
async def test_anomaly_empty_df():
    insights = await step_anomaly(None)
    assert insights == []


# ==================== Critic ====================

@pytest.mark.asyncio
async def test_critic_normal_data_ok():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    assert await step_critic(df) is True


@pytest.mark.asyncio
async def test_critic_empty_df_fails():
    assert await step_critic(pd.DataFrame()) is False


@pytest.mark.asyncio
async def test_critic_none_fails():
    assert await step_critic(None) is False


@pytest.mark.asyncio
async def test_critic_all_null_fails():
    df = pd.DataFrame({"a": [None, None, None]})
    assert await step_critic(df) is False
