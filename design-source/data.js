// Table-Talker — mock data & shared constants
window.TT_DATA = {
  tagline: "Ask. See. Decide.",
  taglineCn: "对话即洞察",

  datasets: [
    { id: "ds_emp", name: "employee_analytics", source: "datahub", rows: 17234, cols: 28, updated: "2 小时前", desc: "员工技能 / 认证 / BU 分布", icon: "👥" },
    { id: "ds_sale", name: "sales_orders_2026", source: "mysql", rows: 482103, cols: 19, updated: "12 分钟前", desc: "订单明细（电信集采 + ToB）", icon: "💼" },
    { id: "ds_fin", name: "fin_pnl_monthly", source: "starrocks", rows: 8924, cols: 24, updated: "今天 09:00", desc: "财务损益（部门 × 月）", icon: "💰" },
    { id: "ds_op", name: "operator_arpu", source: "datahub", rows: 2841092, cols: 12, updated: "1 小时前", desc: "运营商用户 ARPU 月度", icon: "📡" },
    { id: "ds_ticket", name: "service_tickets", source: "api", rows: 91204, cols: 16, updated: "实时", desc: "客服工单（含 SLA）", icon: "🎫" },
    { id: "ds_cust", name: "b2b_customers.csv", source: "file", rows: 3201, cols: 9, updated: "刚刚", desc: "上传文件", icon: "📄" },
  ],

  // Conversation history shown in left rail
  history: [
    { id: "c1", title: "Q1 销售归因：为什么华南掉了 12%", time: "刚刚", active: true, mode: "business" },
    { id: "c2", title: "HR 月度复盘 · 2026/04", time: "昨天", mode: "business" },
    { id: "c3", title: "运营商 ARPU 异常排查", time: "昨天", mode: "expert" },
    { id: "c4", title: "工单 SLA 达成率拉升路径", time: "前天", mode: "business" },
    { id: "c5", title: "财务 P&L · 部门偏差", time: "5/1", mode: "expert" },
    { id: "c6", title: "员工技能矩阵 × BU", time: "4/30", mode: "expert" },
    { id: "c7", title: "客户流失 7 日早期信号", time: "4/29", mode: "business" },
  ],

  // Pre-built per-conversation content (selectable from sidebar)
  conversations: {
    c1: {
      title: "Q1 销售归因：为什么华南掉了 12%",
      question: "Q1 华南区销售为什么环比下滑 12%？哪些 BU 拖累最大？",
      tag: "Q1 销售归因",
      bizText: "华南区 Q1 同比下滑 12%，主因是 BU-3 的客户经理流失（−18%）拖累签单链路；建议本季度优先稳定 BU-3 团队、并将渠道激励向直销倾斜。",
      expertText: "华南区 q1_2026 vs q1_2025 同比 −12.0%（1116 vs 1268，单位万元）。下钻 BU 维度：BU-3 贡献度从 32% → 22%（−10pp），与 BU-3 客户经理流失率 r=0.81 强相关。突变点：2026-01。",
      bizFollowups: ["华南为什么 BU-3 客户经理流失？", "对比西南区抓手", "生成完整复盘报告"],
      expertFollowups: ["改 SQL 加 channel 维度", "导出 Notebook", "下钻到 BU-3 客户级"],
      charts: [
        { kind: "bars", title: "Q1 区域成交额对比 · 同比", subtitle: "单位万元 · 红=负增长",
          data: [
            { region: "华东", q1_2025: 1820, q1_2026: 1934, delta: 6.3 },
            { region: "华北", q1_2025: 1402, q1_2026: 1516, delta: 8.1 },
            { region: "华南", q1_2025: 1268, q1_2026: 1116, delta: -12.0 },
            { region: "西南", q1_2025: 891,  q1_2026: 962,  delta: 8.0 },
            { region: "华中", q1_2025: 743,  q1_2026: 798,  delta: 7.4 },
            { region: "东北", q1_2025: 412,  q1_2026: 401,  delta: -2.7 },
          ] },
        { kind: "line", title: "近 6 月走势", subtitle: "月度成交额（华南）",
          data: [
            { m: "2025-10", val: 412 }, { m: "2025-11", val: 398 }, { m: "2025-12", val: 421 },
            { m: "2026-01", val: 354 }, { m: "2026-02", val: 376 }, { m: "2026-03", val: 386 },
          ] },
      ],
      insights: [
        { kind: "异常下跌", text: "华南 Q1 同比 −12.0%，是六大区中唯一两位数下滑（IQR 离群）", severity: "high" },
        { kind: "强相关",   text: "华南成交额下滑与 BU-3 客户经理流失率（−18%）皮尔逊相关 r=0.81", severity: "med" },
        { kind: "突变点",   text: "2026-01 出现单调突变（前后均值差 2.4σ），与渠道政策调整时间吻合", severity: "med" },
      ],
    },
    c2: {
      title: "HR 月度复盘 · 2026/04",
      question: "4 月人力月度复盘：流动率、认证密度、各 BU 人均产出?",
      tag: "HR 月度复盘",
      bizText: "4 月整体流动率 2.8%（同比 −0.3pp）；BU-2 / BU-5 人均产出环比 +6.4% 领跑，但 BU-3 认证密度仅 0.41 低于均线，建议本月安排 38 人补考。",
      expertText: "turnover_rate=2.8% (−0.3pp YoY) · cert_density: BU-2=0.71, BU-5=0.68, BU-3=0.41 (均线 0.55)。人均产出 BU-2 +6.4%, BU-5 +6.1% (环比), 与员工任期中位数 r=0.72。",
      bizFollowups: ["BU-3 认证缺口具体是哪些证书？", "Top 流失员工画像", "生成 HR 7 章月报"],
      expertFollowups: ["按 manager_id 下钻", "导出员工明细 csv", "改用 cohort 分析"],
      charts: [
        { kind: "bars", title: "各 BU 认证密度 · 4月", subtitle: "0–1 · 红=低于均线 0.55",
          data: [
            { region: "BU-1", q1_2025: 0.55, q1_2026: 0.62, delta: 12.7 },
            { region: "BU-2", q1_2025: 0.62, q1_2026: 0.71, delta: 14.5 },
            { region: "BU-3", q1_2025: 0.48, q1_2026: 0.41, delta: -14.6 },
            { region: "BU-4", q1_2025: 0.51, q1_2026: 0.55, delta: 7.8 },
            { region: "BU-5", q1_2025: 0.61, q1_2026: 0.68, delta: 11.5 },
            { region: "BU-6", q1_2025: 0.49, q1_2026: 0.52, delta: 6.1 },
          ] },
        { kind: "line", title: "近 6 月流动率", subtitle: "%（公司整体）",
          data: [
            { m: "2025-11", val: 3.2 }, { m: "2025-12", val: 3.4 }, { m: "2026-01", val: 3.1 },
            { m: "2026-02", val: 3.0 }, { m: "2026-03", val: 2.9 }, { m: "2026-04", val: 2.8 },
          ] },
      ],
      insights: [
        { kind: "认证短板", text: "BU-3 认证密度 0.41 低于均线 0.55，38 人证书过期未续", severity: "high" },
        { kind: "正向",     text: "BU-2 / BU-5 人均产出环比 +6.4% / +6.1%，与任期中位数 r=0.72", severity: "low" },
        { kind: "趋势",     text: "整体流动率连续 4 个月下行，已低于行业均线 3.5%", severity: "low" },
      ],
    },
    c3: {
      title: "运营商 ARPU 异常排查",
      question: "本月哪些用户 ARPU 异常下跌？是否与套餐变更相关？",
      tag: "ARPU 异常",
      bizText: "本月共检出 1,283 名异常下跌用户，集中在 5G 旧套餐迁移群组；其中 78% 在套餐变更后 30 天内 ARPU 下滑超 25%，建议优先针对该群组发起留存关怀。",
      expertText: "异常用户=1283 (−25% ARPU, 30d window post-migration)。Cohort: 5G_legacy_migration n=1647, hit_rate=78%。突变点 2026-03-15 与套餐 P-5G-99 下线时间一致 (Δ=2 天)。",
      bizFollowups: ["留存关怀话术怎么设计？", "高价值用户优先级", "推送给客户经理"],
      expertFollowups: ["按 city_tier 切片", "对比 4G 迁移基线", "拉取 30d ARPU 序列"],
      charts: [
        { kind: "bars", title: "异常用户 × 迁移群组", subtitle: "人数·红=异常 hit_rate >70%",
          data: [
            { region: "5G迁移", q1_2025: 412, q1_2026: 1001, delta: 142.9 },
            { region: "4G留存", q1_2025: 220, q1_2026: 184,  delta: -16.4 },
            { region: "高价值",  q1_2025: 60,  q1_2026: 47,   delta: -21.7 },
            { region: "静默",    q1_2025: 95,  q1_2026: 51,   delta: -46.3 },
          ] },
        { kind: "line", title: "迁移群组 30d ARPU 序列", subtitle: "元/月·T+0 为迁移日",
          data: [
            { m: "2026-T-7",  val: 96 }, { m: "2026-T0",   val: 92 },
            { m: "2026-T+7",  val: 78 }, { m: "2026-T+14", val: 71 },
            { m: "2026-T+21", val: 68 }, { m: "2026-T+30", val: 67 },
          ] },
      ],
      insights: [
        { kind: "异常集群", text: "5G 旧套餐迁移群组 hit_rate=78%，远高于基线 12%", severity: "high" },
        { kind: "突变点", text: "2026-03-15 ARPU 集体跳变，与 P-5G-99 下线仅差 2 天", severity: "high" },
        { kind: "高价值警示", text: "高价值用户中 47 人进入下跌区，需 48h 内优先报保", severity: "high" },
      ],
    },
    c4: {
      title: "工单 SLA 达成率拉升路径",
      question: "工单 SLA 达成率 Top10 区域，以及拉升空间最大的区域？",
      tag: "SLA 拉升",
      bizText: "SLA 达成率 Top3 区域为：成都 96.4% / 杭州 95.7% / 苏州 95.1%。拉升空间最大的是郑州（83.2%），主因周末班次不足，建议增配 4 名值班工程师。",
      expertText: "Top3: chengdu=0.964, hangzhou=0.957, suzhou=0.951。最低 zhengzhou=0.832，瓶颈：weekend_shift_coverage=0.41 (低于均线 0.78)，与 SLA 达成率 r=0.79。",
      bizFollowups: ["郑州补员的 ROI 怎么测？", "对比同类城市", "推送给区域负责人"],
      expertFollowups: ["按工单类型切片", "导出 SLA 时间序列", "改用生存分析模型"],
      charts: [
        { kind: "bars", title: "区域 SLA 达成率 · 同比", subtitle: "% · 红=达成率 < 90%",
          data: [
            { region: "成都", q1_2025: 94.1, q1_2026: 96.4, delta: 2.4 },
            { region: "杭州", q1_2025: 93.5, q1_2026: 95.7, delta: 2.4 },
            { region: "苏州", q1_2025: 92.8, q1_2026: 95.1, delta: 2.5 },
            { region: "上海", q1_2025: 91.2, q1_2026: 93.4, delta: 2.4 },
            { region: "北京", q1_2025: 89.6, q1_2026: 91.8, delta: 2.5 },
            { region: "郑州", q1_2025: 86.4, q1_2026: 83.2, delta: -3.7 },
          ] },
        { kind: "line", title: "郑州 · 近 6 月周末班次覆盖率", subtitle: "% · 均线 78%",
          data: [
            { m: "2025-11", val: 62 }, { m: "2025-12", val: 58 }, { m: "2026-01", val: 51 },
            { m: "2026-02", val: 46 }, { m: "2026-03", val: 43 }, { m: "2026-04", val: 41 },
          ] },
      ],
      insights: [
        { kind: "排名跨跳", text: "郑州 从排名 6 跳至区域末位，下滑背后为周末班次供不应求", severity: "high" },
        { kind: "结构异常", text: "周末覆盖率 0.41 远低于均线 0.78，与 SLA r=0.79", severity: "med" },
        { kind: "正向", text: "成都 / 杭州 / 苏州 连续 4 个季度保持 +2pp 以上拉升", severity: "low" },
      ],
    },
    c5: {
      title: "财务 P&L · 部门偏差",
      question: "Q1 各部门预算执行偏差排行，超支 Top 5 与原因?",
      tag: "P&L 偏差",
      bizText: "Q1 超支 Top1 为研发部 +18.7%（+1,240 万），主因人员扩张快于计划；其次销售费用 +12.3%。建议研发部下季度暂停外部招聘 2 个月，重点消化在岗。",
      expertText: "var_top5: rd=+18.7% (+12.4M), sales_opex=+12.3%, marketing=+9.1%, infra=+7.4%, hr=−4.2%。研发偏差与 headcount_growth r=0.93，与项目交付节奏 r=0.31。",
      bizFollowups: ["研发暂停招聘的人才风险？", "对比 2025 同期", "起草财务说明邮件"],
      expertFollowups: ["按 cost_center 下钻", "改用 EVA 模型", "导出预算执行 csv"],
      charts: [
        { kind: "bars", title: "Q1 部门预算偏差·%", subtitle: "红=超支 · 绿=节约",
          data: [
            { region: "研发",   q1_2025: 100, q1_2026: 118.7, delta: 18.7 },
            { region: "销售费用", q1_2025: 100, q1_2026: 112.3, delta: 12.3 },
            { region: "市场",   q1_2025: 100, q1_2026: 109.1, delta: 9.1 },
            { region: "基础设施", q1_2025: 100, q1_2026: 107.4, delta: 7.4 },
            { region: "人力",   q1_2025: 100, q1_2026: 95.8,  delta: -4.2 },
          ] },
        { kind: "line", title: "研发部 · 近 6 月人员增长", subtitle: "人·计划 vs 实际",
          data: [
            { m: "2025-11", val: 612 }, { m: "2025-12", val: 638 }, { m: "2026-01", val: 681 },
            { m: "2026-02", val: 712 }, { m: "2026-03", val: 758 }, { m: "2026-04", val: 791 },
          ] },
      ],
      insights: [
        { kind: "超支头部", text: "研发部 +18.7%（+1,240 万）独占全公司偏差 53%", severity: "high" },
        { kind: "强相关", text: "偏差与 headcount 增长 r=0.93，与项目交付节奏仅 r=0.31", severity: "med" },
        { kind: "正向", text: "人力成本 −4.2% 节约，主因 Q1 社保减免政策", severity: "low" },
      ],
    },
    c6: {
      title: "员工技能矩阵 × BU",
      question: "各 BU 的关键技能覆盖率热力图，哪些是高价值缺口？",
      tag: "技能矩阵",
      bizText: "云原生与 LLM Eng 是全公司共性缺口（覆盖率 < 35%），其中 BU-4 同时缺这两项；建议 Q2 启动专项培训，预算约 86 万。",
      expertText: "skills × BU heatmap: cloud_native=[0.21..0.42], llm_eng=[0.08..0.38]。BU-4 双低 (0.21, 0.12)。建议路径：cohort_training, n=120, budget=860K。",
      bizFollowups: ["86 万预算的 ROI 怎么算？", "对标外部薪酬", "生成培训方案"],
      expertFollowups: ["按 skill_level 切片", "导出技能差距 matrix", "对比同行业基准"],
      charts: [
        { kind: "bars", title: "关键技能覆盖率 · 全公司", subtitle: "% · 红=低于 35% 阈值",
          data: [
            { region: "数据治理",   q1_2025: 58, q1_2026: 64, delta: 10.3 },
            { region: "云原生",   q1_2025: 28, q1_2026: 32, delta: 14.3 },
            { region: "LLM Eng",  q1_2025: 12, q1_2026: 23, delta: 91.7 },
            { region: "交付架构",  q1_2025: 51, q1_2026: 56, delta: 9.8 },
            { region: "项目管理", q1_2025: 67, q1_2026: 71, delta: 6.0 },
            { region: "安全合规", q1_2025: 44, q1_2026: 48, delta: 9.1 },
          ] },
        { kind: "line", title: "BU-4 · 云原生认证增长", subtitle: "人·近 6 月",
          data: [
            { m: "2025-11", val: 18 }, { m: "2025-12", val: 20 }, { m: "2026-01", val: 22 },
            { m: "2026-02", val: 24 }, { m: "2026-03", val: 26 }, { m: "2026-04", val: 27 },
          ] },
      ],
      insights: [
        { kind: "双低警示", text: "BU-4 云原生 0.21 / LLM Eng 0.12，为唯一双低 BU", severity: "high" },
        { kind: "快速上升", text: "LLM Eng 覆盖率 12%→23%（+91.7%），是增速最快技能", severity: "low" },
        { kind: "预算建议", text: "专项培训 n=120 预算 86 万，以表面年化 ROI 4.2x 估算", severity: "med" },
      ],
    },
    c7: {
      title: "客户流失 7 日早期信号",
      question: "近 7 日哪些客户出现流失早期信号？特征是什么？",
      tag: "流失预警",
      bizText: "近 7 日识别出 47 家高风险客户，共同特征：登录频次环比 −60%、工单升级、合同续签询价中断。建议客户经理 48 小时内逐一拜访。",
      expertText: "high_risk_customers n=47, features: login_freq_drop>0.6 ∧ ticket_escalation>0 ∧ renewal_query_gap>14d。Lift vs baseline=4.7x。",
      bizFollowups: ["TOP 5 客户拜访话术", "历史流失客户的恢复率", "推送给客户经理"],
      expertFollowups: ["调整阈值看召回率", "导出客户名单", "对比上周特征"],
      charts: [
        { kind: "bars", title: "高风险客户 · 按行业", subtitle: "家·近 7 日 vs 上周",
          data: [
            { region: "金融",   q1_2025: 8,  q1_2026: 14, delta: 75.0 },
            { region: "制造",   q1_2025: 6,  q1_2026: 11, delta: 83.3 },
            { region: "零售",   q1_2025: 5,  q1_2026: 9,  delta: 80.0 },
            { region: "政务",   q1_2025: 4,  q1_2026: 7,  delta: 75.0 },
            { region: "医疗",   q1_2025: 2,  q1_2026: 4,  delta: 100.0 },
            { region: "其他",   q1_2025: 1,  q1_2026: 2,  delta: 100.0 },
          ] },
        { kind: "line", title: "高风险客户数 · 近 7 日", subtitle: "家·阈值上调后的召回趋势",
          data: [
            { m: "D-6", val: 21 }, { m: "D-5", val: 26 }, { m: "D-4", val: 32 },
            { m: "D-3", val: 38 }, { m: "D-2", val: 42 }, { m: "D-1", val: 47 },
          ] },
      ],
      insights: [
        { kind: "高 Lift", text: "三特征组合 Lift=4.7x，位于预警模型 PR 曲线肩部", severity: "high" },
        { kind: "行业偏重", text: "金融·制造 2 大行业占高风险客户 53%，需优先处理", severity: "med" },
        { kind: "动作建议", text: "48h 内拜访 TOP 5 可减少预计流失金额 1,800 万", severity: "high" },
      ],
    },
  },

  // Suggested starter prompts
  prompts: [
    "Q1 华南区销售为什么环比下滑？",
    "对比各 BU 的人均产出与认证密度",
    "本月哪些客户的 ARPU 异常下跌？",
    "生成 4 月人力月度复盘报告",
    "工单 SLA 达成率 Top10 区域",
  ],

  // Templates for new chat — 20 个覆盖企业 8 大域的分析模板
  templates: [
    // —— 销售 / 营销
    { id: "t01", name: "月度经营复盘", icon: "📊", domain: "经营", chips: ["8 章节", "PDF/Word"], prompt: "帮我做本月度经营复盘，含核心 KPI、异常、归因与下一步建议", desc: "封面 → 摘要 → 核心图表 → 维度下钻 → 异常 → 趋势 → 结论 → 附录" },
    { id: "t02", name: "销售归因分析", icon: "🔎", domain: "销售", chips: ["多维下钻", "BU × 区域"], prompt: "做一份销售归因分析：哪些区域/BU/产品线在拖累或拉动？", desc: "按区域 × BU × 产品 × 渠道四维归因，找拖累项 + Top 增长引擎" },
    { id: "t03", name: "渠道贡献分析", icon: "🛒", domain: "销售", chips: ["ROI 排行"], prompt: "对比直销/分销/线上/伙伴各渠道的 ROI 与同比", desc: "渠道维度 × 时间，给出 ROI 排行、激励调整建议" },
    { id: "t04", name: "Top 客户榜单", icon: "👑", domain: "销售", chips: ["增速 + 流失"], prompt: "Q1 客户增速 Top 20 + 流失风险 Top 10", desc: "按 GMV 增速、回款健康度、续约概率排序" },
    // —— 营销
    { id: "t05", name: "营销活动复盘", icon: "📣", domain: "营销", chips: ["ROI / 转化"], prompt: "复盘本月所有营销活动的拉新成本、转化率与 ROI", desc: "活动 × 渠道 × 漏斗，找性价比最高的组合" },
    { id: "t06", name: "区域市场渗透", icon: "🗺", domain: "营销", chips: ["渗透率"], prompt: "对比各省/市的客户渗透率与潜力分", desc: "渗透率 × 行业占比 × 头部客户密度" },
    // —— 财务
    { id: "t07", name: "财务季报", icon: "💼", domain: "财务", chips: ["预算偏差"], prompt: "财务季报，重点看各部门预算执行偏差与现金流", desc: "P&L · 现金流 · 部门预算偏差 Top10" },
    { id: "t08", name: "预算执行偏差", icon: "🎯", domain: "财务", chips: ["部门 Top"], prompt: "本月哪些部门超预算？给出超额比例与原因假设", desc: "按部门 × 科目 × 月份，>10% 偏差自动标红" },
    { id: "t09", name: "现金流压力测试", icon: "💧", domain: "财务", chips: ["18 个月"], prompt: "未来 18 个月现金流压力测试，最差/中性/最好情景", desc: "三情景模拟：应收回款 ±15% × 应付节奏 ±30 天" },
    { id: "t10", name: "毛利结构分析", icon: "💰", domain: "财务", chips: ["产品 × 客户"], prompt: "毛利率分析：哪些产品/客户在拉低整体毛利？", desc: "产品 × 客户矩阵，标识毛利异常项" },
    // —— HR
    { id: "t11", name: "HR 人力月报", icon: "👥", domain: "HR", chips: ["7 章节"], prompt: "帮我做 HR 月报，含编制、流动、薪酬、认证密度", desc: "在岗 · 入离职 · 流动率 · 关键岗位空缺 · 认证覆盖" },
    { id: "t12", name: "离职预警画像", icon: "⚠", domain: "HR", chips: ["高危员工"], prompt: "找出本月离职高危员工 Top 30，给出画像和挽留建议", desc: "基于工龄 / 绩效 / 加班 / 调薪 / 直属变动 综合打分" },
    { id: "t13", name: "关键技能盘点", icon: "🎓", domain: "HR", chips: ["覆盖率热力"], prompt: "各 BU 关键技能/认证覆盖率热力图，找缺口", desc: "技能矩阵 × BU，标识 <50% 覆盖的高风险格" },
    // —— 客户成功 / 服务
    { id: "t14", name: "客户健康度评分", icon: "❤", domain: "客户", chips: ["流失预警"], prompt: "客户健康度评分 + 流失风险 Top 30", desc: "活跃度 / 续约 / NPS / 工单 综合打分" },
    { id: "t15", name: "NPS 满意度分析", icon: "😊", domain: "客户", chips: ["趋势"], prompt: "近 6 个月 NPS 趋势 + 评论关键词聚类", desc: "评分趋势 + 文本聚类找差评聚集点" },
    { id: "t16", name: "工单 SLA 月报", icon: "🎫", domain: "服务", chips: ["区域对比"], prompt: "工单 SLA 达成率 Top10 / Bottom10 区域", desc: "按区域 × 优先级，识别 SLA 滑档" },
    // —— 运营 / 异常
    { id: "t17", name: "异常排查", icon: "⚠️", domain: "运营", chips: ["主动洞察"], prompt: "本周所有指标自动跑异常检测，标出突变点", desc: "多算法（IQR / Z-Score / STL / CUSUM）联合判定" },
    { id: "t18", name: "KPI 周报", icon: "📅", domain: "运营", chips: ["自动同步"], prompt: "本周经营 KPI 周报，对比上周和年累计", desc: "WoW / YoY / YTD 三对比 + 排行变化" },
    // —— 供应链 / 采购
    { id: "t19", name: "供应链风险扫描", icon: "📦", domain: "供应链", chips: ["库存周转"], prompt: "扫描本月供应链风险：库存周转、缺货、呆滞", desc: "周转天数 × SKU × 仓库矩阵，找呆滞与断货" },
    { id: "t20", name: "Adhoc 自由问", icon: "✨", domain: "通用", chips: ["最常用"], prompt: "", desc: "直接用业务语言提问，AI 自动选数据集与方法" },
  ],

  // The signature 14-step Agent trace
  traceSteps: [
    { i: 1, name: "接收用户问题", group: "感知", detail: "解析自然语言 + session 上下文(10轮)", t: 12 },
    { i: 2, name: "加载可用能力", group: "感知", detail: "工具集 8 项 · 数据集 6 张候选", t: 28 },
    { i: 3, name: "GraphRAG 社区检索", group: "理解", detail: "top-k=5 业务社区摘要命中：销售归因 / 区域结构", t: 340, badge: "GraphRAG" },
    { i: 4, name: "规划下一步动作", group: "理解", detail: "判定为多维归因任务 → 走 NL2SQL 主链路", t: 88 },
    { i: 5, name: "选择执行能力", group: "理解", detail: "Router 选定 sales_orders_2026 + fin_pnl_monthly", t: 22 },
    { i: 6, name: "实例语义解析", group: "理解", detail: "实体：'华南'、'Q1'、'环比' · 指标：成交额", t: 46 },
    { i: 7, name: "TTL 推理与补全", group: "理解", detail: "业务术语 → 字段：region_l1=south_china · period=2026Q1", t: 71, badge: "TTL" },
    { i: 8, name: "SQL 生成 · 尝试 1", group: "执行", detail: "JOIN 两张表 · 按 region × month × bu 切片", t: 612, badge: "Codegen" },
    { i: 9, name: "SQL 生成 · 尝试 2", group: "执行", detail: "校验失败：fin 表 month 字段为 string 需 cast", t: 198, status: "retry" },
    { i: 10, name: "SQL 生成 · 尝试 3", group: "执行", detail: "—", t: 0, status: "skip" },
    { i: 11, name: "SQL 生成 · 尝试 4", group: "执行", detail: "—", t: 0, status: "skip" },
    { i: 12, name: "执行 SQL（DuckDB）", group: "执行", detail: "扫描 482,103 行 → 返回 84 行聚合", t: 1340 },
    { i: 13, name: "检查查询结果", group: "校验", detail: "Critic：行数合理、无空值、数值在历史 IQR 范围内", t: 122 },
    { i: 14, name: "组装结论 + 选图 + 引用", group: "输出", detail: "选定双轴折线 + 同比柱形 · 触发异常洞察 2 条", t: 410 },
  ],

  // Sample chart data — Q1 sales attribution
  salesByRegion: [
    { region: "华东", q1_2025: 1820, q1_2026: 1934, delta: 6.3 },
    { region: "华北", q1_2025: 1402, q1_2026: 1516, delta: 8.1 },
    { region: "华南", q1_2025: 1268, q1_2026: 1116, delta: -12.0 },
    { region: "西南", q1_2025: 891, q1_2026: 962, delta: 8.0 },
    { region: "华中", q1_2025: 743, q1_2026: 798, delta: 7.4 },
    { region: "东北", q1_2025: 412, q1_2026: 401, delta: -2.7 },
  ],

  // Monthly trend
  monthlyTrend: [
    { m: "2025-10", val: 412 }, { m: "2025-11", val: 438 }, { m: "2025-12", val: 461 },
    { m: "2026-01", val: 392 }, { m: "2026-02", val: 358 }, { m: "2026-03", val: 366 },
  ],

  // Citation
  citation: {
    datasets: ["sales_orders_2026", "fin_pnl_monthly"],
    columns: ["order_id", "region_l1", "bu_id", "amount", "order_date", "period"],
    sql: `SELECT region_l1 AS region,
       SUM(CASE WHEN period='2025Q1' THEN amount END) AS q1_2025,
       SUM(CASE WHEN period='2026Q1' THEN amount END) AS q1_2026
FROM sales_orders_2026 s
JOIN fin_pnl_monthly f
  ON s.bu_id = f.bu_id
 AND CAST(f.month AS INT) = EXTRACT(MONTH FROM s.order_date)
WHERE period IN ('2025Q1','2026Q1')
GROUP BY region_l1
ORDER BY q1_2026 DESC;`,
    rows: 84,
    sample: [
      { region: "华南", q1_2025: 1268, q1_2026: 1116, delta_pct: -12.0 },
      { region: "华东", q1_2025: 1820, q1_2026: 1934, delta_pct: 6.3 },
      { region: "华北", q1_2025: 1402, q1_2026: 1516, delta_pct: 8.1 },
    ],
  },

  // Anomaly insights
  anomalies: [
    { kind: "异常下跌", text: "华南 Q1 同比 −12.0%，是六大区中唯一两位数下滑（IQR 离群）", severity: "high" },
    { kind: "强相关", text: "华南成交额下滑与 BU-3 客户经理流失率（−18%）皮尔逊相关 r=0.81", severity: "med" },
    { kind: "突变点", text: "2026-01 出现单调突变（前后均值差 2.4σ），与渠道政策调整时间吻合", severity: "med" },
  ],

  // Dashboard — grouped by source conversation; each group is a "pinned report"
  dashGroups: [
    {
      id: "g1", convId: "c1", title: "Q1 销售归因 · 华南", subtitle: "来自 c1 · 钉于 5 分钟前",
      owner: "巧玲", followers: 4, refresh: "每日 09:00",
      cards: [
        { id: "d1.kpi", title: "华南 Q1 同比", kind: "kpi", value: "−12.0", delta: -12, sub: "vs 2025Q1 · 1116 vs 1268 万元", spans: 1 },
        { id: "d1.bars", title: "Q1 区域成交额对比", kind: "bars", convChart: 0, spans: 2 },
        { id: "d1.line", title: "华南近 6 月走势", kind: "line", convChart: 1, spans: 2 },
        { id: "d1.insights", title: "异常洞察 · 3 条", kind: "insights", spans: 1 },
      ],
    },
    {
      id: "g2", convId: "c2", title: "HR 月度复盘 · 2026/04", subtitle: "来自 c2 · 钉于 1 小时前",
      owner: "巧玲", followers: 7, refresh: "每月 1 号",
      cards: [
        { id: "d2.kpi", title: "整体流动率", kind: "kpi", value: "2.8", delta: -0.3, sub: "% · 同比 −0.3pp · 低于行业均线", spans: 1 },
        { id: "d2.bars", title: "各 BU 认证密度", kind: "bars", convChart: 0, spans: 2 },
        { id: "d2.line", title: "近 6 月流动率", kind: "line", convChart: 1, spans: 2 },
        { id: "d2.insights", title: "HR 系统洞察", kind: "insights", spans: 1 },
      ],
    },
    {
      id: "g3", convId: "c5", title: "财务 P&L · 部门偏差", subtitle: "来自 c5 · 钉于昨天",
      owner: "巧玲", followers: 3, refresh: "每周一 08:00",
      cards: [
        { id: "d3.kpi", title: "研发部超支", kind: "kpi", value: "+18.7", delta: 18.7, sub: "% · +1,240 万 · Top1 拖累", spans: 1 },
        { id: "d3.bars", title: "Q1 部门预算偏差", kind: "bars", convChart: 0, spans: 2 },
        { id: "d3.donut", title: "超支结构占比", kind: "donut", spans: 1 },
        { id: "d3.insights", title: "财务洞察", kind: "insights", spans: 2 },
      ],
    },
  ],
  // Legacy flat list (kept for back-compat; prefer dashGroups)
  dashboardCards: [
    { id: "d1", title: "Q1 区域成交额对比", chart: "bars", spans: 2 },
    { id: "d2", title: "六个月销售趋势", chart: "line", spans: 1 },
    { id: "d3", title: "华南环比 −12%（KPI）", chart: "kpi", spans: 1 },
    { id: "d4", title: "BU × 区域热力图", chart: "heat", spans: 2 },
    { id: "d5", title: "异常洞察 · 3 条", chart: "insights", spans: 1 },
    { id: "d6", title: "渠道贡献分布", chart: "donut", spans: 1 },
  ],

  // Eval set sample rows
  evalRows: [
    { id: "e_001", q: "Q1 华南销售环比", success: true, lat: 6.2, has_chart: true },
    { id: "e_002", q: "HR 认证密度 Top BU", success: true, lat: 4.8, has_chart: true },
    { id: "e_003", q: "财务异常部门", success: true, lat: 5.4, has_chart: true },
    { id: "e_004", q: "ARPU 离群用户", success: true, lat: 7.1, has_chart: true },
    { id: "e_005", q: "工单 SLA 达成", success: true, lat: 3.9, has_chart: true },
    { id: "e_006", q: "技能矩阵 × BU", success: false, lat: 8.7, has_chart: false },
    { id: "e_007", q: "Q1 增速 Top 客户", success: true, lat: 5.0, has_chart: true },
    { id: "e_008", q: "续约率与 NPS", success: true, lat: 4.4, has_chart: true },
  ],

  evalMetrics: {
    完成率: 0.965, 答案正确率: 0.871, 图表生成率: 0.942,
    多轮一致性: 0.834, 引用准确率: 0.962, 平均耗时: 5.6,
  },
};
