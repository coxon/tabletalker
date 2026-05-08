"""异常检测算法 · 工业级实现。

5 种检测方法：
1. IQR 离群（单变量）— 经典统计法
2. Z-Score 异常 — 标准正态假设
3. STL 分解残差异常 — 时间序列趋势 + 季节性分离后的残差检测（类 Prophet）
4. Pearson 强相关 — 跨变量关联
5. 单调突变（CUSUM 简化版）— 时间序列突变点

设计原则：
- 不引入重型依赖（statsmodels 可选 import，未装时降级）
- 每个方法独立可调阈值
- 输出含 severity、evidence、algorithm 来源（可追溯）
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class Insight:
    kind: str
    text: str
    severity: str           # low / med / high
    algorithm: str          # 标记是哪个算法发现的
    evidence: dict          # 数值证据，便于追溯
    column: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ============ 1. IQR 离群（单变量）============

def detect_iqr_outliers(df: pd.DataFrame, col: str, k: float = 1.5) -> Optional[Insight]:
    s = df[col].dropna()
    if len(s) < 4:
        return None
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    lower, upper = q1 - k * iqr, q3 + k * iqr
    outliers = s[(s < lower) | (s > upper)]
    if len(outliers) == 0:
        return None
    severity = "high" if len(outliers) / len(s) > 0.1 else "med"
    return Insight(
        kind="离群异常",
        text=f"{col} 列检出 {len(outliers)} 个离群值（占 {len(outliers)/len(s)*100:.1f}%），范围 [{lower:.2f}, {upper:.2f}] 之外",
        severity=severity,
        algorithm="IQR (k=1.5)",
        column=col,
        evidence={"q1": round(q1, 4), "q3": round(q3, 4), "iqr": round(iqr, 4),
                  "n_outliers": int(len(outliers)), "n_total": int(len(s)),
                  "outlier_values": outliers.head(5).tolist()},
    )


# ============ 2. Z-Score 异常 ============

def detect_zscore_anomalies(df: pd.DataFrame, col: str, threshold: float = 3.0) -> Optional[Insight]:
    s = df[col].dropna()
    if len(s) < 5:
        return None
    mu, sigma = s.mean(), s.std()
    if sigma == 0:
        return None
    z = (s - mu) / sigma
    extreme = z[z.abs() > threshold]
    if len(extreme) == 0:
        return None
    severity = "high" if z.abs().max() > 4 else "med"
    return Insight(
        kind="统计异常",
        text=f"{col} 列检出 {len(extreme)} 个超 {threshold}σ 极端值（最大 z={z.abs().max():.2f}σ）",
        severity=severity,
        algorithm=f"Z-Score (threshold={threshold}σ)",
        column=col,
        evidence={"mean": round(mu, 4), "std": round(sigma, 4),
                  "max_z": round(z.abs().max(), 4),
                  "n_anomalies": int(len(extreme))},
    )


# ============ 3. STL 残差异常（类 Prophet）============

def detect_stl_residual_anomalies(df: pd.DataFrame, time_col: str, value_col: str,
                                   period: int = 7, threshold: float = 2.5) -> Optional[Insight]:
    """对时间序列做 STL 分解（trend + seasonal + residual），检测残差异常。

    类似 Facebook Prophet 的检测逻辑，但用 statsmodels 简化实现。
    statsmodels 未装时降级为简单趋势线减法。
    """
    s = df[[time_col, value_col]].dropna().sort_values(time_col).reset_index(drop=True)
    if len(s) < period * 2:
        return None
    series = s[value_col].astype(float).values

    try:
        from statsmodels.tsa.seasonal import STL
        stl_period = min(period, len(series) // 2)
        stl = STL(series, period=stl_period, robust=True).fit()
        residual = stl.resid
    except Exception:
        # 降级：简单移动平均作为 trend
        window = min(7, len(series) // 3)
        trend = pd.Series(series).rolling(window=window, center=True, min_periods=1).mean().values
        residual = series - trend

    res_mean, res_std = np.nanmean(residual), np.nanstd(residual)
    if res_std == 0:
        return None
    z = np.abs((residual - res_mean) / res_std)
    n_anomalies = int(np.sum(z > threshold))
    if n_anomalies == 0:
        return None

    severity = "high" if n_anomalies / len(series) > 0.05 else "med"
    return Insight(
        kind="时序残差异常",
        text=f"{value_col} 时间序列分解后残差检出 {n_anomalies} 个异常点（>{threshold}σ），可能是非季节性事件冲击",
        severity=severity,
        algorithm=f"STL decomposition (period={period}, residual {threshold}σ)",
        column=value_col,
        evidence={"n_points": int(len(series)),
                  "n_anomalies": n_anomalies,
                  "max_residual_z": round(float(z.max()), 4)},
    )


# ============ 4. 强相关检测 ============

def detect_strong_correlations(df: pd.DataFrame, abs_threshold: float = 0.7,
                               max_pairs: int = 3) -> List[Insight]:
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] < 2:
        return []
    insights = []
    corr = numeric.corr(method="pearson")
    cols = corr.columns.tolist()
    seen = set()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = corr.iloc[i, j]
            if pd.isna(r) or abs(r) < abs_threshold:
                continue
            key = tuple(sorted([cols[i], cols[j]]))
            if key in seen:
                continue
            seen.add(key)
            sign = "正" if r > 0 else "负"
            severity = "high" if abs(r) > 0.85 else "med"
            insights.append(Insight(
                kind="强相关",
                text=f"{cols[i]} 与 {cols[j]} 呈强{sign}相关（Pearson r={r:.3f}）",
                severity=severity,
                algorithm="Pearson correlation",
                evidence={"col_a": cols[i], "col_b": cols[j],
                          "r": round(float(r), 4),
                          "abs_r": round(float(abs(r)), 4)},
            ))
            if len(insights) >= max_pairs:
                return insights
    return insights


# ============ 5. CUSUM 突变点 ============

def detect_cusum_changepoints(df: pd.DataFrame, time_col: str, value_col: str,
                               threshold_sigma: float = 2.0) -> Optional[Insight]:
    """CUSUM 累积和检测突变点（前后均值差超过阈值σ）。"""
    s = df[[time_col, value_col]].dropna().sort_values(time_col).reset_index(drop=True)
    if len(s) < 6:
        return None
    series = s[value_col].astype(float).values
    n = len(series)

    best_diff = 0.0
    best_idx = -1
    for cut in range(2, n - 2):
        left, right = series[:cut], series[cut:]
        diff = abs(np.mean(left) - np.mean(right))
        if diff > best_diff:
            best_diff = diff
            best_idx = cut

    if best_idx < 0:
        return None
    sigma = np.std(series)
    if sigma == 0 or best_diff < threshold_sigma * sigma:
        return None

    when = s.iloc[best_idx][time_col]
    severity = "high" if best_diff > 3 * sigma else "med"
    return Insight(
        kind="突变点",
        text=f"{value_col} 在 {when} 出现单调突变：前后均值差 {best_diff/sigma:.2f}σ",
        severity=severity,
        algorithm="CUSUM (threshold 2σ)",
        column=value_col,
        evidence={"changepoint_at": str(when),
                  "diff_in_sigma": round(float(best_diff / sigma), 4),
                  "before_mean": round(float(np.mean(series[:best_idx])), 4),
                  "after_mean": round(float(np.mean(series[best_idx:])), 4)},
    )


# ============ 主入口：组合所有检测 ============

def detect_all(df: Optional[pd.DataFrame], time_cols_hint: Optional[List[str]] = None,
                max_insights: int = 5) -> List[Insight]:
    """跑所有异常检测，返回合并后 top-N 洞察（按 severity 排序）。"""
    if df is None or len(df) == 0:
        return []
    insights: List[Insight] = []
    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    # IQR + Z-Score（每列一次）
    for col in numeric_cols[:5]:   # 限前 5 列防爆炸
        if (i := detect_iqr_outliers(df, col)):
            insights.append(i)
        if (i := detect_zscore_anomalies(df, col)):
            insights.append(i)

    # 时间序列检测（如果有 time-like 列）
    time_cols = time_cols_hint or [c for c in df.columns
                                   if any(k in c.lower() for k in ["date", "month", "time", "year", "_at", "ts"])]
    if time_cols:
        tc = time_cols[0]
        for vc in numeric_cols[:3]:
            if vc != tc:
                if (i := detect_stl_residual_anomalies(df, tc, vc)):
                    insights.append(i)
                if (i := detect_cusum_changepoints(df, tc, vc)):
                    insights.append(i)

    # 跨变量相关
    insights.extend(detect_strong_correlations(df))

    # 按 severity 排序：high > med > low
    severity_rank = {"high": 0, "med": 1, "low": 2}
    insights.sort(key=lambda i: severity_rank.get(i.severity, 3))

    return insights[:max_insights]
