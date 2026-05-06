"""Mock 模式：返回与设计稿 design-source/data.js 完全一致的演示数据。

用途：
1. 没有 API Key 时也能演示（评委、内部开发联调）
2. 离线 demo 视频录制
3. 单元测试
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator


# === 14 步 trace（与 data.js 一致）===
MOCK_TRACE_STEPS = [
    {"i": 1, "name": "接收用户问题", "group": "感知", "detail": "解析自然语言 + session 上下文(10轮)", "t": 12},
    {"i": 2, "name": "加载可用能力", "group": "感知", "detail": "工具集 8 项 · 数据集 6 张候选", "t": 28},
    {"i": 3, "name": "GraphRAG 社区检索", "group": "理解", "detail": "top-k=5 业务社区摘要命中：销售归因 / 区域结构", "t": 340, "badge": "GraphRAG"},
    {"i": 4, "name": "规划下一步动作", "group": "理解", "detail": "判定为多维归因任务 → 走 NL2SQL 主链路", "t": 88},
    {"i": 5, "name": "选择执行能力", "group": "理解", "detail": "Router 选定 sales_orders_2026 + fin_pnl_monthly", "t": 22},
    {"i": 6, "name": "实例语义解析", "group": "理解", "detail": "实体：'华南'、'Q1'、'环比' · 指标：成交额", "t": 46},
    {"i": 7, "name": "TTL 推理与补全", "group": "理解", "detail": "业务术语 → 字段：region_l1=south_china · period=2026Q1", "t": 71, "badge": "TTL"},
    {"i": 8, "name": "SQL 生成 · 尝试 1", "group": "执行", "detail": "JOIN 两张表 · 按 region × month × bu 切片", "t": 612, "badge": "Codegen"},
    {"i": 9, "name": "SQL 生成 · 尝试 2", "group": "执行", "detail": "校验失败：fin 表 month 字段为 string 需 cast", "t": 198, "status": "retry"},
    {"i": 10, "name": "SQL 生成 · 尝试 3", "group": "执行", "detail": "—", "t": 0, "status": "skip"},
    {"i": 11, "name": "SQL 生成 · 尝试 4", "group": "执行", "detail": "—", "t": 0, "status": "skip"},
    {"i": 12, "name": "执行 SQL（DuckDB）", "group": "执行", "detail": "扫描 482,103 行 → 返回 84 行聚合", "t": 1340},
    {"i": 13, "name": "检查查询结果", "group": "校验", "detail": "Critic：行数合理、无空值、数值在历史 IQR 范围内", "t": 122},
    {"i": 14, "name": "组装结论 + 选图 + 引用", "group": "输出", "detail": "选定双轴折线 + 同比柱形 · 触发异常洞察 2 条", "t": 410},
]

# 6 个数据集（与设计稿一致）
MOCK_DATASETS = [
    {"id": "ds_emp", "name": "employee_analytics", "source": "datahub", "rows": 17234, "cols": 28, "updated": "2 小时前", "desc": "员工技能 / 认证 / BU 分布", "icon": "👥"},
    {"id": "ds_sale", "name": "sales_orders_2026", "source": "mysql", "rows": 482103, "cols": 19, "updated": "12 分钟前", "desc": "订单明细（电信集采 + ToB）", "icon": "💼"},
    {"id": "ds_fin", "name": "fin_pnl_monthly", "source": "starrocks", "rows": 8924, "cols": 24, "updated": "今天 09:00", "desc": "财务损益（部门 × 月）", "icon": "💰"},
    {"id": "ds_op", "name": "operator_arpu", "source": "datahub", "rows": 2841092, "cols": 12, "updated": "1 小时前", "desc": "运营商用户 ARPU 月度", "icon": "📡"},
    {"id": "ds_ticket", "name": "service_tickets", "source": "api", "rows": 91204, "cols": 16, "updated": "实时", "desc": "客服工单（含 SLA）", "icon": "🎫"},
    {"id": "ds_cust", "name": "b2b_customers.csv", "source": "file", "rows": 3201, "cols": 9, "updated": "刚刚", "desc": "上传文件", "icon": "📄"},
]

# 7 条历史
MOCK_HISTORY = [
    {"id": "c1", "title": "Q1 销售归因：为什么华南掉了 12%", "time": "刚刚", "active": True, "mode": "business"},
    {"id": "c2", "title": "HR 月度复盘 · 2026/04", "time": "昨天", "mode": "business"},
    {"id": "c3", "title": "运营商 ARPU 异常排查", "time": "昨天", "mode": "expert"},
    {"id": "c4", "title": "工单 SLA 达成率拉升路径", "time": "前天", "mode": "business"},
    {"id": "c5", "title": "财务 P&L · 部门偏差", "time": "5/1", "mode": "expert"},
    {"id": "c6", "title": "员工技能矩阵 × BU", "time": "4/30", "mode": "expert"},
    {"id": "c7", "title": "客户流失 7 日早期信号", "time": "4/29", "mode": "business"},
]

# 5 个看板
MOCK_DASHBOARDS = [
    {"id": "g1", "title": "Q1 销售归因 · 华南", "subtitle": "来自 c1 · 钉于 5 分钟前", "owner": "巧玲", "followers": 4, "refresh": "每日 09:00"},
    {"id": "g2", "title": "HR 月度复盘 · 2026/04", "subtitle": "来自 c2 · 钉于 1 小时前", "owner": "巧玲", "followers": 7, "refresh": "每月 1 号"},
    {"id": "g3", "title": "财务 P&L · 部门偏差", "subtitle": "来自 c5 · 钉于昨天", "owner": "巧玲", "followers": 3, "refresh": "每周一 08:00"},
]

# 7 个对话场景完整答案（与 data.js conversations 对齐）
MOCK_CONVERSATIONS = {
    "c1": {
        "title": "Q1 销售归因：为什么华南掉了 12%",
        "keywords": ["销售", "华南", "Q1", "区域", "区", "归因", "下滑", "成交"],
        "answer": {
            "business": "华南区 Q1 同比下滑 12%，主因是 BU-3 的客户经理流失（−18%）拖累签单链路；建议本季度优先稳定 BU-3 团队、并将渠道激励向直销倾斜。",
            "expert": "华南区 q1_2026 vs q1_2025 同比 −12.0%（1116 vs 1268，单位万元）。下钻 BU 维度：BU-3 贡献度从 32% → 22%（−10pp），与 BU-3 客户经理流失率 r=0.81 强相关。突变点：2026-01。",
        },
        "followups": {
            "business": ["华南为什么 BU-3 客户经理流失？", "对比西南区抓手", "生成完整复盘报告"],
            "expert": ["改 SQL 加 channel 维度", "导出 Notebook", "下钻到 BU-3 客户级"],
        },
        "charts": [
            {"kind": "bars", "title": "Q1 区域成交额对比 · 同比", "subtitle": "单位万元 · 红=负增长", "data": [
                {"region": "华东", "q1_2025": 1820, "q1_2026": 1934, "delta": 6.3},
                {"region": "华北", "q1_2025": 1402, "q1_2026": 1516, "delta": 8.1},
                {"region": "华南", "q1_2025": 1268, "q1_2026": 1116, "delta": -12.0},
                {"region": "西南", "q1_2025": 891, "q1_2026": 962, "delta": 8.0},
                {"region": "华中", "q1_2025": 743, "q1_2026": 798, "delta": 7.4},
                {"region": "东北", "q1_2025": 412, "q1_2026": 401, "delta": -2.7},
            ]},
        ],
        "insights": [
            {"kind": "异常下跌", "text": "华南 Q1 同比 −12.0%，是六大区中唯一两位数下滑（IQR 离群）", "severity": "high"},
            {"kind": "强相关", "text": "华南成交额下滑与 BU-3 客户经理流失率（−18%）皮尔逊相关 r=0.81", "severity": "med"},
        ],
    },
    "c2": {
        "title": "HR 月度复盘 2026/04",
        "keywords": ["HR", "人力", "月报", "认证", "流动", "BU", "员工", "持证", "技能"],
        "answer": {
            "business": "4 月整体流动率 2.8%（同比 −0.3pp）；BU-2 / BU-5 人均产出环比 +6.4% 领跑，但 BU-3 认证密度仅 0.41 低于均线，建议本月安排 38 人补考。",
            "expert": "turnover_rate=2.8% (−0.3pp YoY) · cert_density: BU-2=0.71, BU-5=0.68, BU-3=0.41 (均线 0.55)。人均产出 BU-2 +6.4%, BU-5 +6.1% (环比), 与员工任期中位数 r=0.72。",
        },
        "followups": {
            "business": ["BU-3 认证缺口具体是哪些证书？", "Top 流失员工画像", "生成 HR 7 章月报"],
            "expert": ["按 manager_id 下钻", "导出员工明细 csv", "改用 cohort 分析"],
        },
        "charts": [
            {"kind": "bars", "title": "各 BU 认证密度 · 4月", "subtitle": "0–1 · 红=低于均线 0.55", "data": [
                {"region": "BU-1", "q1_2026": 0.62, "q1_2025": 0.55, "delta": 12.7},
                {"region": "BU-2", "q1_2026": 0.71, "q1_2025": 0.62, "delta": 14.5},
                {"region": "BU-3", "q1_2026": 0.41, "q1_2025": 0.48, "delta": -14.6},
                {"region": "BU-4", "q1_2026": 0.55, "q1_2025": 0.51, "delta": 7.8},
                {"region": "BU-5", "q1_2026": 0.68, "q1_2025": 0.61, "delta": 11.5},
                {"region": "BU-6", "q1_2026": 0.52, "q1_2025": 0.49, "delta": 6.1},
            ]},
        ],
        "insights": [
            {"kind": "认证短板", "text": "BU-3 认证密度 0.41 低于均线 0.55，38 人证书过期未续", "severity": "high"},
            {"kind": "正向", "text": "BU-2 / BU-5 人均产出环比 +6.4% / +6.1%，与任期中位数 r=0.72", "severity": "low"},
        ],
    },
    "c3": {
        "title": "运营商 ARPU 异常排查",
        "keywords": ["ARPU", "套餐", "迁移", "运营商", "5G", "4G", "用户"],
        "answer": {
            "business": "本月共检出 1,283 名异常下跌用户，集中在 5G 旧套餐迁移群组；其中 78% 在套餐变更后 30 天内 ARPU 下滑超 25%，建议优先针对该群组发起留存关怀。",
            "expert": "异常用户=1283 (−25% ARPU, 30d window post-migration)。Cohort: 5G_legacy_migration n=1647, hit_rate=78%。突变点 2026-03-15 与套餐 P-5G-99 下线时间一致 (Δ=2 天)。",
        },
        "followups": {
            "business": ["留存关怀话术怎么设计？", "高价值用户优先级", "推送给客户经理"],
            "expert": ["按 city_tier 切片", "对比 4G 迁移基线", "拉取 30d ARPU 序列"],
        },
        "charts": [
            {"kind": "bars", "title": "异常用户 × 迁移群组", "subtitle": "人数 · 红=异常 hit_rate >70%", "data": [
                {"region": "5G迁移", "q1_2026": 1001, "q1_2025": 412, "delta": 142.9},
                {"region": "4G留存", "q1_2026": 184, "q1_2025": 220, "delta": -16.4},
                {"region": "青年套餐", "q1_2026": 65, "q1_2025": 78, "delta": -16.7},
                {"region": "企业用户", "q1_2026": 33, "q1_2025": 41, "delta": -19.5},
            ]},
        ],
        "insights": [
            {"kind": "强相关", "text": "ARPU 下跌与套餐 P-5G-99 下线时间高度吻合（突变点偏差 2 天）", "severity": "high"},
            {"kind": "群组", "text": "5G_legacy_migration 群组 hit_rate=78%，是其他群组的 4-5 倍", "severity": "med"},
        ],
    },
    "c4": {
        "title": "工单 SLA 达成率",
        "keywords": ["工单", "SLA", "客服", "达成", "投诉", "满意度"],
        "answer": {
            "business": "近 30 天 SLA 整体达成率 92.4%，比上月 +1.8pp；P1 工单达成最低（87%），主要卡在网络故障类。建议增加 P1 自动派发规则、夜间值班双备份。",
            "expert": "SLA: P1=87.0%, P2=91.4%, P3=94.8%, P4=96.2%（n=2103）。P1 故障类工单 mean_resolution=5.8h (SLA=4h)，escalation_rate=12.4%。",
        },
        "followups": {
            "business": ["P1 故障的根因是什么？", "对比同行 SLA", "排夜班双值班的预算"],
            "expert": ["按 agent_id 排名", "拉取 P1 升级链路", "做 cohort week-over-week"],
        },
        "charts": [
            {"kind": "bars", "title": "各优先级 SLA 达成率", "subtitle": "百分比 · 红=低于均线 92.4%", "data": [
                {"region": "P1", "q1_2026": 87.0, "q1_2025": 85.5, "delta": 1.8},
                {"region": "P2", "q1_2026": 91.4, "q1_2025": 89.6, "delta": 2.0},
                {"region": "P3", "q1_2026": 94.8, "q1_2025": 93.2, "delta": 1.7},
                {"region": "P4", "q1_2026": 96.2, "q1_2025": 95.0, "delta": 1.3},
            ]},
        ],
        "insights": [
            {"kind": "瓶颈", "text": "P1 工单是 SLA 拖累项，故障类升级率 12.4%", "severity": "high"},
        ],
    },
    "c5": {
        "title": "财务 P&L 部门偏差",
        "keywords": ["财务", "预算", "超支", "P&L", "部门", "偏差", "成本"],
        "answer": {
            "business": "Q1 超支最严重的是研发部（+18.7%，超 1240 万），主因外包人力扩张；建议立即冻结非关键招聘、Q2 启动预算二次审议。",
            "expert": "research_dept Q1 actual=7892, budget=6650, variance=+1242 (+18.7%)。category 拆分：外包+892, 设备+261, 人力+89。其他 9 部门均在 ±5% 内。",
        },
        "followups": {
            "business": ["外包扩张是合理还是失控？", "其他部门有没有挪预算空间？", "做季度预算重审 SOP"],
            "expert": ["按 sub_dept 下钻", "对比 2025 同期", "导出预算 vs 实际明细"],
        },
        "charts": [
            {"kind": "bars", "title": "Q1 部门预算偏差率", "subtitle": "百分比 · 红=超支", "data": [
                {"region": "研发", "q1_2026": 18.7, "q1_2025": 5.2, "delta": 13.5},
                {"region": "销售", "q1_2026": 3.8, "q1_2025": 2.1, "delta": 1.7},
                {"region": "市场", "q1_2026": -2.4, "q1_2025": 1.0, "delta": -3.4},
                {"region": "客服", "q1_2026": 1.2, "q1_2025": 0.8, "delta": 0.4},
                {"region": "供应链", "q1_2026": -4.5, "q1_2025": -1.2, "delta": -3.3},
                {"region": "HR", "q1_2026": 0.5, "q1_2025": 0.0, "delta": 0.5},
            ]},
        ],
        "insights": [
            {"kind": "异常超支", "text": "研发部 Q1 超支 18.7%，远超公司均线 1.2%（IQR 离群）", "severity": "high"},
        ],
    },
    "c6": {
        "title": "员工技能矩阵 BU",
        "keywords": ["技能", "矩阵", "员工", "BU", "skill", "能力"],
        "answer": {
            "business": "AI/ML 技能在 BU-2 / BU-5 集中，占比 28-31%；BU-3 / BU-6 严重不足（<8%）。建议跨 BU 调动 12 人 + 启动针对性培训。",
            "expert": "AI/ML skill density: BU-2=31.2%, BU-5=28.4%, BU-1=15.6%, BU-4=12.0%, BU-3=7.8%, BU-6=6.5%（n=17234）。Cluster 分析：高/低 BU 间技能基尼系数 0.41。",
        },
        "followups": {
            "business": ["跨 BU 调动方案", "培训预算", "高潜员工识别"],
            "expert": ["技能 cosine 相似度", "导出 skill_tags 矩阵", "做 K-means 聚类"],
        },
        "charts": [
            {"kind": "bars", "title": "AI/ML 技能员工占比 × BU", "subtitle": "百分比", "data": [
                {"region": "BU-1", "q1_2026": 15.6, "q1_2025": 12.0, "delta": 30.0},
                {"region": "BU-2", "q1_2026": 31.2, "q1_2025": 25.4, "delta": 22.8},
                {"region": "BU-3", "q1_2026": 7.8, "q1_2025": 6.5, "delta": 20.0},
                {"region": "BU-4", "q1_2026": 12.0, "q1_2025": 10.5, "delta": 14.3},
                {"region": "BU-5", "q1_2026": 28.4, "q1_2025": 22.0, "delta": 29.1},
                {"region": "BU-6", "q1_2026": 6.5, "q1_2025": 5.8, "delta": 12.1},
            ]},
        ],
        "insights": [
            {"kind": "结构失衡", "text": "BU-3 / BU-6 AI/ML 技能不足 8%，建议跨 BU 调动 12 人", "severity": "med"},
        ],
    },
    "c8": {
        "title": "🌟 三表 JOIN：华南掉 12% 跨域归因",
        "keywords": ["三表", "JOIN", "跨表", "跨域", "跨数据集", "归因", "根因", "员工流动率", "BU-3 流失"],
        "answer": {
            "business": "华南区 Q1 同比下滑 12%，跨域归因发现：① BU-3 客户经理流失率 18%（员工分析数据集），② BU-3 销售贡献度 32%→22%（销售订单数据集），③ BU-3 预算执行偏差 +15%（财务损益数据集）。三个数据集交叉印证：人才流失 → 签单链路断 → 业绩下滑。建议优先稳定 BU-3 客户经理团队（年终留任激励 + 接续培训），同时把 Q2 渠道激励从 BU-3 直销转向更稳定的 BU-2 / BU-5。",
            "expert": "三表 JOIN 路径：sales_orders_2026 ⋈ employee_analytics ⋈ fin_pnl_monthly\n· 关联键：BU-3 (region_l1='south_china')\n· 关键发现：\n  - sales: q1_2025=405, q1_2026=246 (-39.3%)\n  - employee: BU-3 turnover=18% vs avg 2.8%\n  - fin: BU-3 variance=+15% (overspend on retention bonuses)\n· Pearson 相关：r(turnover, sales_drop)=0.81, p<0.01\n· 突变点：2026-01-15（BU-3 资深经理 Top3 同期离职）\n· 因果链强度：employee→sales→fin（不是 fin→sales→employee）",
        },
        "followups": {
            "business": ["哪些 BU-3 客户经理离职后没接续？", "对比西南区为什么没掉？", "生成跨域归因完整报告"],
            "expert": ["按 manager_id 下钻 BU-3 内部", "导出 employee × sales 关联明细 csv", "Granger 因果检验：流失→销售的时序滞后 N 月"],
        },
        "charts": [
            {"kind": "bars", "title": "BU-3 三个维度同时恶化", "subtitle": "跨 3 个数据集 · 同期对比", "data": [
                {"region": "员工流失率%", "q1_2025": 5, "q1_2026": 18, "delta": 260},
                {"region": "销售贡献度%", "q1_2025": 32, "q1_2026": 22, "delta": -31},
                {"region": "预算偏差%", "q1_2025": 3, "q1_2026": 15, "delta": 400},
                {"region": "签单数", "q1_2025": 145, "q1_2026": 89, "delta": -38.6},
                {"region": "客户满意度", "q1_2025": 4.5, "q1_2026": 3.6, "delta": -20},
            ]},
            {"kind": "line", "title": "BU-3 关键时间线（多数据集叠加）", "subtitle": "灰=员工流失 · 绿=销售 · 橙=财务偏差", "data": [
                {"m": "2025-10", "val": 145},
                {"m": "2025-11", "val": 138},
                {"m": "2025-12", "val": 132},
                {"m": "2026-01", "val": 95},
                {"m": "2026-02", "val": 78},
                {"m": "2026-03", "val": 89},
            ]},
        ],
        "insights": [
            {"kind": "🔥 跨域强相关", "text": "BU-3 客户经理流失率与销售贡献度负相关 r=-0.81（员工 × 销售两表）", "severity": "high"},
            {"kind": "📊 突变点对齐", "text": "2026-01-15 资深客户经理 Top3 离职 → 同月销售断崖（员工 × 销售时序对齐）", "severity": "high"},
            {"kind": "💰 财务连锁", "text": "BU-3 预算偏差 +15% 主因留任奖金 + 招聘外包，与销售下滑形成恶性循环（员工 × 财务）", "severity": "med"},
            {"kind": "🌐 全域诊断", "text": "三个数据集交叉印证同一根因（BU-3 人才链断）——任一单表分析都会漏掉", "severity": "med"},
        ],
    },
    "c7": {
        "title": "客户流失早期信号",
        "keywords": ["流失", "客户", "留存", "信号", "churn"],
        "answer": {
            "business": "近 7 天检出 28 个高流失风险客户，主要信号：合同到期 30 天内 + NPS<0 + 接触频率下降；建议本周客户成功团队主动接触。",
            "expert": "high_churn_risk=28 (n=500, 5.6%)。Top 信号：renewal_window<=30d (相关 r=0.68)、nps<0 (r=0.55)、last_contact>60d (r=0.42)。",
        },
        "followups": {
            "business": ["接触话术怎么说", "Top 客户案例", "本周动作清单"],
            "expert": ["训练 churn 预测模型", "导出客户名单", "做 Cox 生存分析"],
        },
        "charts": [
            {"kind": "bars", "title": "高流失风险客户 × 行业", "subtitle": "客户数", "data": [
                {"region": "电信", "q1_2026": 8, "q1_2025": 6, "delta": 33.3},
                {"region": "金融", "q1_2026": 6, "q1_2025": 5, "delta": 20.0},
                {"region": "政企", "q1_2026": 5, "q1_2025": 4, "delta": 25.0},
                {"region": "制造", "q1_2026": 4, "q1_2025": 4, "delta": 0.0},
                {"region": "零售", "q1_2026": 3, "q1_2025": 2, "delta": 50.0},
                {"region": "其他", "q1_2026": 2, "q1_2025": 3, "delta": -33.3},
            ]},
        ],
        "insights": [
            {"kind": "早期信号", "text": "续约窗口 ≤30 天 + NPS<0 是最强信号（r=0.68）", "severity": "high"},
        ],
    },
}


def _match_conversation(question: str) -> dict:
    """根据用户问题里的关键词匹配最合适的对话场景。

    匹配规则：含关键词数最多的优先；若都不匹配，返回 None 让外层用 fallback。
    """
    best_cid, best_score = None, 0
    for cid, c in MOCK_CONVERSATIONS.items():
        score = sum(1 for k in c.get("keywords", []) if k in question)
        if score > best_score:
            best_cid, best_score = cid, score
    return MOCK_CONVERSATIONS.get(best_cid) if best_score > 0 else None


def _generic_response(question: str, mode: str) -> dict:
    """无关键词匹配时的兜底答案——基于问题动态生成有意义的内容。

    Mock 模式下用关键词匹配 intent；真 LLM 模式下 intent 由 step_chart_pick 用 LLM 决定。
    """
    q_short = question[:50] + ("…" if len(question) > 50 else "")
    # 10-intent 关键词路由（与前端、后端 LLM 选图保持一致）
    has_delta   = any(k in question for k in ["同比", "环比", "增长", "下滑", "涨幅", "下降"])
    has_time    = any(k in question for k in ["趋势", "走势", "近", "月", "年", "天", "时序", "走"])
    has_share   = any(k in question for k in ["占比", "构成", "结构", "分布", "比例"])
    has_rank    = any(k in question for k in ["排行", "排名", "榜", "top", "前", "最高", "最低"])
    has_heatmap = any(k in question for k in ["热力", "矩阵", "交叉", "二维"])
    has_funnel  = any(k in question for k in ["漏斗", "转化", "流失", "阶段"])
    has_anomaly = any(k in question for k in ["异常", "突变", "离群", "预警", "风险"])
    has_compare = any(k in question for k in ["对比", "比较", "vs"])

    # 决定 intent + chart_kind
    if has_delta:        intent, chart_kind = "delta", "bars"
    elif has_time:       intent, chart_kind = "trend", "line"
    elif has_share:      intent, chart_kind = "share", "donut"
    elif has_rank:       intent, chart_kind = "rank", "bars"
    elif has_heatmap:    intent, chart_kind = "heatmap", "heat"
    elif has_funnel:     intent, chart_kind = "funnel", "bars"
    elif has_anomaly:    intent, chart_kind = "anomaly", "line"
    elif has_compare:    intent, chart_kind = "compare", "bars"
    else:                intent, chart_kind = "compare", "bars"

    if intent == "trend" or intent == "anomaly":
        chart_data = [
            {"m": "2025-10", "val": 412}, {"m": "2025-11", "val": 438},
            {"m": "2025-12", "val": 461}, {"m": "2026-01", "val": 392},
            {"m": "2026-02", "val": 358}, {"m": "2026-03", "val": 366},
        ]
        chart_title = f"近 6 月{'异常突变' if intent == 'anomaly' else '趋势'}（基于「{q_short}」）"
    elif intent == "share":
        chart_data = [
            {"region": "直销", "q1_2026": 42, "q1_2025": 0, "delta": 0},
            {"region": "渠道", "q1_2026": 28, "q1_2025": 0, "delta": 0},
            {"region": "线上", "q1_2026": 18, "q1_2025": 0, "delta": 0},
            {"region": "OEM",  "q1_2026": 12, "q1_2025": 0, "delta": 0},
        ]
        chart_title = f"结构占比（基于「{q_short}」）"
    elif intent == "heatmap":
        chart_data = [{"region": "BU-1", "q1_2026": 82, "q1_2025": 0, "delta": 0}]  # heat 不读 data
        chart_title = "维度交叉热力"
    elif intent == "delta":
        chart_data = [
            {"region": "维度 A", "q1_2025": 1820, "q1_2026": 1934, "delta": 6.3},
            {"region": "维度 B", "q1_2025": 1402, "q1_2026": 1516, "delta": 8.1},
            {"region": "维度 C", "q1_2025": 1268, "q1_2026": 1116, "delta": -12.0},
            {"region": "维度 D", "q1_2025": 891,  "q1_2026": 962,  "delta": 8.0},
            {"region": "维度 E", "q1_2025": 743,  "q1_2026": 798,  "delta": 7.4},
        ]
        chart_title = f"同环比对比（基于「{q_short}」）"
    elif intent == "rank":
        # 排行榜：单边数值（无对比基准）
        chart_data = [
            {"region": "客户 A", "q1_2026": 1934, "q1_2025": 0, "delta": 0},
            {"region": "客户 B", "q1_2026": 1722, "q1_2025": 0, "delta": 0},
            {"region": "客户 C", "q1_2026": 1516, "q1_2025": 0, "delta": 0},
            {"region": "客户 D", "q1_2026": 1268, "q1_2025": 0, "delta": 0},
            {"region": "客户 E", "q1_2026": 962,  "q1_2025": 0, "delta": 0},
        ]
        chart_title = f"Top 排行（基于「{q_short}」）"
    elif intent == "funnel":
        # 漏斗：阶段递减
        chart_data = [
            {"region": "曝光",   "q1_2026": 10000, "q1_2025": 0, "delta": 0},
            {"region": "点击",   "q1_2026": 4200,  "q1_2025": 0, "delta": 0},
            {"region": "加购",   "q1_2026": 1850,  "q1_2025": 0, "delta": 0},
            {"region": "下单",   "q1_2026": 920,   "q1_2025": 0, "delta": 0},
            {"region": "支付",   "q1_2026": 780,   "q1_2025": 0, "delta": 0},
        ]
        chart_title = f"转化漏斗（基于「{q_short}」）"
    else:  # compare 默认
        chart_data = [
            {"region": "维度 A", "q1_2025": 120, "q1_2026": 145, "delta": 20.8},
            {"region": "维度 B", "q1_2025": 95,  "q1_2026": 108, "delta": 13.7},
            {"region": "维度 C", "q1_2025": 78,  "q1_2026": 82,  "delta": 5.1},
            {"region": "维度 D", "q1_2025": 65,  "q1_2026": 58,  "delta": -10.8},
            {"region": "维度 E", "q1_2025": 42,  "q1_2026": 51,  "delta": 21.4},
        ]
        chart_title = f"维度对比（基于「{q_short}」）"

    return {
        "title": q_short,
        "answer": {
            "business": (
                f"针对您的问题「{q_short}」——\n\n"
                f"基于 15 个企业数据集和 130+ 业务术语词典分析，AI 选图意图：{intent}。"
                f"\n\n下面图表展示了相关维度的初步数据。如需更精确分析，建议切换到真实 LLM 模式（5/6 内网验证），"
                f"或点击右侧追问 chip 探索 7 个预置真实场景。\n\n"
                f"💡 提示：本回答由 Mock 模式生成，演示阶段路由准确率受限于关键词匹配。"
            ),
            "expert": (
                f"Question parsed: '{q_short}'\n"
                f"Intent (10 categories): {intent}\n"
                f"Chart kind selected: {chart_kind}\n"
                f"Available datasets: 15 (HR×1, sales×2, finance×1, operator×4, retail×2, industry×5)\n"
                f"Routing decision: fallback to generic response (no exact keyword match in c1-c8)\n"
                f"In Real mode, this would route to LLM for: NL parsing → schema discovery → SQL gen → execute → chart\n"
                f"Sample chart data shown below."
            ),
        },
        "followups": {
            "business": [
                "Q1 销售归因",
                "HR 月度复盘",
                "财务 P&L 部门偏差",
                "运营商 ARPU 异常",
            ],
            "expert": [
                "切真实 LLM 模式",
                "查看支持的业务术语",
                "导出可分析数据集列表",
            ],
        },
        "charts": [
            {"kind": chart_kind, "title": chart_title, "subtitle": "Mock 演示数据",
             "data": chart_data, "intent": intent, "_picked_by": "mock_keyword"},
        ],
        "insights": [
            {"kind": "💡 提示", "text": f"问题「{q_short}」未直接命中预置场景关键词。Mock 模式下展示通用模板，真实 LLM 模式下会基于 schema + GraphRAG 精准路由", "severity": "low"},
            {"kind": "🎯 路径", "text": "尝试问句包含：'销售'、'HR'、'ARPU'、'工单'、'财务'、'技能'、'流失'等关键词可命中真实场景", "severity": "low"},
        ],
    }

MOCK_CITATION = {
    "datasets": ["sales_orders_2026", "fin_pnl_monthly"],
    "columns": ["order_id", "region_l1", "bu_id", "amount", "order_date", "period"],
    "sql": """SELECT region_l1 AS region,
       SUM(CASE WHEN period='2025Q1' THEN amount END) AS q1_2025,
       SUM(CASE WHEN period='2026Q1' THEN amount END) AS q1_2026
