"""生成 15 个模拟数据集到 data/ 目录。

涵盖赛题四 6 大类：HR / 销售 / 财务 / 运营 / 零售 / 行业。
设计原则：
1. 每个数据集 200-5000 行，合理量级
2. 数据带"业务真实感"——时间序列有趋势、相关字段有相关性
3. 与 design-source/data.js 中的 7 个对话场景对齐
   （比如华南 Q1 同比 -12%、BU-3 流动率高、5G 套餐迁移导致 ARPU 下降等）

用法：
    cd backend-skeleton
    source .venv/bin/activate
    python tools/generate_mock_data.py
    ls -lh ../data/

总产出：~15 个 CSV 文件，约 5-15MB
"""
from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# 全局种子，保证可复现
SEED = 20260503
np.random.seed(SEED)
random.seed(SEED)

# ============ 通用常量 ============

REGIONS = ["华东", "华北", "华南", "西南", "华中", "东北"]
BU_IDS = [f"BU-{i}" for i in range(1, 7)]
PROVINCES = [
    "北京", "上海", "广东", "江苏", "浙江", "山东", "河南", "四川", "湖北", "湖南",
    "河北", "福建", "安徽", "陕西", "辽宁", "江西", "广西", "云南", "重庆", "天津",
    "贵州", "山西", "内蒙古", "吉林", "新疆", "甘肃", "黑龙江", "海南", "宁夏", "青海",
]
CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京", "重庆"]


# ============ 1. employee_analytics ============

def gen_employee_analytics(n=3000) -> pd.DataFrame:
    rows = []
    skill_pool = ["Java", "Python", "Go", "AI/ML", "Spark", "K8s", "React", "PM", "BD", "财务", "审计", "运营"]
    cert_pool = ["AWS", "PMP", "CFA", "TensorFlow", "K8s-CKA", "Oracle DBA", "ACP"]
    deps = ["研发", "销售", "市场", "运营", "财务", "HR", "客服", "产品"]

    for i in range(n):
        bu = random.choice(BU_IDS)
        # BU-3 故意做得"差"——员工经验少、流动率高、证书少
        is_bu3 = bu == "BU-3"
        tenure = max(0.1, np.random.exponential(2.5 if is_bu3 else 4))
        skills = random.sample(skill_pool, k=random.randint(1, 4))
        has_ai = "AI/ML" in skills
        # AI/ML 持证率整体约 5.5%（与 mock 数据对齐）
        has_cert_prob = 0.055 if has_ai else 0.18
        if bu in ("BU-2", "BU-5"):
            has_cert_prob *= 1.3   # BU-2/5 培训密度高
        if is_bu3:
            has_cert_prob *= 0.5
        has_cert = np.random.rand() < has_cert_prob
        rows.append({
            "employee_id": f"E{10000+i}",
            "bu_id": bu,
            "department": random.choice(deps),
            "skill_tags": "|".join(skills),
            "has_ai_skill": int(has_ai),
            "cert_count": int(has_cert) * random.randint(1, 3),
            "has_cert": int(has_cert),
            "main_cert": random.choice(cert_pool) if has_cert else None,
            "hire_date": (datetime(2020, 1, 1) + timedelta(days=random.randint(0, 1800))).strftime("%Y-%m-%d"),
            "tenure_years": round(tenure, 2),
            "manager_id": f"M{random.randint(100, 199)}",
            "performance_score": round(np.clip(np.random.normal(3.5, 0.6), 1, 5), 2),
            "salary_band": random.choice(["P3", "P4", "P5", "P6", "P7"]),
            "region": random.choice(REGIONS),
            "gender": random.choice(["男", "女"]),
            "age": int(np.clip(np.random.normal(33, 7), 22, 60)),
            "is_active": 0 if (is_bu3 and np.random.rand() < 0.05) or np.random.rand() < 0.028 else 1,
            "leave_date": None,
        })
    return pd.DataFrame(rows)


# ============ 2. sales_orders_2026 ============

