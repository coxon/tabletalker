"""Agent 各原子步骤的实现。

当前为 P0 骨架：每个函数都有 fallback 实现，能让端到端流程跑通；
真实 LLM/GraphRAG/TTL 在后续日子逐步替换。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from loguru import logger

from llm.adapter import chat_complete


def _parse_json_tolerant(raw: str) -> dict:
    """容忍 markdown 包裹 / 前后空白 / 多余文本的 JSON 解析。

    亚信网关上不同模型对 json_mode 的遵守程度不同：
    - qwen / deepseek 通常返回纯 JSON
    - MiniMax 可能返回 ```json\\n{...}\\n``` 或前后带解释文字
    """
    if not raw:
        raise ValueError("LLM 返回为空字符串")
    # 先抓最外层 { ... }（贪婪匹配，跨行）
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        return json.loads(m.group())
    # 兜底：直接试一次
    return json.loads(raw)


# -------------- F-AG-01 Router --------------

ROUTER_PROMPT = """你是数据集路由器。用户问题：
{question}

可选数据集：
{candidates}

请输出 JSON：{{"datasets": ["..."], "reason": "..."}}
只选最相关的 1~3 个数据集。"""


async def step_router(question: str, dataset_hint: str | None = None) -> list[str]:
    if dataset_hint:
        return [dataset_hint]

    schemas_path = Path(os.getenv("SCHEMAS_FILE", "./schemas.json"))
    if not schemas_path.exists():
        # fallback：返回所有候选
        return ["sales_orders_2026", "fin_pnl_monthly"]

    schemas = json.loads(schemas_path.read_text())
    candidates = "\n".join(
        f"- {name}: {s.get('description', '无描述')} | 字段：{[c['name'] for c in s.get('columns', [])[:8]]}"
        for name, s in schemas.items()
    )
    try:
        resp = await chat_complete(
            messages=[
                {"role": "system", "content": "你是严谨的数据集路由器。"},
                {"role": "user", "content": ROUTER_PROMPT.format(question=question, candidates=candidates)},
            ],
            task="router",
            json_mode=True,
            max_tokens=200,
        )
        return _parse_json_tolerant(resp).get("datasets", [])
    except Exception as e:
        logger.warning(f"router LLM call failed: {e}, fallback to all")
        return list(schemas.keys())[:2]


# -------------- F-AG-02 GraphRAG --------------

_GRAPHRAG_INDEX = None


def _load_graphrag_index():
    """懒加载 GraphRAG 索引（从 ./graphrag_index.json）。"""
    global _GRAPHRAG_INDEX
    if _GRAPHRAG_INDEX is not None:
        return _GRAPHRAG_INDEX
    p = Path(os.getenv("GRAPHRAG_INDEX", "./graphrag_index.json"))
    if p.exists():
        _GRAPHRAG_INDEX = json.loads(p.read_text())
        n_communities = len(_GRAPHRAG_INDEX.get("communities", []))
        logger.info(f"已加载 GraphRAG 索引：{p} (共 {n_communities} 个社区)")
    else:
        logger.warning(f"GraphRAG 索引不存在：{p}，step_graphrag 降级为关键词匹配")
        _GRAPHRAG_INDEX = {"communities": []}
    return _GRAPHRAG_INDEX


async def step_graphrag(question: str, top_k: int = 5) -> list[dict]:
    """检索社区摘要。

    基于 graphrag_index.json 中预构建的社区索引：
    1. 计算每个社区的关键词在 question 中的命中次数
    2. 数据集名命中 +2，典型问题片段命中 +1
    3. 返回 top-k 社区（含 summary + datasets + key_terms）
    4. 索引不存在时降级为关键词字典
    """
    idx = _load_graphrag_index()
    communities = idx.get("communities", [])

    if not communities:
        fallback_map = {
            "销售": {"community": "销售归因", "summary": "区域 + BU + 渠道结构"},
            "HR": {"community": "HR 月报", "summary": "认证密度 + 流动率 + 人均产出"},
            "ARPU": {"community": "运营商 ARPU", "summary": "套餐迁移 + 用户分层"},
            "工单": {"community": "客服 SLA", "summary": "首响应 + 升级率"},
        }
        return [v for k, v in fallback_map.items() if k in question][:top_k]

    scored = []
    for c in communities:
        terms = c.get("all_terms", []) + c.get("key_terms", [])
        score = sum(1 for t in terms if t and t in question)
        for ds in c.get("datasets", []):
            if ds in question:
                score += 2
        for q in c.get("typical_questions", []):
            common = sum(1 for ch in q[:6] if ch in question)
            if common >= 3:
                score += 1
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    top = scored[:top_k]
    return [
        {
            "community": c["name"],
            "id": c.get("id"),
            "summary": c["summary"],
            "datasets": c.get("datasets", []),
            "score": score,
        }
        for score, c in top
    ]


# -------------- F-AG-03 TTL 推理 --------------

_BUSINESS_TERMS = None


def _load_business_terms():
    """懒加载业务术语词典（从 ../business_terms.json）。"""
    global _BUSINESS_TERMS
    if _BUSINESS_TERMS is not None:
        return _BUSINESS_TERMS
    bt_path = Path(os.getenv("BUSINESS_TERMS_FILE", "./business_terms.json"))
    if bt_path.exists():
        _BUSINESS_TERMS = json.loads(bt_path.read_text())
        logger.info(f"已加载业务术语词典：{bt_path} (共 {sum(len(v) for v in _BUSINESS_TERMS.get('dataset_terms', {}).values())} 条)")
    else:
        logger.warning(f"业务术语词典不存在：{bt_path}，TTL 步骤降级为简易词典")
        _BUSINESS_TERMS = {"global_terms": {}, "dataset_terms": {}, "synonyms": {}}
    return _BUSINESS_TERMS


async def step_ttl(question: str, mode: str = "semantic") -> Any:
    """TTL 推理：业务术语 → 字段映射。

    基于 business_terms.json：
    - 全局术语（时间、区域）
    - 数据集术语（每个 dataset 的列别名 + 业务指标）
    - 同义词（让多种说法都能匹配）

    MVP：词典查找；V1：RDFLib SPARQL（决赛后接入）。
    """
    bt = _load_business_terms()
    matched_entities: list[str] = []
    completions: dict = {}

    # 1. 全局术语（时间、区域）
    for category, terms in bt.get("global_terms", {}).items():
        for term, mapping in terms.items():
            if term in question:
                matched_entities.append(term)
                completions[term] = mapping

    # 2. 数据集术语（遍历所有数据集）
    for dataset_name, terms in bt.get("dataset_terms", {}).items():
        for term, mapping in terms.items():
            if term in question:
                matched_entities.append(f"{dataset_name}:{term}")
                completions[term] = {**mapping, "_dataset": dataset_name}

    # 3. 同义词扩展（如用户问"营收"，扩展到"销售额"）
    for canonical, synonyms in bt.get("synonyms", {}).items():
        for syn in synonyms:
            if syn in question and canonical not in matched_entities:
                # 用同义词补充扫一次
                for ds_name, terms in bt.get("dataset_terms", {}).items():
                    if canonical in terms:
                        matched_entities.append(f"{ds_name}:{canonical}（同义于'{syn}'）")
                        completions[canonical] = {**terms[canonical], "_dataset": ds_name}
                        break

    if mode == "entities":
        return matched_entities
    return completions


# -------------- F-AG-04/05 CodeGen + 重试 --------------

CODEGEN_PROMPT = """你是数据分析师。基于以下信息生成 DuckDB SQL：

