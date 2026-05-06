"""GraphRAG 索引构建脚本。

基于 schemas.json + business_terms.json 构建：
1. 实体图（dataset / column / business_term 三类节点 + 关系）
2. 社区聚类（联通子图 → 业务社区）
3. 社区摘要（自然语言一句话描述）

输出：graphrag_index.json，被 agent/steps.py 的 step_graphrag 加载用。

V0：纯规则 + 关键词；V1：等真接 LLM 后用 LLM 生成更好的社区摘要。

用法：
    cd backend-skeleton
    python tools/build_graphrag.py
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


# ============ 业务社区定义（手工策展，覆盖 6 大类）============

COMMUNITIES = [
    {
        "id": "community_hr",
        "name": "人力资源分析",
        "datasets": ["employee_analytics"],
        "key_terms": ["BU", "持证率", "流动率", "认证密度", "人均产出", "AI/ML 技能", "技能"],
        "summary": "员工技能、认证、流动率、人均产出的多维分析；适合月度 HR 复盘、组织能力评估、培训需求识别。",
        "typical_questions": [
            "BU-3 流动率为什么高",
            "AI/ML 技能员工持证率",
            "各 BU 人均产出对比",
        ],
    },
    {
        "id": "community_sales",
        "name": "销售归因与漏斗",
        "datasets": ["sales_orders_2026", "fin_pnl_monthly"],
        "key_terms": ["成交额", "区域", "Q1", "BU", "客户经理", "渠道", "环比", "同比"],
        "summary": "订单×部门×区域×渠道的销售归因；适合区域复盘、BU 拖累分析、季度同比/环比变化解读。",
        "typical_questions": [
            "Q1 华南销售为什么下滑",
            "哪些 BU 拖累最大",
            "对比直销和渠道的成交额",
        ],
    },
    {
        "id": "community_finance",
        "name": "财务预算与成本",
        "datasets": ["fin_pnl_monthly"],
        "key_terms": ["预算", "实际", "偏差", "超支", "部门", "成本", "费用类别"],
        "summary": "部门 × 月预算执行偏差；适合季度预算审议、超支识别、成本优化分析。",
        "typical_questions": [
            "哪个部门超支最严重",
            "Q1 预算偏差总览",
            "外包成本占比",
        ],
    },
    {
        "id": "community_operator",
        "name": "运营商用户与套餐",
        "datasets": ["operator_arpu", "service_tickets"],
        "key_terms": ["ARPU", "套餐", "迁移", "5G", "4G", "异常下跌", "流失", "城市层级"],
        "summary": "用户 ARPU 时序 + 套餐迁移 cohort + SLA 工单；适合套餐变更影响评估、流失预警、客户分层。",
        "typical_questions": [
            "哪些用户 ARPU 异常下跌",
            "5G 套餐迁移影响",
            "高优工单 SLA 达成率",
        ],
    },
    {
        "id": "community_retail",
        "name": "零售门店与营销",
        "datasets": ["retail_stores", "marketing_campaigns", "product_inventory"],
        "key_terms": ["门店", "工作日", "周末", "毛利率", "ROI", "渠道", "库存", "周转"],
        "summary": "门店销售 × 营销 ROI × 库存周转的协同分析；适合区域门店对比、营销活动效果评估、库存优化。",
        "typical_questions": [
            "东西部门店销售对比",
            "ROI 最高的营销渠道",
            "库存周转 Top 类目",
        ],
    },
    {
        "id": "community_industry",
        "name": "行业与宏观洞察",
        "datasets": [
            "movies_box_office", "weather_cities", "population_provinces",
            "shipping_voyages", "traffic_metro", "app_user_events", "b2b_customers",
        ],
        "key_terms": ["票房", "气温", "人口", "老龄化", "客流", "DAU", "续约", "客户"],
        "summary": "宏观数据集合：票房 / 气象 / 人口 / 试航 / 交通 / 应用事件 / 客户管理；用于行业研究、长期趋势探索、跨域关联挖掘。",
        "typical_questions": [
            "近 5 年北京 7 月气温走势",
            "2023 年票房 Top 10",
            "老龄化最严重的省份",
            "客户流失早期信号",
        ],
    },
]


def build_entity_graph(schemas: dict, business_terms: dict) -> dict:
    """构建三类节点 + 三类边的实体图。

    节点：
    - dataset: 数据集
    - column: 字段（属于某 dataset）
    - term: 业务术语

    边：
    - has_column: dataset → column
    - maps_to: term → column（业务术语映射到字段）
    - synonym_of: term → term（同义词组）
    """
    nodes = {"dataset": [], "column": [], "term": []}
    edges = {"has_column": [], "maps_to": [], "synonym_of": []}

    # dataset + column 节点
    for ds_name, ds_info in schemas.items():
        nodes["dataset"].append({
            "id": f"ds:{ds_name}",
            "name": ds_name,
            "n_columns": len(ds_info.get("columns", [])),
            "description": ds_info.get("description", ""),
        })
        for col in ds_info.get("columns", []):
            col_id = f"col:{ds_name}.{col['name']}"
            nodes["column"].append({
                "id": col_id,
                "name": col["name"],
                "dataset": ds_name,
                "dtype": col.get("dtype", ""),
                "business_term": col.get("business_term", ""),
            })
            edges["has_column"].append({
                "from": f"ds:{ds_name}",
                "to": col_id,
            })

    # term 节点 + maps_to 边
    for ds_name, terms in business_terms.get("dataset_terms", {}).items():
        for term, mapping in terms.items():
            term_id = f"term:{term}@{ds_name}"
            nodes["term"].append({
                "id": term_id,
                "name": term,
                "dataset": ds_name,
                "mapping": mapping,
            })
            # 如果 mapping 有 column 字段，建 maps_to 边
            if "column" in mapping:
                edges["maps_to"].append({
                    "from": term_id,
                    "to": f"col:{ds_name}.{mapping['column']}",
                })

    # 全局 term（时间、区域）
    for cat, terms in business_terms.get("global_terms", {}).items():
        for term, mapping in terms.items():
            nodes["term"].append({
                "id": f"term:{term}@global",
                "name": term,
                "category": cat,
                "mapping": mapping,
            })

    # 同义词边
    synonyms = business_terms.get("synonyms", {})
    for canonical, syn_list in synonyms.items():
        for syn in syn_list:
            edges["synonym_of"].append({
                "from": f"term:{syn}",
                "to": f"term:{canonical}",
            })

    return {"nodes": nodes, "edges": edges}


def build_community_index(schemas: dict, business_terms: dict) -> list[dict]:
    """每个社区附完整可检索信息，便于 step_graphrag 使用。"""
    communities = []
    for c in COMMUNITIES:
        # 收集这个社区涉及的所有列
        all_columns = []
        for ds in c["datasets"]:
            if ds in schemas:
                all_columns.extend(
                    f"{ds}.{col['name']}" for col in schemas[ds].get("columns", [])
                )

        # 收集业务术语
        all_terms = list(c.get("key_terms", []))
        for ds in c["datasets"]:
            if ds in business_terms.get("dataset_terms", {}):
                all_terms.extend(business_terms["dataset_terms"][ds].keys())

        # 构造一个加权检索字符串（用于关键词匹配）
        search_text = " ".join([
            c["name"], c["summary"],
            " ".join(c["datasets"]),
            " ".join(all_terms),
            " ".join(c.get("typical_questions", [])),
        ])

        communities.append({
            "id": c["id"],
            "name": c["name"],
            "summary": c["summary"],
            "datasets": c["datasets"],
            "key_terms": c["key_terms"],
            "all_terms": list(set(all_terms)),
            "all_columns": all_columns,
            "typical_questions": c["typical_questions"],
            "search_text": search_text,
        })
    return communities


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schemas", default="../schemas.json")
    parser.add_argument("--terms", default="../business_terms.json")
    parser.add_argument("--out", default="../graphrag_index.json")
    args = parser.parse_args()

    schemas_path = Path(args.schemas)
    terms_path = Path(args.terms)

    if not schemas_path.exists():
        print(f"⚠️  {schemas_path} 不存在，先跑 python tools/extract_schema.py")
        return
    if not terms_path.exists():
        print(f"⚠️  {terms_path} 不存在，先跑 python tools/build_business_terms.py")
        return

    schemas = json.loads(schemas_path.read_text())
    business_terms = json.loads(terms_path.read_text())

    print(f"📥 schemas: {len(schemas)} 个数据集")
    print(f"📥 业务术语: {sum(len(v) for v in business_terms.get('dataset_terms', {}).values())} 条")

    print("\n→ 构建实体图 ...")
    graph = build_entity_graph(schemas, business_terms)
    n_nodes = sum(len(v) for v in graph["nodes"].values())
    n_edges = sum(len(v) for v in graph["edges"].values())
    print(f"   ✅ 节点：{n_nodes}（dataset {len(graph['nodes']['dataset'])} / column {len(graph['nodes']['column'])} / term {len(graph['nodes']['term'])}）")
    print(f"   ✅ 边：{n_edges}（has_column {len(graph['edges']['has_column'])} / maps_to {len(graph['edges']['maps_to'])} / synonym_of {len(graph['edges']['synonym_of'])}）")

    print("\n→ 构建社区索引 ...")
    communities = build_community_index(schemas, business_terms)
    print(f"   ✅ {len(communities)} 个社区：")
    for c in communities:
        print(f"      · {c['name']}（{len(c['datasets'])} 数据集 / {len(c['all_terms'])} 术语）")

    output = {
        "version": "v0.1",
        "graph": graph,
        "communities": communities,
        "stats": {
            "n_datasets": len(schemas),
            "n_columns": len(graph["nodes"]["column"]),
            "n_terms": len(graph["nodes"]["term"]),
            "n_communities": len(communities),
        },
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅ 写入 {out_path.resolve()}")
    print(f"   文件大小：{out_path.stat().st_size / 1024:.1f} KB")
    print("\n📋 后续：")
    print("   - agent/steps.py 的 step_graphrag 会自动加载此文件")
    print("   - 重启后端：bash stop.sh && bash start.sh")


if __name__ == "__main__":
    main()