def gen_sales_orders(n=5000) -> pd.DataFrame:
    rows = []
    products = ["智能客服", "数据中台", "BSS-OSS", "云平台", "AI 助理", "运营商网关", "IT 服务"]
    channels = ["直销", "渠道", "电商", "项目集采"]
    for i in range(n):
        # 时间分布在 2024-2025-2026 Q1
        year = np.random.choice([2024, 2025, 2026], p=[0.2, 0.4, 0.4])
        if year == 2026:
            month = np.random.randint(1, 4)  # Q1
            quarter = "2026Q1"
        else:
            month = np.random.randint(1, 13)
            quarter = f"{year}Q{(month - 1) // 3 + 1}"
        day = np.random.randint(1, 28)
        order_date = datetime(year, month, day).strftime("%Y-%m-%d")

        region = np.random.choice(REGIONS, p=[0.30, 0.22, 0.18, 0.12, 0.12, 0.06])
        # 华南在 2026Q1 有 -12% 同比下滑（让 c1 SQL 能复现）
        base_amount = np.random.exponential(50)
        if region == "华南" and quarter == "2026Q1":
            base_amount *= 0.85
        if region == "华东":
            base_amount *= 1.15
        amount = round(base_amount, 2)

        bu = random.choice(BU_IDS)
        # BU-3 在华南 2026 拖累
        if region == "华南" and bu == "BU-3" and year == 2026:
            amount *= 0.7

        rows.append({
            "order_id": f"SO{200000+i}",
            "customer_id": f"C{random.randint(1000, 4000)}",
            "region_l1": region,
            "region_l2": random.choice(["北线", "南线", "中线", "东线"]),
            "bu_id": bu,
            "product_line": random.choice(products),
            "amount": amount,
            "order_date": order_date,
            "period": quarter,
            "channel": random.choice(channels),
            "sales_manager_id": f"SM{random.randint(100, 250)}",
            "status": np.random.choice(["closed", "shipping", "pending"], p=[0.85, 0.1, 0.05]),
        })
    return pd.DataFrame(rows)


# ============ 3. fin_pnl_monthly ============

def gen_fin_pnl(n_dept=10, years=(2024, 2025, 2026)) -> pd.DataFrame:
    rows = []
    depts = [f"D{i:02d}" for i in range(1, n_dept + 1)]
    dept_names = ["研发部", "销售部", "市场部", "客服部", "供应链", "财务部", "HR部", "法务部", "战略部", "国际部"]
    categories = ["人力成本", "差旅", "设备", "外包", "营销", "其他"]

    for d_id, d_name in zip(depts, dept_names):
        for y in years:
            max_month = 13 if y < 2026 else 4   # 2026 仅 Q1
            for m in range(1, max_month):
                budget = round(np.random.uniform(200, 1500), 1)
                # 研发部 Q1 故意超支 18.7%（让 c5 复现）
                if d_name == "研发部" and y == 2026 and m <= 3:
                    actual = round(budget * np.random.uniform(1.15, 1.20), 1)
                else:
                    actual = round(budget * np.random.uniform(0.85, 1.10), 1)
                variance = round(actual - budget, 1)
                variance_pct = round((actual - budget) / budget * 100, 2)
                rows.append({
                    "dept_id": d_id,
                    "dept_name": d_name,
                    "month": m,
                    "year": y,
                    "period": f"{y}Q{(m - 1) // 3 + 1}",
                    "category": random.choice(categories),
                    "budget": budget,
                    "actual": actual,
                    "variance": variance,
                    "variance_pct": variance_pct,
                })
    return pd.DataFrame(rows)


# ============ 4. operator_arpu ============

def gen_operator_arpu(n_users=2000, months=12) -> pd.DataFrame:
    rows = []
    plans = ["P-5G-99", "P-5G-199", "P-4G-59", "P-4G-99", "P-IoT", "P-青年"]
    cohorts = ["5G_legacy_migration", "4G_retain", "young_user", "enterprise"]
    for u in range(n_users):
        plan = random.choice(plans)
        cohort = "5G_legacy_migration" if plan == "P-5G-99" and np.random.rand() < 0.5 else random.choice(cohorts)
        base_arpu = np.random.uniform(45, 150)
        migration_month = np.random.randint(1, months) if cohort == "5G_legacy_migration" else None

        for m in range(1, months + 1):
            mm_str = f"2026-{m:02d}"
            # 迁移后 ARPU 下降 25%（让 c3 SQL 复现）
            if migration_month and m > migration_month:
                arpu = base_arpu * np.random.uniform(0.65, 0.80)
                churn = int(np.random.rand() < 0.08)
            else:
                arpu = base_arpu * np.random.uniform(0.95, 1.05)
                churn = int(np.random.rand() < 0.02)
            prev_arpu = base_arpu if m == 1 else arpu * np.random.uniform(0.95, 1.05)
            rows.append({
                "user_id": f"U{100000+u}",
                "plan_code": plan,
                "cohort": cohort,
                "region": random.choice(REGIONS),
                "city_tier": random.choice(["T1", "T2", "T3", "T4"]),
                "age_group": random.choice(["18-25", "26-35", "36-45", "46-60", "60+"]),
                "month": mm_str,
                "arpu_value": round(arpu, 2),
                "prev_arpu": round(prev_arpu, 2),
                "arpu_change_pct": round((arpu - prev_arpu) / prev_arpu * 100, 2),
                "churn_flag": churn,
                "migration_date": f"2026-{migration_month:02d}-15" if migration_month else None,
            })
    return pd.DataFrame(rows)