用户问题：{question}
选定数据集：{datasets}
语义补全：{semantic}
schema 摘要：
{schema}

要求：
1. 输出 JSON：{{"sql": "...", "explanation": "..."}}
2. SQL 必须可在 DuckDB 上直接执行
3. 表名直接使用数据集名
4. 不要 LIMIT，除非用户明确要求 Top N
5. **类型规则（最重要！违反这条会直接报错）**：
   - 字段类型在 schema 摘要里以 `name:type` 的形式给出
   - 如果某列是 `VARCHAR` 类型但内容像日期（如 order_date），DuckDB 函数会报 Binder Error
   - 必须先 CAST：`DATE_TRUNC('month', CAST(order_date AS DATE))` 而不是 `DATE_TRUNC('month', order_date)`
   - 数值列做聚合前如果是 VARCHAR 也要 CAST：`SUM(CAST(amount AS DOUBLE))`
6. "环比上期"含义：本期数值 vs 上一期数值 → 用 LAG 或 self-join 实现
7. "近 N 个月"：基于数据中最大日期向前推 N 个月（不是当前自然日期）
"""


async def step_codegen_with_retry(
    question: str,
    datasets: list[str],
    semantic: dict,
    max_retries: int = 4,
) -> tuple[str, int]:
    """生成 SQL，失败反思重试。返回 (最终 sql, 实际尝试次数)。"""
    schemas_path = Path(os.getenv("SCHEMAS_FILE", "./schemas.json"))
    schemas = json.loads(schemas_path.read_text()) if schemas_path.exists() else {}
    # 紧凑格式（比原来 list 字面量省 ~40% tokens）：
    # sales_orders_2026 (20 列):
    #   id:VARCHAR, order_date:VARCHAR, amount:DOUBLE, ...
    schema_text_parts = []
    for ds in datasets:
        cols = schemas.get(ds, {}).get("columns", [])
        col_strs = [f"{c['name']}:{c.get('dtype', '?')}" for c in cols]
        schema_text_parts.append(f"{ds} ({len(col_strs)} 列):\n  " + ", ".join(col_strs))
    schema_text = "\n".join(schema_text_parts)

    # ↓↓↓ 优化 #5（占位 / 待决赛前实现）：
    #   流式 codegen + 在线 JSON 解析 + 早停校验
    #   思路：用 chat_stream 逐 token 取，累积 buffer，发现 "sql": "..." 闭合后立刻
    #   开始 EXPLAIN 校验。校验通过即可中断 stream，节省后半段输出时间（~15-30s）
    #   未实现原因：JSON 流式解析 + 优雅取消 OpenAI stream 的代码量约 80 行，
    #   且非流式版本已经够稳。先把 #1-#4 的收益拿到，决赛前回头做 #5。
    #   tracking issue: 见 docs/optimization-roadmap.md（如需）
    last_error = None
    sql = ""
    for attempt in range(1, max_retries + 1):
        try:
            user_msg = CODEGEN_PROMPT.format(
                question=question,
                datasets=datasets,
                semantic=semantic,
                schema=schema_text,
            )
            if last_error:
                user_msg += f"\n\n上次错误：{last_error}\n请修正。"
            resp = await chat_complete(
                messages=[
                    {"role": "system", "content": "你是严谨的 SQL 工程师。"},
                    {"role": "user", "content": user_msg},
                ],
                task="codegen",
                json_mode=True,
                # 实测 SQL 一般 < 400 tokens，给 700 足够；max_tokens 砍半省 ~20s
                max_tokens=700,
            )
            sql = _parse_json_tolerant(resp).get("sql", "")

            # 静态校验：必须先把 CSV 的 schema 加载到一个新 in-memory DuckDB，
            # 否则任何引用真实表的 SQL 都会被误判为 Catalog Error。
            # 用 LIMIT 0 只拿 schema 不拿数据，校验非常快。
            val_con = duckdb.connect(":memory:")
            data_dir = Path(os.getenv("DATA_DIR", "./data"))
            for ds in datasets:
                csv = data_dir / f"{ds}.csv"
                if csv.exists():
                    val_con.execute(
                        f"CREATE TABLE {ds} AS SELECT * FROM read_csv_auto('{csv}') LIMIT 0"
                    )
            val_con.execute(f"EXPLAIN {sql}")
            return sql, attempt
        except Exception as e:
            last_error = str(e)[:300]
            logger.warning(f"codegen attempt {attempt} failed: {e}")

    return sql, max_retries


# -------------- F-AG-06 Sandbox 执行 --------------

async def step_sandbox_exec(sql: str, datasets: list[str]) -> tuple[pd.DataFrame | None, str | None]:
    """在 DuckDB 内执行 SQL，自动从 data/ 加载 CSV 为表。"""
    try:
        con = duckdb.connect(":memory:")
        data_dir = Path(os.getenv("DATA_DIR", "./data"))
        for ds in datasets:
            csv = data_dir / f"{ds}.csv"
            if csv.exists():
                con.execute(f"CREATE TABLE {ds} AS SELECT * FROM read_csv_auto('{csv}')")
        df = con.execute(sql).df()
        return df, None
    except Exception as e:
        logger.error(f"sandbox exec failed: {e}")
        return None, str(e)


# -------------- F-AG-08 Critic --------------

async def step_critic(df: pd.DataFrame | None) -> bool:
    """结果合理性检查。"""
    if df is None or len(df) == 0:
        return False
    # 简单检查：行数>0、列数>0、不全为 NaN
    if df.isnull().all().all():
        return False
    return True


# -------------- F-AG-07 LLM 选图 + 启发式兜底 --------------

CHART_PICK_PROMPT = """你是数据可视化专家。基于「问题」+「数据特征」选最合适的图表组合。

