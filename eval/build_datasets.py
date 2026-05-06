"""Synthesize 15 evaluation datasets.

Why synthetic instead of real public CSVs? The organizer's grading
network may block external downloads, and we want a re-run to reproduce
the same evidence numbers. So every dataset here is built from `numpy`
RNGs seeded per-dataset; the shapes (column count, mix of categorical /
numeric / date, NaN rate, encoding edge cases) are picked to exercise
the same code paths the official rubric does.

Run via `python eval/build_datasets.py` or `make eval-datasets`. Output
lands under `eval/datasets/*.csv`. The directory is gitignored — every
re-run regenerates byte-identical files.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "datasets"


def _save(df: pd.DataFrame, name: str, *, encoding: str = "utf-8-sig") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{name}.csv", index=False, encoding=encoding)


def ds01_ecommerce_orders() -> None:
    rng = np.random.default_rng(1)
    n = 5_000
    df = pd.DataFrame(
        {
            "order_id": [f"O{1000000 + i}" for i in range(n)],
            "customer_age": rng.integers(18, 75, n),
            "gender": rng.choice(["男", "女"], n, p=[0.45, 0.55]),
            "category": rng.choice(
                ["女装", "男装", "鞋类", "配饰", "美妆"], n, p=[0.30, 0.22, 0.18, 0.14, 0.16]
            ),
            "purchase_amount_usd": np.round(rng.gamma(2.0, 30.0, n), 2),
            "season": rng.choice(["Spring", "Summer", "Fall", "Winter"], n),
            "subscription_status": rng.choice(["Yes", "No"], n, p=[0.28, 0.72]),
            "discount_applied": rng.choice(["Yes", "No"], n, p=[0.43, 0.57]),
            "review_rating": np.round(rng.uniform(1, 5, n), 1),
        }
    )
    _save(df, "01_ecommerce_orders")


def ds02_hr_attrition() -> None:
    rng = np.random.default_rng(2)
    n = 3_000
    df = pd.DataFrame(
        {
            "employee_id": [f"E{i:05d}" for i in range(n)],
            "department": rng.choice(["技术", "销售", "市场", "运营", "财务", "HR"], n),
            "level": rng.choice(["P3", "P4", "P5", "P6", "P7"], n, p=[0.25, 0.30, 0.22, 0.15, 0.08]),
            "tenure_years": np.round(rng.gamma(2.0, 2.5, n), 1),
            "annual_salary_cny": (rng.lognormal(11.5, 0.4, n)).astype(int),
            "performance_score": np.round(rng.uniform(2, 5, n), 2),
            "left_company": rng.choice([0, 1], n, p=[0.84, 0.16]),
            "wfh_days_per_week": rng.integers(0, 6, n),
        }
    )
    _save(df, "02_hr_attrition")


def ds03_bank_transactions() -> None:
    rng = np.random.default_rng(3)
    n = 8_000
    df = pd.DataFrame(
        {
            "txn_id": [f"T{i:08d}" for i in range(n)],
            "txn_date": pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D"),
            "channel": rng.choice(["手机银行", "网银", "ATM", "柜面", "POS"], n, p=[0.45, 0.18, 0.14, 0.08, 0.15]),
            "txn_type": rng.choice(["转账", "存款", "取款", "消费", "缴费"], n),
            "amount_cny": np.round(rng.gamma(1.5, 800.0, n), 2),
            "currency": "CNY",
            "is_fraud": rng.choice([0, 1], n, p=[0.985, 0.015]),
            "city": rng.choice(["北京", "上海", "广州", "深圳", "成都", "杭州"], n),
        }
    )
    _save(df, "03_bank_transactions")


def ds04_hospital_admissions() -> None:
    rng = np.random.default_rng(4)
    n = 2_500
    df = pd.DataFrame(
        {
            "admission_id": [f"A{i:06d}" for i in range(n)],
            "patient_age": rng.integers(0, 95, n),
            "gender": rng.choice(["M", "F"], n),
            "department": rng.choice(["内科", "外科", "儿科", "妇产科", "骨科", "急诊"], n),
            "diagnosis_code": rng.choice(["I10", "E11", "J45", "K21", "M54", "I25", "N18"], n),
            "length_of_stay_days": rng.integers(1, 30, n),
            "readmission_30d": rng.choice([0, 1], n, p=[0.91, 0.09]),
            "total_charge_cny": (rng.gamma(2.0, 4500.0, n)).astype(int),
        }
    )
    _save(df, "04_hospital_admissions")


def ds05_student_scores() -> None:
    rng = np.random.default_rng(5)
    n = 1_800
    df = pd.DataFrame(
        {
            "student_id": [f"S{i:05d}" for i in range(n)],
            "grade_level": rng.choice([7, 8, 9, 10, 11, 12], n),
            "city_tier": rng.choice(["一线", "二线", "三线", "县城"], n, p=[0.20, 0.30, 0.30, 0.20]),
            "math_score": np.clip(rng.normal(75, 15, n), 0, 100).round(1),
            "chinese_score": np.clip(rng.normal(78, 12, n), 0, 100).round(1),
            "english_score": np.clip(rng.normal(72, 18, n), 0, 100).round(1),
            "study_hours_per_week": np.round(rng.gamma(2.5, 4.0, n), 1),
            "club_member": rng.choice(["Yes", "No"], n, p=[0.42, 0.58]),
        }
    )
    _save(df, "05_student_scores")


def ds06_subway_ridership() -> None:
    rng = np.random.default_rng(6)
    dates = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    lines = ["1号线", "2号线", "10号线", "13号线", "机场线"]
    rows = []
    for d in dates:
        weekday = d.weekday()
        for line in lines:
            base = {"1号线": 1.2, "2号线": 1.4, "10号线": 0.95, "13号线": 0.7, "机场线": 0.45}[line]
            weekend_mult = 0.78 if weekday >= 5 else 1.0
            seasonal = 1.0 + 0.12 * np.sin(2 * np.pi * d.timetuple().tm_yday / 365)
            riders = int(base * weekend_mult * seasonal * 1_000_000 * (1 + rng.normal(0, 0.06)))
            rows.append({"date": d.date(), "line": line, "riders": riders, "weekday": weekday})
    df = pd.DataFrame(rows)
    _save(df, "06_subway_ridership")


def ds07_air_quality() -> None:
    rng = np.random.default_rng(7)
    cities = ["北京", "上海", "广州", "成都", "西安", "乌鲁木齐", "海口"]
    dates = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    rows = []
    for d in dates:
        for city in cities:
            pm25 = max(5, rng.normal({"北京": 55, "上海": 38, "广州": 30, "成都": 60, "西安": 70, "乌鲁木齐": 50, "海口": 22}[city], 18))
            rows.append({
                "date": d.date(),
                "city": city,
                "pm2_5": round(pm25, 1),
                "pm10": round(pm25 * 1.5 + rng.normal(0, 5), 1),
                "no2": round(rng.normal(35, 12), 1),
                "o3": round(rng.normal(60, 20), 1),
                "aqi_category": "优" if pm25 < 35 else "良" if pm25 < 75 else "轻度污染" if pm25 < 115 else "中度污染",
            })
    _save(pd.DataFrame(rows), "07_air_quality")


def ds08_logistics_routes() -> None:
    rng = np.random.default_rng(8)
    n = 4_000
    df = pd.DataFrame(
        {
            "shipment_id": [f"SH{i:07d}" for i in range(n)],
            "origin_city": rng.choice(["上海", "广州", "义乌", "深圳", "宁波"], n),
            "destination_city": rng.choice(["北京", "成都", "武汉", "西安", "沈阳"], n),
            "weight_kg": np.round(rng.gamma(1.5, 8.0, n), 1),
            "distance_km": rng.integers(150, 3500, n),
            "transit_hours": np.round(rng.gamma(2.0, 12.0, n), 1),
            "carrier": rng.choice(["顺丰", "京东", "中通", "圆通", "韵达"], n),
            "on_time": rng.choice([0, 1], n, p=[0.18, 0.82]),
            "freight_cny": np.round(rng.gamma(2.0, 25.0, n), 2),
        }
    )
    _save(df, "08_logistics_routes")


def ds09_telecom_churn() -> None:
    rng = np.random.default_rng(9)
    n = 4_500
    df = pd.DataFrame(
        {
            "customer_id": [f"C{i:06d}" for i in range(n)],
            "tenure_months": rng.integers(1, 96, n),
            "monthly_fee_cny": np.round(rng.uniform(28, 388, n), 2),
            "plan_type": rng.choice(["流量包", "通话包", "套餐", "5G尊享"], n),
            "data_usage_gb": np.round(rng.gamma(2.0, 8.0, n), 1),
            "voice_minutes": rng.integers(0, 800, n),
            "sms_count": rng.integers(0, 200, n),
            "complaints_last_30d": rng.poisson(0.4, n),
            "churned": rng.choice([0, 1], n, p=[0.78, 0.22]),
        }
    )
    _save(df, "09_telecom_churn")


def ds10_realestate_listings() -> None:
    rng = np.random.default_rng(10)
    n = 3_500
    cities = rng.choice(["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安"], n)
    base_price = {"北京": 75000, "上海": 72000, "广州": 35000, "深圳": 78000, "杭州": 42000, "成都": 22000, "武汉": 21000, "西安": 18000}
    df = pd.DataFrame(
        {
            "listing_id": [f"L{i:07d}" for i in range(n)],
            "city": cities,
            "district": rng.choice(["朝阳", "海淀", "西城", "天河", "越秀", "南山", "西湖", "锦江"], n),
            "area_sqm": np.round(rng.uniform(35, 200, n), 1),
            "rooms": rng.integers(1, 6, n),
            "build_year": rng.integers(1990, 2024, n),
            "list_price_cny": [int(base_price[c] * a * (1 + rng.normal(0, 0.15))) for c, a in zip(cities, rng.uniform(0.85, 1.20, n))],
            "has_elevator": rng.choice(["Yes", "No"], n, p=[0.74, 0.26]),
            "decoration": rng.choice(["毛坯", "简装", "精装", "豪装"], n),
        }
    )
    _save(df, "10_realestate_listings")


def ds11_movie_ratings() -> None:
    rng = np.random.default_rng(11)
    n = 6_000
    df = pd.DataFrame(
        {
            "user_id": rng.integers(1, 800, n),
            "movie_id": rng.integers(1, 250, n),
            "rating": np.round(rng.uniform(1, 10, n), 1),
            "genre": rng.choice(["剧情", "喜剧", "动作", "悬疑", "爱情", "科幻", "动画"], n),
            "watch_year": rng.integers(2015, 2026, n),
            "duration_min": rng.integers(75, 180, n),
            "language": rng.choice(["中文", "英语", "日语", "韩语"], n, p=[0.45, 0.40, 0.10, 0.05]),
        }
    )
    _save(df, "11_movie_ratings")


def ds12_fitness_tracker() -> None:
    rng = np.random.default_rng(12)
    n = 2_400
    df = pd.DataFrame(
        {
            "user_id": [f"U{i:05d}" for i in range(n // 30) for _ in range(30)],
            "date": [pd.to_datetime("2025-09-01") + pd.Timedelta(days=i) for _ in range(n // 30) for i in range(30)],
            "steps": rng.integers(2000, 18000, n),
            "calories_kcal": rng.integers(1400, 3800, n),
            "sleep_hours": np.round(rng.uniform(4, 10, n), 1),
            "active_minutes": rng.integers(15, 240, n),
            "device_brand": rng.choice(["Apple", "Garmin", "华为", "小米"], n, p=[0.32, 0.10, 0.34, 0.24]),
        }
    )
    _save(df, "12_fitness_tracker")


def ds13_iot_sensor() -> None:
    rng = np.random.default_rng(13)
    devices = [f"D{i:03d}" for i in range(40)]
    timestamps = pd.date_range("2025-12-01", "2025-12-08", freq="h")
    rows = []
    for ts in timestamps:
        for d in devices:
            rows.append({
                "timestamp": ts,
                "device_id": d,
                "temperature_c": round(20 + 5 * np.sin(ts.hour / 24 * 2 * np.pi) + rng.normal(0, 1.5), 2),
                "humidity_pct": round(rng.uniform(35, 70), 1),
                "vibration_g": round(rng.gamma(1.2, 0.3), 3),
                "alarm": int(rng.random() < 0.012),
            })
    _save(pd.DataFrame(rows), "13_iot_sensor")


def ds14_titanic() -> None:
    """Tiny classic so the eval includes a well-known shape."""
    rng = np.random.default_rng(14)
    n = 891
    df = pd.DataFrame(
        {
            "PassengerId": np.arange(1, n + 1),
            "Survived": rng.choice([0, 1], n, p=[0.62, 0.38]),
            "Pclass": rng.choice([1, 2, 3], n, p=[0.24, 0.21, 0.55]),
            "Sex": rng.choice(["male", "female"], n, p=[0.65, 0.35]),
            "Age": np.where(
                rng.random(n) < 0.20,
                np.nan,
                np.clip(rng.normal(29.7, 14.5, n), 0.5, 80).round(1),
            ),
            "SibSp": rng.integers(0, 5, n),
            "Parch": rng.integers(0, 4, n),
            "Fare": np.round(np.clip(rng.gamma(1.5, 18.0, n), 4, 500), 4),
            "Embarked": rng.choice(["S", "C", "Q"], n, p=[0.72, 0.19, 0.09]),
        }
    )
    _save(df, "14_titanic")


def ds15_world_gdp() -> None:
    rng = np.random.default_rng(15)
    countries = ["中国", "美国", "日本", "德国", "印度", "英国", "法国", "巴西", "意大利", "加拿大", "韩国", "俄罗斯", "澳大利亚", "西班牙", "墨西哥"]
    rows = []
    base = {"中国": 18.0, "美国": 27.0, "日本": 4.2, "德国": 4.5, "印度": 3.7, "英国": 3.3, "法国": 3.0, "巴西": 2.1, "意大利": 2.0, "加拿大": 2.1, "韩国": 1.7, "俄罗斯": 2.0, "澳大利亚": 1.7, "西班牙": 1.6, "墨西哥": 1.8}
    growth = {"中国": 0.052, "美国": 0.025, "日本": 0.012, "德国": 0.014, "印度": 0.068, "英国": 0.018, "法国": 0.015, "巴西": 0.022, "意大利": 0.010, "加拿大": 0.020, "韩国": 0.025, "俄罗斯": 0.018, "澳大利亚": 0.022, "西班牙": 0.020, "墨西哥": 0.025}
    for year in range(2010, 2026):
        for c in countries:
            t = year - 2010
            gdp = base[c] * (1 + growth[c]) ** t * (1 + rng.normal(0, 0.025))
            rows.append({
                "country": c,
                "year": year,
                "gdp_trillion_usd": round(gdp, 3),
                "population_million": round(base[c] * 50 + rng.normal(0, 10), 1),
                "continent": {"中国": "亚洲", "美国": "北美", "日本": "亚洲", "德国": "欧洲", "印度": "亚洲", "英国": "欧洲", "法国": "欧洲", "巴西": "南美", "意大利": "欧洲", "加拿大": "北美", "韩国": "亚洲", "俄罗斯": "欧洲", "澳大利亚": "大洋洲", "西班牙": "欧洲", "墨西哥": "北美"}[c],
            })
    _save(pd.DataFrame(rows), "15_world_gdp")


ALL = [
    ds01_ecommerce_orders,
    ds02_hr_attrition,
    ds03_bank_transactions,
    ds04_hospital_admissions,
    ds05_student_scores,
    ds06_subway_ridership,
    ds07_air_quality,
    ds08_logistics_routes,
    ds09_telecom_churn,
    ds10_realestate_listings,
    ds11_movie_ratings,
    ds12_fitness_tracker,
    ds13_iot_sensor,
    ds14_titanic,
    ds15_world_gdp,
]


def main() -> None:
    for build in ALL:
        build()
        print(f"  ✓ {build.__name__}")
    print(f"\nDone — {len(ALL)} datasets written to {OUT}")


if __name__ == "__main__":
    main()