# ============ 5. service_tickets ============

def gen_service_tickets(n=2000) -> pd.DataFrame:
    rows = []
    cats = ["故障申报", "咨询", "投诉", "业务变更", "退订", "其他"]
    priorities = ["P1", "P2", "P3", "P4"]
    for i in range(n):
        created = datetime(2026, np.random.randint(1, 5), np.random.randint(1, 28), np.random.randint(0, 24))
        sla_h = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}[priorities[0]]
        priority = random.choice(priorities)
        sla_h = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}[priority]
        resolution_h = max(0.5, np.random.exponential(sla_h * 0.6))
        resolved = created + timedelta(hours=resolution_h)
        sla_met = int(resolution_h <= sla_h)
        rows.append({
            "ticket_id": f"T{500000+i}",
            "customer_id": f"C{random.randint(1000, 4000)}",
            "category": random.choice(cats),
            "priority": priority,
            "channel": random.choice(["热线", "在线", "邮件", "App"]),
            "created_at": created.strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at": resolved.strftime("%Y-%m-%d %H:%M:%S"),
            "sla_hours": sla_h,
            "resolution_time_hours": round(resolution_h, 2),
            "sla_met": sla_met,
            "escalated": int(np.random.rand() < 0.08),
            "csat_score": int(np.random.choice([1, 2, 3, 4, 5], p=[0.05, 0.05, 0.15, 0.4, 0.35])),
            "agent_id": f"A{random.randint(100, 300)}",
        })
    return pd.DataFrame(rows)


# ============ 6. b2b_customers ============

def gen_b2b_customers(n=500) -> pd.DataFrame:
    rows = []
    industries = ["电信", "金融", "政企", "能源", "制造", "交通", "教育", "医疗", "零售", "物流"]
    for i in range(n):
        signed = datetime(2020, 1, 1) + timedelta(days=random.randint(0, 2000))
        last_contact = signed + timedelta(days=random.randint(30, 1500))
        rows.append({
            "customer_id": f"C{1000+i}",
            "customer_name": f"客户-{i:04d}",
            "industry": random.choice(industries),
            "region": random.choice(REGIONS),
            "contract_value": round(np.random.exponential(500), 2),
            "signed_date": signed.strftime("%Y-%m-%d"),
            "renewal_date": (signed + timedelta(days=365)).strftime("%Y-%m-%d"),
            "last_contact_date": last_contact.strftime("%Y-%m-%d"),
            "churn_risk": np.random.choice(["low", "med", "high"], p=[0.6, 0.3, 0.1]),
            "account_manager_id": f"AM{random.randint(50, 150)}",
            "status": np.random.choice(["active", "renewing", "churned"], p=[0.8, 0.15, 0.05]),
            "nps_score": int(np.random.choice([-100, -50, 0, 50, 100], p=[0.05, 0.1, 0.3, 0.4, 0.15])),
        })
    return pd.DataFrame(rows)


# ============ 7. retail_stores ============