返回严格 JSON（不要任何解释文字）：
{{"intent":"<intent>","charts":[{{"kind":"<kind>","title":"<标题>","x_col":"<列名|null>","y_col":"<列名|null>","reason":"<一句话>"}}]}}

intent 取值（10 选 1）：
  delta     · 同比/环比/增长下滑
  trend     · 时间序列走势
  share     · 占比/构成
  rank      · 排行 Top N
  compare   · 多维度对比
  heatmap   · 二维交叉
  funnel    · 漏斗转化
  table     · 明细列表
  kpi_only  · 单一数值
  anomaly   · 异常诊断

kind 取值：bars / line / donut / heat / kpi / table / funnel
最多 3 张图，最少 1 张。优先用 KPI 卡 + 主图 组合。
负值/下滑要用 bars 红色，趋势必须 line，占比必须 donut。

现在的输入：
问题：{question}
列：{columns}
行数：{n_rows}
样本：{sample}
"""


async def step_chart_pick(
    df: pd.DataFrame | None,
    question: str,
    *,
    use_llm: bool = True,
) -> list[dict]:
    """让 LLM 决定 chart_type + intent；失败 fallback 到启发式。"""
    if df is None or len(df) == 0:
        return []

    cols = df.columns.tolist()
    n = len(df)
    sample = df.head(3).to_dict(orient="records")

    # ---------- A. 优先让 LLM 选 ----------
    if use_llm:
        try:
            from llm.adapter import chat_complete  # 项目原生 LLM 包装（5 模型路由 + 重试）
            prompt = CHART_PICK_PROMPT.format(
                question=question, columns=cols, n_rows=n, sample=sample
            )
            raw = await chat_complete(
                messages=[
                    {"role": "system", "content": "你是图表选型专家。返回严格 JSON，不要任何解释文字。"},
                    {"role": "user", "content": prompt},
                ],
                task="router",       # 用小模型（deepseek-v3.2）省成本省延迟
                max_tokens=400,
                temperature=0.0,     # 选图要确定性
                json_mode=True,      # 强制 JSON 输出
            )
            # 解析 JSON（兼容代码块 / 多余文本）
            import json, re
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                decision = json.loads(m.group())
                intent = decision.get("intent", "compare")
                picks = decision.get("charts", [])
                charts = []
                for p in picks[:3]:
                    ch = {
                        "kind": p.get("kind", "bars"),
                        "title": p.get("title", f"{cols[0]} × {cols[1] if len(cols) > 1 else ''}"),
                        "x_col": p.get("x_col"),
                        "y_col": p.get("y_col"),
                        "reason": p.get("reason", ""),
                        "_picked_by": "llm",
                    }
                    # 把数据塞回去（LLM 不返回数据，只返回选型）
                    if ch["kind"] == "table":
                        ch["data"] = df.head(50).to_dict(orient="records")
                    elif ch["kind"] == "line" and ch["x_col"] and ch["y_col"]:
                        ch["data"] = df[[ch["x_col"], ch["y_col"]]].head(50).to_dict(orient="records")
                    elif ch["kind"] in ("bars", "donut", "funnel"):
                        ch["data"] = df.head(30).to_dict(orient="records")
                    elif ch["kind"] == "kpi":
                        # KPI 卡：用最后一个数值列做主指标，多行时算 last vs prev 真 delta
                        nums = df.select_dtypes(include="number")
                        if len(nums.columns) == 0:
                            ch["kpi"] = {"value": None, "delta": None, "label": ch["title"], "sub": "无数值列"}
                        else:
                            col = nums.columns[-1]  # 通常 SUM/AVG 列在末尾
                            s = nums[col].dropna()
                            if len(s) == 0:
                                ch["kpi"] = {"value": None, "delta": None, "label": ch["title"], "sub": ""}
                            elif len(s) == 1:
                                ch["kpi"] = {"value": float(s.iloc[0]), "delta": None,
                                             "label": ch["title"], "sub": col}
                            else:
                                cur = float(s.iloc[-1])
                                prev = float(s.iloc[-2])
                                delta_pct = round(((cur - prev) / prev * 100), 1) if prev else 0
                                ch["kpi"] = {
                                    "value": cur,
                                    "delta": delta_pct,
                                    "label": ch["title"],
                                    "sub": f"上期 {prev:,.0f}",
                                }
                    elif ch["kind"] == "heat":
                        ch["data"] = df.head(50).to_dict(orient="records")
                    charts.append(ch)
                if charts:
                    # 把 intent 也带出去给前端 badge
                    charts[0]["intent"] = intent

                    # ===== 安全网：每种 intent 必须有它该有的"主图"，LLM 漏了就补 =====
                    INTENT_REQUIRED_KIND = {
                        "trend": "line",
                        "share": "donut",
                        "rank": "bars",
                        "compare": "bars",
                        "anomaly": "line",
                        "heatmap": "heat",
                        "funnel": "funnel",
                    }
                    required = INTENT_REQUIRED_KIND.get(intent)
                    if required and not any(c.get("kind") == required for c in charts):
                        nums_cols = df.select_dtypes(include="number").columns.tolist()
                        cat_cols = [c for c in df.columns if c not in nums_cols]
                        if nums_cols:
                            x_col = cat_cols[0] if cat_cols else df.columns[0]
                            y_col = nums_cols[-1]
                            new_ch = {
                                "kind": required,
                                "title": f"{y_col} · {x_col}",
                                "x_col": x_col,
                                "y_col": y_col,
                                "intent": intent,
                                "_picked_by": "post-fix",
                                "reason": f"{intent} 意图必须有 {required}，LLM 没给我自己补",
                            }
                            if required == "line":
                                new_ch["data"] = df[[x_col, y_col]].head(50).to_dict(orient="records")
                            elif required in ("bars", "donut", "funnel"):
                                new_ch["data"] = df.head(30).to_dict(orient="records")
                            elif required == "heat":
                                new_ch["data"] = df.head(50).to_dict(orient="records")
                            # 主图放最前面，最多保留 3 张
                            charts.insert(0, new_ch)
                            charts = charts[:3]
                            logger.info(f"[chart_pick] post-fix added {required} chart for intent={intent}")

                    # ===== KPI 卡如果是 None 就补一个真值（防止仍显示 "—"）=====
                    for c in charts:
                        if c.get("kind") == "kpi" and (c.get("kpi") is None or c["kpi"].get("value") is None):
                            nums = df.select_dtypes(include="number")
                            if len(nums.columns) and len(nums) > 0:
                                col = nums.columns[-1]
                                s = nums[col].dropna()
                                if len(s) >= 2:
                                    cur, prev = float(s.iloc[-1]), float(s.iloc[-2])
                                    c["kpi"] = {
                                        "value": cur,
                                        "delta": round((cur - prev) / prev * 100, 1) if prev else 0,
                                        "label": c.get("title", "结果"),
                                        "sub": f"上期 {prev:,.0f}",
                                    }
                                elif len(s) == 1:
                                    c["kpi"] = {"value": float(s.iloc[0]), "delta": None,
                                                "label": c.get("title", "结果"), "sub": col}
                    return charts
        except Exception as e:
            # LLM 失败不阻塞 trace，走启发式兜底
            print(f"[step_chart_pick] LLM fallback: {e}")

    # ---------- B. 启发式兜底（LLM 不可用 / 解析失败）----------
    time_cols = [c for c in cols if any(k in c.lower() for k in ["date", "month", "year", "time", "_at"])]
    q = (question or "").lower()

    # 关键词推断 intent
    intent = (
        "delta"     if any(k in q for k in ["同比", "环比", "增长", "下滑"]) else
        "trend"     if (time_cols or any(k in q for k in ["趋势", "走势"])) else
        "share"     if any(k in q for k in ["占比", "构成", "结构"]) else
        "rank"      if any(k in q for k in ["排行", "排名", "top", "前"]) else
        "anomaly"   if any(k in q for k in ["异常", "突变", "离群"]) else
        "kpi_only"  if (n == 1) else
        "compare"
    )

    charts = []
    if intent == "trend" and time_cols and len(cols) >= 2:
        charts.append({"kind": "line", "title": f"{cols[1]} 随时间变化",
                       "x_col": time_cols[0], "y_col": cols[1],
                       "data": df[[time_cols[0], cols[1]]].head(50).to_dict(orient="records"),
                       "intent": intent, "_picked_by": "heuristic"})
    elif intent == "share" and len(cols) >= 2:
        charts.append({"kind": "donut", "title": "结构占比",
                       "data": df.head(8).to_dict(orient="records"),
                       "intent": intent, "_picked_by": "heuristic"})
    elif intent == "kpi_only":
        nums = df.select_dtypes(include="number")
        if len(nums.columns) and len(nums) > 0:
            col = nums.columns[-1]
            s = nums[col].dropna()
            value = float(s.iloc[-1]) if len(s) else None
            delta = None
            if len(s) >= 2 and s.iloc[-2]:
                delta = round(((s.iloc[-1] - s.iloc[-2]) / s.iloc[-2] * 100), 1)
            charts.append({"kind": "kpi", "title": "结果",
                           "kpi": {"value": value, "delta": delta,
                                   "label": cols[0] if cols else "结果", "sub": col},
                           "intent": intent, "_picked_by": "heuristic"})
        else:
            charts.append({"kind": "kpi", "title": "结果",
                           "kpi": {"value": None, "delta": None, "label": "无数值列", "sub": ""},
                           "intent": intent, "_picked_by": "heuristic"})
    elif n <= 30 and len(cols) >= 2:
        charts.append({"kind": "bars", "title": f"{cols[0]} × {cols[1]}",
                       "data": df.head(30).to_dict(orient="records"),
                       "intent": intent, "_picked_by": "heuristic"})
    else:
        charts.append({"kind": "table", "title": "查询结果",
                       "data": df.head(50).to_dict(orient="records"),
                       "intent": intent, "_picked_by": "heuristic"})

    return charts[:3]


# -------------- F-AG-09 Summarize --------------

SUMM_PROMPT_BIZ = """你是企业数据分析师，请用商业语言总结：
问题：{question}
关键数据：{data_summary}
关键洞察：{insights}

