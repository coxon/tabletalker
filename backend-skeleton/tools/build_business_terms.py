"""基于 schemas.json 生成业务术语词典 business_terms.json。

业务术语词典是 Agent F-AG-03（TTL 推理与语义补全）的语义层底座：
- 把"华南""Q1""环比""持证率"等业务说法映射到具体的列名/聚合方式/过滤条件
- 等真接 LLM 时，TTL 步骤就靠这个词典把用户问题翻译成 SQL 友好形式

使用：
    cd backend-skeleton
    python tools/build_business_terms.py
    cat ../business_terms.json | head -50

V0：手工编写（覆盖 15 个数据集的核心术语）
V1：基于 LLM + schema 自动生成（接 LLM 后扩展）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


# ============ 业务术语词典（V0 手工版）============

BUSINESS_TERMS = {

    # ==== 时间维度（通用）====
    "时间": {
        "今年": {"filter": "YEAR(date) = 2026"},
        "去年": {"filter": "YEAR(date) = 2025"},
        "Q1": {"filter": "period = '2026Q1'", "alt_filter": "MONTH(date) BETWEEN 1 AND 3"},
        "Q2": {"filter": "period = '2026Q2'"},
        "Q3": {"filter": "period = '2026Q3'"},
        "Q4": {"filter": "period = '2026Q4'"},
        "本月": {"filter": "DATE_TRUNC('month', date) = DATE_TRUNC('month', CURRENT_DATE)"},
        "上月": {"filter": "DATE_TRUNC('month', date) = DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')"},
        "近 7 天": {"filter": "date >= CURRENT_DATE - INTERVAL '7 days'"},
        "近 30 天": {"filter": "date >= CURRENT_DATE - INTERVAL '30 days'"},
        "环比": {"compare_type": "qoq", "note": "本期 vs 上期"},
        "同比": {"compare_type": "yoy", "note": "本期 vs 去年同期"},
    },

    # ==== 区域 / 行政（销售、零售、运营商）====
    "区域": {
        "华南": {"column": "region_l1", "value": "华南"},
        "华东": {"column": "region_l1", "value": "华东"},
        "华北": {"column": "region_l1", "value": "华北"},
        "华中": {"column": "region_l1", "value": "华中"},
        "西南": {"column": "region_l1", "value": "西南"},
        "东北": {"column": "region_l1", "value": "东北"},
        "全国": {"note": "不加区域过滤"},
        "一线城市": {"column": "city_tier", "value": "T1"},
        "二线城市": {"column": "city_tier", "value": "T2"},
    },

    # ==== HR / 员工分析 ====
    "employee_analytics": {
        "BU": {"column": "bu_id", "examples": ["BU-1", "BU-2", "BU-3"]},
        "部门": {"column": "department"},
        "持证率": {
            "metric": "AVG(has_cert)",
            "format": "百分比",
            "note": "持证员工数 / 总员工数",
        },
        "AI 技能员工": {"filter": "has_ai_skill = 1"},
        "AI/ML 技能": {"filter": "has_ai_skill = 1"},
        "流动率": {
            "metric": "1 - AVG(is_active)",
            "format": "百分比",
            "note": "已离职员工占比",
        },
        "在职": {"filter": "is_active = 1"},
        "离职": {"filter": "is_active = 0"},
        "认证密度": {
            "metric": "AVG(cert_count)",
            "note": "人均证书数",
        },
        "人均产出": {
            "metric": "AVG(performance_score)",
            "note": "绩效平均分",
        },
        "任期": {"column": "tenure_years"},
        "薪资带": {"column": "salary_band"},
    },

    # ==== 销售订单 ====
    "sales_orders_2026": {
        "成交额": {"metric": "SUM(amount)", "unit": "万元"},
        "订单数": {"metric": "COUNT(*)"},
        "客单价": {"metric": "AVG(amount)", "unit": "万元"},
        "签单": {"filter": "status IN ('closed', 'shipping')"},
        "已收款": {"filter": "status = 'closed'"},
        "渠道": {"column": "channel"},
        "直销": {"column": "channel", "value": "直销"},
        "渠道集采": {"column": "channel", "value": "项目集采"},
        "产品线": {"column": "product_line"},
        "客户经理": {"column": "sales_manager_id"},
        "Top 客户": {
            "metric": "SUM(amount)",
            "group_by": "customer_id",
            "order": "DESC",
            "limit": 10,
        },
    },

    # ==== 财务 P&L ====
    "fin_pnl_monthly": {
        "预算": {"column": "budget"},
        "实际": {"column": "actual"},
        "偏差": {"column": "variance"},
        "偏差率": {"column": "variance_pct", "unit": "百分比"},
        "超支": {"filter": "variance > 0"},
        "节省": {"filter": "variance < 0"},
        "部门": {"column": "dept_name"},
        "成本": {"metric": "SUM(actual)"},
        "费用类别": {"column": "category"},
    },

    # ==== 运营商 ARPU ====
    "operator_arpu": {
        "ARPU": {"column": "arpu_value", "unit": "元/月"},
        "ARPU 异常": {"filter": "arpu_change_pct < -25"},
        "套餐": {"column": "plan_code"},
        "5G 用户": {"filter": "plan_code LIKE 'P-5G-%'"},
        "4G 用户": {"filter": "plan_code LIKE 'P-4G-%'"},
        "迁移群组": {"column": "cohort"},
        "5G 旧套餐迁移": {"column": "cohort", "value": "5G_legacy_migration"},
        "流失": {"filter": "churn_flag = 1"},
        "留存": {"filter": "churn_flag = 0"},
        "城市层级": {"column": "city_tier"},
    },

    # ==== 客服工单 ====
    "service_tickets": {
        "SLA 达成率": {"metric": "AVG(sla_met)", "format": "百分比"},
        "首响应时间": {"column": "resolution_time_hours"},
        "高优工单": {"filter": "priority IN ('P1', 'P2')"},
        "投诉": {"filter": "category = '投诉'"},
        "升级率": {"metric": "AVG(escalated)", "format": "百分比"},
        "满意度": {"metric": "AVG(csat_score)"},
        "优先级": {"column": "priority"},
    },

    # ==== B2B 客户 ====
    "b2b_customers": {
        "合同金额": {"column": "contract_value", "unit": "万元"},
        "续约": {"filter": "status = 'renewing'"},
        "已流失": {"filter": "status = 'churned'"},
        "高流失风险": {"filter": "churn_risk = 'high'"},
        "行业": {"column": "industry"},
        "NPS": {"column": "nps_score"},
        "金融客户": {"column": "industry", "value": "金融"},
    },

    # ==== 零售门店 ====
    "retail_stores": {
        "周末销售": {"column": "weekend_sales"},
        "工作日销售": {"column": "weekday_sales"},
        "毛利率": {"column": "gross_margin", "unit": "百分比"},
        "门店类型": {"column": "format"},
        "旗舰店": {"column": "format", "value": "旗舰店"},
        "总销售额": {"metric": "SUM(total_sales)"},
        "城市": {"column": "city"},
    },

    # ==== 交通 / 地铁 ====
    "traffic_metro": {
        "客流": {"column": "passenger_count"},
        "高峰时段": {"filter": "hour IN (7, 8, 18, 19)"},
        "工作日": {"filter": "is_weekend = 0"},
        "周末": {"filter": "is_weekend = 1"},
        "节假日": {"filter": "is_holiday = 1"},
        "线路": {"column": "line"},
    },

    # ==== 气象 ====
    "weather_cities": {
        "平均气温": {"column": "avg_temp", "unit": "℃"},
        "最高气温": {"column": "max_temp"},
        "最低气温": {"column": "min_temp"},
        "降水": {"column": "precipitation_mm", "unit": "mm"},
        "湿度": {"column": "humidity_pct", "unit": "百分比"},
        "空气质量": {"column": "aqi"},
        "城市": {"column": "city"},
    },

    # ==== 人口 ====
    "population_provinces": {
        "总人口": {"column": "total_population_wan", "unit": "万人"},
        "年龄段": {"column": "age_group"},
        "老龄化": {
            "filter": "age_group = '60+'",
            "metric": "SUM(age_count_wan) / SUM(total_population_wan)",
            "format": "百分比",
        },
        "城镇化率": {"column": "urban_pct", "unit": "百分比"},
        "省份": {"column": "province"},
    },

    # ==== 电影票房 ====
    "movies_box_office": {
        "票房": {"column": "total_box_office_yi", "unit": "亿元"},
        "首周末票房": {"column": "opening_weekend_yi"},
        "类型": {"column": "genre"},
        "导演": {"column": "director"},
        "评分": {"column": "rating"},
        "上映年份": {"column": "release_year"},
        "时长": {"column": "runtime_min", "unit": "分钟"},
    },

    # ==== 试航 ====
    "shipping_voyages": {
        "航行时长": {"column": "duration_hours", "unit": "小时"},
        "距离": {"column": "distance_nm", "unit": "海里"},
        "船型": {"column": "ship_type"},
        "燃油消耗": {"column": "fuel_consumption_ton", "unit": "吨"},
        "载货量": {"column": "cargo_weight_ton"},
        "出发港": {"column": "departure_port"},
        "到达港": {"column": "arrival_port"},
    },

    # ==== 库存 ====
    "product_inventory": {
        "库存": {"column": "stock_qty"},
        "周转天数": {"column": "turnover_days", "unit": "天"},
        "低库存": {"filter": "is_low_stock = 1"},
        "类目": {"column": "category"},
        "仓库": {"column": "warehouse_id"},
    },

    # ==== 营销 ====
    "marketing_campaigns": {
        "ROI": {"column": "roi"},
        "点击率": {"column": "ctr_pct", "unit": "百分比"},
        "转化率": {"column": "cvr_pct", "unit": "百分比"},
        "曝光": {"column": "impressions"},
        "渠道": {"column": "channel"},
        "总营收": {"metric": "SUM(revenue_wan)", "unit": "万元"},
    },

    # ==== App 用户事件 ====
    "app_user_events": {
        "DAU": {
            "metric": "COUNT(DISTINCT user_id)",
            "group_by": "date",
            "note": "日活用户",
        },
        "MAU": {
            "metric": "COUNT(DISTINCT user_id)",
            "filter": "date >= CURRENT_DATE - INTERVAL '30 days'",
        },
        "购买事件": {"filter": "event_type = 'purchase'"},
        "注册": {"filter": "event_type = 'register'"},
        "iOS 用户": {"filter": "platform = 'iOS'"},
        "Android 用户": {"filter": "platform = 'Android'"},
        "页面": {"column": "screen"},
    },
}


# ============ 同义词映射（让用户多种说法都能匹配）============

SYNONYMS = {
    "员工": ["人员", "雇员", "成员"],
    "证书": ["认证", "资格证"],
    "持证": ["认证", "拿证"],
    "AI/ML": ["AI", "人工智能", "机器学习"],
    "销售额": ["营收", "收入", "成交额"],
    "客户": ["甲方", "用户"],
    "套餐": ["资费", "package", "plan"],
    "工单": ["case", "ticket", "案子"],
    "门店": ["店铺", "店面"],
    "客流": ["人流", "passenger"],
    "气温": ["温度"],
    "票房": ["box office"],
    "船": ["船只", "船舶", "vessel"],
    "活动": ["campaign"],
    "活跃用户": ["DAU", "active user"],
    "增长": ["上升", "上涨", "升高"],
    "下降": ["下滑", "降低", "缩水"],
    "占比": ["比例", "比率"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="../business_terms.json")
    parser.add_argument("--schemas", default="../schemas.json")
    args = parser.parse_args()

    schemas_path = Path(args.schemas)
    if schemas_path.exists():
        schemas = json.loads(schemas_path.read_text())
        print(f"📥 加载 schemas.json：{len(schemas)} 个数据集")
    else:
        schemas = {}
        print(f"⚠️  schemas.json 不存在：{schemas_path}")

    # 校验：词典里的 dataset 必须在 schemas 里
    print("\n📋 数据集词典覆盖：")
    schema_keys = set(schemas.keys())
    term_dataset_keys = {k for k in BUSINESS_TERMS if k not in ("时间", "区域")}
    for k in term_dataset_keys:
        in_schemas = "✅" if k in schema_keys else "⚠️ "
        n_terms = len(BUSINESS_TERMS[k])
        print(f"  {in_schemas} {k}: {n_terms} 条术语")

    # 警告：schemas 里有但词典里没有的数据集
    missing = schema_keys - term_dataset_keys
    if missing:
        print(f"\n⚠️  以下 {len(missing)} 个数据集没有业务术语映射：")
        for m in sorted(missing):
            print(f"     - {m}")

    output = {
        "version": "v0.1",
        "format": "manual-curated",
        "global_terms": {k: BUSINESS_TERMS[k] for k in ("时间", "区域") if k in BUSINESS_TERMS},
        "dataset_terms": {k: v for k, v in BUSINESS_TERMS.items() if k not in ("时间", "区域")},
        "synonyms": SYNONYMS,
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    n_global = sum(len(v) for v in output["global_terms"].values())
    n_dataset = sum(len(v) for v in output["dataset_terms"].values())
    n_synonyms = len(output["synonyms"])
    print(f"\n✅ 写入 {out_path.resolve()}")
    print(f"   全局术语：{n_global} 条")
    print(f"   数据集术语：{n_dataset} 条")
    print(f"   同义词：{n_synonyms} 组")


if __name__ == "__main__":
    main()