def gen_retail_stores(n=300, periods=12) -> pd.DataFrame:
    rows = []
    formats = ["旗舰店", "标准店", "便利店", "无人店"]
    east = ["华东", "华南"]
    for i in range(n):
        store_id = f"S{2000+i}"
        region = random.choice(REGIONS)
        is_east = region in east
        fmt = random.choice(formats)
        for m in range(1, periods + 1):
            wd_sales = np.random.uniform(50, 300) * (1.2 if is_east else 0.9)
            we_sales = wd_sales * np.random.uniform(0.8, 1.6)
            total = wd_sales + we_sales
            margin = round(np.random.uniform(0.18, 0.32) * (1.05 if is_east else 1.0), 4)
            rows.append({
                "store_id": store_id,
                "store_name": f"门店-{i:04d}",
                "region": region,
                "city": random.choice(CITIES),
                "format": fmt,
                "month": f"2026-{m:02d}" if m <= 4 else f"2025-{m:02d}",
                "weekday_sales": round(wd_sales, 2),
                "weekend_sales": round(we_sales, 2),
                "total_sales": round(total, 2),
                "gross_margin": margin,
                "headcount": random.randint(3, 15),
            })
    return pd.DataFrame(rows)


# ============ 8. traffic_metro ============

def gen_traffic_metro(n_stations=50, days=30) -> pd.DataFrame:
    rows = []
    lines = [f"L{i}号线" for i in range(1, 11)]
    base_date = datetime(2026, 4, 1)
    for s in range(n_stations):
        line = random.choice(lines)
        station_id = f"ST{s:03d}"
        station_name = f"站点-{s:03d}"
        base_flow = np.random.uniform(2000, 30000)
        for d in range(days):
            cur = base_date + timedelta(days=d)
            is_weekend = cur.weekday() >= 5
            for h in [7, 8, 9, 12, 18, 19, 20]:  # 7 个高峰小时
                multiplier = 1.5 if h in [7, 8, 18, 19] else 0.6
                if is_weekend:
                    multiplier *= 0.7
                count = int(base_flow * multiplier * np.random.uniform(0.85, 1.15))
                rows.append({
                    "station_id": station_id,
                    "station_name": station_name,
                    "line": line,
                    "date": cur.strftime("%Y-%m-%d"),
                    "hour": h,
                    "is_weekend": int(is_weekend),
                    "is_holiday": int(d == 14),  # 模拟一个节假日
                    "passenger_count": count,
                })
    return pd.DataFrame(rows)


# ============ 9. weather_cities ============

def gen_weather_cities(years=(2021, 2022, 2023, 2024, 2025)) -> pd.DataFrame:
    rows = []
    for city in CITIES:
        base_temp = {"北京": 12, "上海": 17, "广州": 22, "深圳": 23, "杭州": 17,
                     "成都": 16, "武汉": 17, "西安": 14, "南京": 16, "重庆": 18}.get(city, 15)
        for y in years:
            for m in range(1, 13):
                # 季节温度
                seasonal = np.sin((m - 4) / 12 * 2 * np.pi) * 12
                # 北京 7 月在做小幅上升趋势（让 c4 类似的可复现）
                trend = (y - 2021) * 0.4 if (city == "北京" and m == 7) else 0
                avg = base_temp + seasonal + trend + np.random.normal(0, 1.2)
                rows.append({
                    "city": city,
                    "year": y,
                    "month": m,
                    "date": f"{y}-{m:02d}-15",
                    "avg_temp": round(avg, 1),
                    "max_temp": round(avg + np.random.uniform(3, 8), 1),
                    "min_temp": round(avg - np.random.uniform(3, 8), 1),
                    "precipitation_mm": round(max(0, np.random.exponential(50 if 5 <= m <= 9 else 20)), 1),
                    "humidity_pct": int(np.clip(np.random.normal(70, 12), 30, 98)),
                    "aqi": int(np.clip(np.random.normal(80, 30), 20, 250)),
                })
    return pd.DataFrame(rows)


# ============ 10. population_provinces ============

def gen_population_provinces() -> pd.DataFrame:
    rows = []
    age_groups = ["0-14", "15-29", "30-44", "45-59", "60+"]
    # 让某几个省份"老龄化严重"（如东北、四川、重庆）
    high_old_provinces = {"辽宁", "吉林", "黑龙江", "四川", "重庆"}
    for prov in PROVINCES:
        for y in (2020, 2021, 2022, 2023, 2024):
            total = np.random.uniform(2000, 11000)
            old_share_base = 0.22 if prov in high_old_provinces else 0.13
            shares = np.array([0.15, 0.20, 0.22, 0.25 if prov not in high_old_provinces else 0.20, old_share_base])
            shares = shares / shares.sum()
            for ag, sh in zip(age_groups, shares):
                rows.append({
                    "province": prov,
                    "year": y,
                    "total_population_wan": round(total, 1),
                    "age_group": ag,
                    "age_count_wan": round(total * sh, 1),
                    "age_pct": round(sh * 100, 2),
                    "urban_pct": round(np.random.uniform(45, 90), 2),
                })
    return pd.DataFrame(rows)