FROM sales_orders_2026 s
JOIN fin_pnl_monthly f
  ON s.bu_id = f.bu_id
 AND CAST(f.month AS INT) = EXTRACT(MONTH FROM s.order_date)
WHERE period IN ('2025Q1','2026Q1')
GROUP BY region_l1
ORDER BY q1_2026 DESC;""",
    "rows": 84,
    "sample": [
        {"region": "华南", "q1_2025": 1268, "q1_2026": 1116, "delta_pct": -12.0},
        {"region": "华东", "q1_2025": 1820, "q1_2026": 1934, "delta_pct": 6.3},
        {"region": "华北", "q1_2025": 1402, "q1_2026": 1516, "delta_pct": 8.1},
    ],
}


# 三表 JOIN 杀手级场景的 citation
MOCK_CITATION_TRIPLE_JOIN = {
    "datasets": ["sales_orders_2026", "employee_analytics", "fin_pnl_monthly"],
    "columns": ["s.bu_id", "s.amount", "s.period", "e.is_active", "e.bu_id", "e.tenure_years", "f.budget", "f.actual", "f.variance_pct"],
    "sql": """-- 三表 JOIN：销售 × 员工 × 财务
WITH sales_by_bu AS (
    SELECT bu_id, region_l1,
           SUM(CASE WHEN period='2025Q1' THEN amount END) AS q1_2025_sales,
           SUM(CASE WHEN period='2026Q1' THEN amount END) AS q1_2026_sales
    FROM sales_orders_2026
    WHERE region_l1 = '华南'
    GROUP BY bu_id, region_l1
),
emp_turnover AS (
    SELECT bu_id,
           AVG(CASE WHEN is_active = 0 THEN 1.0 ELSE 0.0 END) AS turnover_rate,
           COUNT(*) FILTER (WHERE tenure_years > 3 AND is_active = 0) AS senior_lost
    FROM employee_analytics
    WHERE region = '华南'
    GROUP BY bu_id
),
fin_variance AS (
    SELECT dept_id AS bu_id,
           AVG(variance_pct) AS avg_variance_pct,
           SUM(actual) - SUM(budget) AS total_overspend
    FROM fin_pnl_monthly
    WHERE year = 2026 AND month <= 3
    GROUP BY dept_id
)
SELECT s.bu_id,
       s.q1_2025_sales, s.q1_2026_sales,
       (s.q1_2026_sales - s.q1_2025_sales) / s.q1_2025_sales * 100 AS sales_delta_pct,
       e.turnover_rate * 100 AS turnover_pct,
       e.senior_lost,
       f.avg_variance_pct AS budget_variance_pct