要求：
- 1-3 句话讲清结论 + 1 句业务解读 + 1 句建议
- 100-200 字
- 不要技术术语
"""

SUMM_PROMPT_EXPERT = """你是数据工程师，请客观陈述结果：
问题：{question}
关键数据：{data_summary}

要求：
- 客观、含计算口径
- 50-150 字
- 不做主观判断
"""


async def step_summarize(
    question: str,
    df: pd.DataFrame | None,
    *,
    mode: str = "business",
    charts: list[dict] = None,
    insights: list[dict] = None,
) -> str:
    if df is None or len(df) == 0:
        return "未查询到数据。请检查问题表述或数据集是否正确。"

    data_summary = df.head(5).to_string()
    insights_text = "; ".join(i.get("text", "") for i in (insights or []))

    tpl = SUMM_PROMPT_BIZ if mode == "business" else SUMM_PROMPT_EXPERT
    user_msg = tpl.format(
        question=question,
        data_summary=data_summary,
        insights=insights_text,
    )
    try:
        return await chat_complete(
            messages=[
                {"role": "system", "content": "你是 Table-Talker 的总结引擎。"},
                {"role": "user", "content": user_msg},
            ],
            # business 模式之前误用 default（→qwen 60s+），改回 summary（→deepseek ~10s）
            task="summary_short" if mode == "expert" else "summary",
            max_tokens=400,
        )
    except Exception as e:
        logger.warning(f"summarize failed: {e}, fallback")
        return f"基于查询结果（{len(df)} 行），核心数据已展示在图表中。{insights_text}"


# -------------- F-AG-10 Anomaly Detector --------------

async def step_anomaly(df: pd.DataFrame | None) -> list[dict]:
    """异常 / 洞察识别。

    使用 agent.anomaly_detector 的工业级 5 算法组合：
      - IQR / Z-Score 单变量异常
      - STL 残差时序异常（类 Prophet）
      - CUSUM 突变点检测
      - Pearson 强相关
    """
    if df is None or len(df) < 3:
        return []
    try:
        from agent.anomaly_detector import detect_all
        insights = detect_all(df, max_insights=5)
        return [i.to_dict() for i in insights]
    except Exception as e:
        logger.warning(f"anomaly_detector 失败，降级简化版：{e}")
        # 降级路径
        out = []
        for col in df.select_dtypes(include="number").columns[:3]:
            s = df[col].dropna()
            if len(s) < 3:
                continue
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                outliers = s[(s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)]
                if len(outliers) > 0:
                    out.append({"kind": "异常", "text": f"{col} 有 {len(outliers)} 个离群值",
                                "severity": "med", "algorithm": "IQR (degraded)"})
        return out[:3]