# ============ 11. movies_box_office ============

def gen_movies(n=500) -> pd.DataFrame:
    rows = []
    genres = ["动作", "科幻", "剧情", "喜剧", "爱情", "动画", "悬疑", "纪录片"]
    countries = ["中国", "美国", "韩国", "日本", "英国", "法国"]
    for i in range(n):
        rel_year = np.random.choice([2020, 2021, 2022, 2023, 2024], p=[0.15, 0.18, 0.22, 0.25, 0.20])
        opening = round(np.random.exponential(1.5), 2)
        total = round(opening * np.random.uniform(2, 8), 2)
        rows.append({
            "movie_id": f"M{1000+i}",
            "title": f"电影-{i:04d}",
            "release_year": rel_year,
            "release_date": f"{rel_year}-{np.random.randint(1, 13):02d}-{np.random.randint(1, 28):02d}",
            "genre": random.choice(genres),
            "director": f"导演-{random.randint(1, 80)}",
            "country": random.choice(countries),
            "runtime_min": random.randint(80, 180),
            "rating": round(np.clip(np.random.normal(7, 1.2), 3, 9.8), 1),
            "opening_weekend_yi": opening,
            "total_box_office_yi": total,
        })
    return pd.DataFrame(rows)


# ============ 12. shipping_voyages ============

def gen_shipping(n=500) -> pd.DataFrame:
    rows = []
    ship_types = ["集装箱船", "散货船", "油轮", "客船", "渔船"]
    ports = ["上海", "宁波", "青岛", "广州", "深圳", "厦门", "天津", "大连"]
    for i in range(n):
        dep_t = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 700), hours=random.randint(0, 23))
        duration_h = np.random.exponential(80)
        arr_t = dep_t + timedelta(hours=duration_h)
        distance = duration_h * np.random.uniform(8, 18)
        rows.append({
            "voyage_id": f"V{50000+i}",
            "ship_id": f"SH{random.randint(100, 250)}",
            "ship_type": random.choice(ship_types),
            "departure_port": random.choice(ports),
            "arrival_port": random.choice(ports),
            "departure_time": dep_t.strftime("%Y-%m-%d %H:%M"),
            "arrival_time": arr_t.strftime("%Y-%m-%d %H:%M"),
            "distance_nm": round(distance, 1),
            "duration_hours": round(duration_h, 2),
            "fuel_consumption_ton": round(distance * np.random.uniform(0.05, 0.15), 2),
            "cargo_weight_ton": round(np.random.exponential(2000), 1),
            "weather_grade": random.choice(["A", "B", "C", "D"]),
        })
    return pd.DataFrame(rows)


# ============ 13. product_inventory ============

def gen_inventory(n=1000) -> pd.DataFrame:
    rows = []
    categories = ["电子", "服装", "食品", "家居", "美妆", "运动", "母婴", "图书"]
    for i in range(n):
        rows.append({
            "sku_id": f"SKU{30000+i}",
            "sku_name": f"商品-{i:04d}",
            "category": random.choice(categories),
            "warehouse_id": f"W{random.randint(1, 10):02d}",
            "stock_qty": int(np.random.exponential(200)),
            "reorder_point": random.randint(20, 100),
            "unit_cost": round(np.random.uniform(5, 500), 2),
            "last_restock_date": (datetime(2026, 1, 1) + timedelta(days=random.randint(0, 120))).strftime("%Y-%m-%d"),
            "turnover_days": round(np.random.uniform(7, 90), 1),
            "is_low_stock": int(np.random.rand() < 0.15),
        })
    return pd.DataFrame(rows)


# ============ 14. marketing_campaigns ============