FROM sales_by_bu s
LEFT JOIN emp_turnover e ON s.bu_id = e.bu_id
LEFT JOIN fin_variance f ON s.bu_id = f.bu_id
ORDER BY sales_delta_pct ASC;""",
    "rows": 6,
    "sample": [
        {"bu_id": "BU-3", "q1_2025_sales": 405, "q1_2026_sales": 246, "sales_delta_pct": -39.3, "turnover_pct": 18.0, "senior_lost": 3, "budget_variance_pct": 15.2},
        {"bu_id": "BU-1", "q1_2025_sales": 280, "q1_2026_sales": 268, "sales_delta_pct": -4.3, "turnover_pct": 3.2, "senior_lost": 0, "budget_variance_pct": 2.1},
        {"bu_id": "BU-2", "q1_2025_sales": 215, "q1_2026_sales": 232, "sales_delta_pct": 7.9, "turnover_pct": 2.4, "senior_lost": 0, "budget_variance_pct": -1.2},
    ],
    "join_path": [
        {"step": 1, "from": "sales_orders_2026", "to": "employee_analytics", "on": "bu_id", "type": "LEFT JOIN"},
        {"step": 2, "from": "(sales × employee)", "to": "fin_pnl_monthly", "on": "bu_id = dept_id", "type": "LEFT JOIN"},
    ],
    "join_strategy_explanation": "AI 自动发现：用户问到'流动率'但 sales 表无该字段 → 推断需要 employee 表；问到'预算' → 推断需要 fin 表。三表通过 bu_id 公共键 JOIN，关联 6 个 BU 的全维度数据。",
}


async def mock_stream(question: str, mode: str, message_id: str) -> AsyncIterator[dict]:
    """以 SSE 事件流推送 mock 对话。

    路由策略：
    1. 用关键词匹配 7 个预置对话（c1-c7）
    2. 都不匹配 → 通用 fallback 回答（含"切到 Real 模式"提示）
    """
    matched = _match_conversation(question)
    print(f"\n[MOCK_STREAM] question={question!r}  mode={mode}  matched={matched.get('title') if matched else 'None (use fallback)'}\n", flush=True)
    conv = matched or _generic_response(question, mode)

    # 14 步推流式
    for s in MOCK_TRACE_STEPS:
        yield {
            "type": "trace_step",
            "i": s["i"], "name": s["name"], "group": s["group"],
            "detail": s["detail"], "badge": s.get("badge"),
            "status": "running",
        }
        await asyncio.sleep(min(0.28, 0.08 + s.get("t", 0) / 8000))
        yield {
            "type": "trace_step",
            "i": s["i"], "status": s.get("status", "done"),
            "duration_ms": s.get("t", 0),
        }

    # 图表
    for ch in conv.get("charts", []):
        yield {"type": "chart", **ch}

    # 异常洞察
    for ins in conv.get("insights", []):
        yield {"type": "insight", **ins}

    # 引用：三表 JOIN 场景用专属 citation；其他用通用
    is_triple_join = matched and matched.get("title", "").startswith("🌟 三表 JOIN")
    citation = MOCK_CITATION_TRIPLE_JOIN if is_triple_join else MOCK_CITATION
    yield {"type": "citation", **citation}

    # 追问
    yield {"type": "followups", **conv.get("followups", {})}

    # 答案逐字流
    answer = conv["answer"][mode]
    for i in range(0, len(answer), 3):
        yield {"type": "answer_chunk", "mode": mode, "text": answer[i:i + 3]}
        await asyncio.sleep(0.02)

    yield {"type": "complete", "message_id": message_id}
