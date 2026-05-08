"""pytest 公共 fixture。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 把项目根加入 PYTHONPATH，让 `from agent.steps import ...` 工作
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """每个测试用临时目录隔离 DB / 文件，避免测试互相影响。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("BUSINESS_TERMS_FILE", str(tmp_path / "_no_business_terms.json"))
    monkeypatch.setenv("GRAPHRAG_INDEX", str(tmp_path / "_no_graphrag.json"))
    monkeypatch.setenv("SCHEMAS_FILE", str(tmp_path / "_no_schemas.json"))

    # 强制 storage 模块用新的 DB_PATH（它在 import 时已经赋值过 module-level 变量）
    from db import storage
    storage.DB_PATH = Path(os.environ["DB_PATH"])
    storage.init_db()
    yield


@pytest.fixture
def sample_business_terms_file(tmp_path, monkeypatch):
    """提供一个最小可用的 business_terms.json。"""
    import json
    p = tmp_path / "business_terms.json"
    p.write_text(json.dumps({
        "global_terms": {
            "时间": {"Q1": {"filter": "period='2026Q1'"}, "环比": {"compare_type": "qoq"}},
        },
        "dataset_terms": {
            "employee_analytics": {
                "持证率": {"metric": "AVG(has_cert)"},
                "BU": {"column": "bu_id"},
            },
            "sales_orders_2026": {
                "成交额": {"metric": "SUM(amount)"},
            },
        },
        "synonyms": {"销售额": ["营收", "成交额"]},
    }, ensure_ascii=False))
    monkeypatch.setenv("BUSINESS_TERMS_FILE", str(p))
    # 强制重新加载
    from agent import steps
    steps._BUSINESS_TERMS = None
    return p


@pytest.fixture
def sample_graphrag_index(tmp_path, monkeypatch):
    import json
    p = tmp_path / "graphrag_index.json"
    p.write_text(json.dumps({
        "communities": [
            {
                "id": "c_hr", "name": "HR 月报",
                "summary": "员工技能/认证/流动率",
                "datasets": ["employee_analytics"],
                "key_terms": ["BU", "持证率", "AI/ML"],
                "all_terms": ["BU", "持证率", "AI/ML", "认证", "流动率"],
                "typical_questions": ["BU-3 流动率为什么高"],
            },
            {
                "id": "c_sales", "name": "销售归因",
                "summary": "区域 + BU + 渠道",
                "datasets": ["sales_orders_2026"],
                "key_terms": ["华南", "Q1", "成交额"],
                "all_terms": ["华南", "Q1", "成交额", "BU", "客户经理"],
                "typical_questions": ["Q1 华南销售下滑"],
            },
        ],
    }, ensure_ascii=False))
    monkeypatch.setenv("GRAPHRAG_INDEX", str(p))
    from agent import steps
    steps._GRAPHRAG_INDEX = None
    return p