def gen_marketing(n=200) -> pd.DataFrame:
    rows = []
    channels = ["搜索", "信息流", "短视频", "邮件", "线下", "联盟", "社交"]
    for i in range(n):
        start = datetime(2025, 1, 1) + timedelta(days=random.randint(0, 480))
        end = start + timedelta(days=random.randint(7, 30))
        budget = round(np.random.uniform(50, 500), 2)
        spend = round(budget * np.random.uniform(0.85, 1.05), 2)
        impressions = int(np.random.exponential(500000))
        clicks = int(impressions * np.random.uniform(0.005, 0.03))
        conversions = int(clicks * np.random.uniform(0.02, 0.10))
        revenue = round(conversions * np.random.uniform(80, 300), 2)
        rows.append({
            "campaign_id": f"CMP{1000+i}",
            "campaign_name": f"营销活动-{i:04d}",
            "channel": random.choice(channels),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "budget_wan": budget,
            "spend_wan": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr_pct": round(clicks / max(impressions, 1) * 100, 4),
            "conversions": conversions,
            "cvr_pct": round(conversions / max(clicks, 1) * 100, 4),
            "revenue_wan": revenue,
            "roi": round(revenue / max(spend, 0.1), 2),
        })
    return pd.DataFrame(rows)


# ============ 15. app_user_events ============

def gen_app_events(n=5000) -> pd.DataFrame:
    rows = []
    events = ["app_open", "page_view", "click", "purchase", "share", "logout", "register", "search"]
    platforms = ["iOS", "Android", "Web"]
    versions = ["1.0.0", "1.1.0", "1.2.0", "1.3.0"]
    for i in range(n):
        ts = datetime(2026, 4, 1) + timedelta(seconds=random.randint(0, 30 * 86400))
        rows.append({
            "event_id": f"E{4000000+i}",
            "user_id": f"U{random.randint(1000, 50000)}",
            "event_type": np.random.choice(events, p=[0.20, 0.35, 0.20, 0.05, 0.03, 0.05, 0.02, 0.10]),
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "date": ts.strftime("%Y-%m-%d"),
            "hour": ts.hour,
            "platform": random.choice(platforms),
            "app_version": random.choice(versions),
            "session_id": f"SES{random.randint(10000, 99999)}",
            "screen": random.choice(["首页", "搜索", "详情", "购物车", "我的", "设置"]),
            "duration_sec": round(np.random.exponential(30), 1),
        })
    return pd.DataFrame(rows)


# ============ 主流程 ============

DATASETS = [
    ("employee_analytics", gen_employee_analytics, 3000),
    ("sales_orders_2026", gen_sales_orders, 5000),
    ("fin_pnl_monthly", gen_fin_pnl, None),
    ("operator_arpu", gen_operator_arpu, None),
    ("service_tickets", gen_service_tickets, 2000),
    ("b2b_customers", gen_b2b_customers, 500),
    ("retail_stores", gen_retail_stores, None),
    ("traffic_metro", gen_traffic_metro, None),
    ("weather_cities", gen_weather_cities, None),
    ("population_provinces", gen_population_provinces, None),
    ("movies_box_office", gen_movies, 500),
    ("shipping_voyages", gen_shipping, 500),
    ("product_inventory", gen_inventory, 1000),
    ("marketing_campaigns", gen_marketing, 200),
    ("app_user_events", gen_app_events, 5000),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="../data", help="输出目录（默认 ../data）")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🎲 生成 15 个模拟数据集到 {out_dir.resolve()}\n")

    summary = []
    for name, gen_fn, n in DATASETS:
        print(f"  → {name} ...", end=" ", flush=True)
        df = gen_fn(n) if n is not None else gen_fn()
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False, encoding="utf-8")
        size_kb = path.stat().st_size / 1024
        print(f"✅ {len(df):>6} 行  {size_kb:>8.1f} KB")
        summary.append((name, len(df), size_kb, list(df.columns)))

    print("\n" + "=" * 70)
    total_rows = sum(s[1] for s in summary)
    total_size = sum(s[2] for s in summary)
    print(f"  ✅ 共 {len(summary)} 个数据集 · {total_rows:,} 行 · {total_size:.1f} KB ({total_size/1024:.2f} MB)")
    print("=" * 70)

    print("\n📋 后续步骤：")
    print(f"  1. 抽取 schema 缓存：python tools/extract_schema.py --data-dir {args.out} --out ../schemas.json")
    print("  2. 重启后端让 Agent 加载新 schema")
    print("  3. 浏览器问问题：'Q1 各区域销售对比' / 'BU-3 流动率为什么高'")


if __name__ == "__main__":
    main()
