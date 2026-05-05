# 结构化数据智能分析与洞察报告生成系统 · 设计文档

> 版本: v0.1 (路线图 PR #3 草案 · 2026-05-05)
> 项目: TableTalker
> 提交对应赛题 4: 结构化数据智能分析与洞察报告生成
>
> 本文中所有 "PR #N" 均指 [`docs/roadmap.md`](../docs/roadmap.md) 内部
> 编号(PR #1 — PR #9),不等同于 GitHub Pull Request 编号。

本文件是中文版设计文档，对应组委会要求的 4–8 页设计说明。
英文版工程细节散落在 `docs/architecture.md`、`docs/submission-contract.md`、
`docs/refusal-policy.md`、`docs/session-state.md`，本文件做面向评委的整合呈现，
正式终版在路线图 PR #9 定稿。

---

## 1. 系统总览

TableTalker 是一个面向**结构化数据 (CSV / Excel)** 的智能分析 Agent。
评委通过 Web 界面上传一个或多个数据文件，提交一段自然语言分析需求，
系统自主完成：

1. **数据探查**：字段类型、缺失率、JSON 嵌套字段识别、跨表 join 候选键检测；
2. **分析规划**：基于数据画像与需求，规划分析步骤（统计 / 趋势 / 根因）；
3. **沙箱执行**：在受控 pandas 沙箱中运行分析代码，捕获 DataFrame 结果；
4. **证据抽取**：从代码执行结果中提取
   `(dataset, table, columns, filters, aggregation, value, row_count)`
   作为每条关键发现的可复现依据；
5. **报告生成**：Jinja2 模板 + Plotly 嵌入式图表，输出独立 HTML 文件；
6. **追问应答**：保留会话状态（已识别客群、已应用过滤、已生成图表）支持多轮；
7. **拒答管控**：四类陷阱（字段缺失 / 维度不匹配 / 诱导幻觉 / 越权请求）
   各自对应统一格式的拒答话术。

### 1.1 核心设计原则

| 原则 | 含义 |
|---|---|
| **凡数据皆有出处** | `findings` 中每个数字必须能被 `evidence` 复现；planner 严禁生成"凭印象"的数字。 |
| **保守拒答** | 误拒可分析需求 > 答错；分类器只在硬信号下触发。 |
| **结构化审计** | 沙箱每一次执行的 op 都进 trace，evidence 抽取走结构化路径，非正则。 |
| **会话有记忆** | 追问不重新推导：父轮的客群定义、过滤条件、图表 ID 入会话状态。 |
| **环境零外联** | 沙箱无网络、读权限收敛在请求 workspace 与 `data/`，避免数据回流与 §7.4 红线。 |

---

## 2. 系统架构

> 对外仅暴露 `/v1/analyze`、`/v1/follow-up`、`/reports/{id}.html` 三条路径,
> 与 `docs/submission-contract.md` 完全一致;响应 JSON 形状逐字段冻结,
> 不得漂移。

### 2.1 拓扑

```text
浏览器 ──HTTP──▶  Next.js 前端 (上传 / 输入 / 报告 iframe / 追问)
                       │
                       ▼ POST /v1/analyze
                       ▼ POST /v1/follow-up
                       ▼ GET  /reports/{id}.html
                ┌────────────────────────┐
                │  FastAPI 后端          │
                │  ├─ 上传 + workspace   │
                │  ├─ 数据探查 Profiler  │
                │  ├─ 拒答前置分类       │
                │  ├─ Planner (ReAct)    │──▶ 亚信 LLM 网关
                │  │   工具集:           │     (OpenAI-compat HTTP)
                │  │   - run_pandas_code│
                │  │   - make_chart     │
                │  │   - refuse / finish│
                │  ├─ 沙箱 Runner        │
                │  │   (subprocess +    │
                │  │    walltime/RSS    │
                │  │    + path 白名单)  │
                │  ├─ 证据 Builder       │
                │  ├─ 报告 Renderer      │
                │  │   (Jinja + Plotly) │
                │  └─ 会话 Store (内存) │
                └────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 落地 PR |
|---|---|---|
| 上传 + workspace | 接收 multipart 上传，按 `workspace/{request_id}/` 隔离 | PR #4 |
| Profiler | 字段类型推断、缺失率、JSON 嵌套识别、跨表 key 候选 | PR #4 |
| 拒答分类器 | 实体-字段匹配、维度一致性检查 | PR #6 |
| Planner | ReAct 循环，调度工具，控制重试上限 (≤3) | PR #4 |
| 沙箱 Runner | 子进程执行 pandas 代码，资源 / IO 隔离 | PR #4 |
| 证据 Builder | 从执行结果提取 evidence 字段，禁止凭空数字 | PR #4 |
| 报告 Renderer | Jinja2 模板 + 内嵌 Plotly JSON | PR #5 |
| 会话 Store | 父轮上下文的内存持久化，按 parent_id 索引 | PR #6 |

### 2.3 关键时序：单次分析

```text
评委 ─→ 前端       后端                  LLM 网关        沙箱
  │     │           │                      │             │
  │ 上传 + 提交问题 │                      │             │
  │────▶│ multipart │                      │             │
  │     │──────────▶│ 保存 workspace      │             │
  │     │           │ 调 Profiler          │             │
  │     │           │ 调拒答前置分类       │             │
  │     │           │ if 拒答 → 跳到底     │             │
  │     │           │                      │             │
  │     │           │ Planner 第 1 轮     │             │
  │     │           │──── system+user ───▶│             │
  │     │           │◀──── tool_calls ────│             │
  │     │           │                      │             │
  │     │           │ run_pandas_code ────────────────▶│
  │     │           │◀──── stdout / df ───────────────────│
  │     │           │                      │             │
  │     │           │ Planner 第 2 轮 (反馈结果)         │
  │     │           │ ... (循环 ≤ N 轮)                  │
  │     │           │                      │             │
  │     │           │ Evidence Builder 抽取每次 run     │
  │     │           │ Renderer 生成 reports/{id}.html   │
  │     │           │ Session Store 写入                 │
  │     │           │                      │             │
  │     │◀── JSON ──│                      │             │
  │◀ 报告 iframe ──│                      │             │
```

---

## 3. 关键设计决策

### 3.1 为什么用 ReAct + 真实 pandas 代码 (而不是 typed plan)

赛题 §7.2 雷 3 明确禁止"凭直觉填数"——证据中的数字必须来自实际代码运行。
有两条路线：

- **A. Typed Plan**：LLM 输出结构化 JSON Plan，executor 跑死代码（Claude
  内部 spreadsheet 工具的做法）。
- **B. ReAct + run_pandas_code**：LLM 写真实 pandas 代码，沙箱执行后把 stdout
  喂回 LLM。

我们选 **B 主路径 + A 退化为审计层**：

- **B 满足证据真实性**：每个数字都能挂回到一段实际跑过的代码；
- **A 升级为结构化 trace**：每次 `run_pandas_code` 调用都被解析为
  typed op (load → filter → group → agg)，让 evidence builder 走结构化路径
  抽取 `(filters, aggregation, value)` 三元组，避免 regex 解析 pandas 代码字符串。

PR #3.5 落地 typed plan 模块（已在 `feat/spreadsheet` 分支 park），
PR #4 落地 ReAct 主循环并接入审计层。

### 3.2 为什么"先探查后规划"

赛题官方推荐与雷 4 (JSON 嵌套字段未解析) 共同决定了这个设计。如果让 planner
在不看真实数据的情况下规划，会出现：

- 把 TMDB 的 `genres` 列当字符串做 `value_counts`，得到几乎全唯一的伪类别；
- 对预算列做 `mean()`，没排除 0 值（TMDB 中 0 表缺失），均值严重低估。

Profiler 在 planner 介入之前，先对每个文件做：

1. dtype 推断 + 类别 / 数值 / 时间 / JSON-字符串 / id 五分类；
2. 每列缺失率（同时识别 `NaN`、空串、`?`、`Unknown`、`N/A`）；
3. JSON 列检测（首行 `json.loads` 试解，成功率 >80% 就标记）；
4. 跨表 key 候选（列名字符串相似度 + 值域重叠率）。

Planner 的系统提示里包含这份画像，避免规划阶段就走偏。

### 3.3 为什么沙箱用 subprocess 而不是 RestrictedPython

- **隔离强度**：subprocess 提供进程级隔离，可加 `rlimit` 限制 RSS 和
  walltime；RestrictedPython 是同进程 AST 改写，逃逸面更大。
- **依赖友好**：`pandas` / `pyarrow` 等用 C 扩展；RestrictedPython 对
  C 扩展支持有限。
- **简单可审计**：subprocess + 清空环境变量 (无 `HTTPS_PROXY`) + 读路径白名单
  比 AST 重写更容易写测试。

代价：每次 `run_pandas_code` 启动子进程的开销 (~50–100 ms)。在分析延迟 ≤60 s
的 SLO 下可接受。

### 3.4 为什么会话状态在内存

- 评测窗口最多约 100 个会话，单进程内存承载充足；
- 引入数据库（Postgres / SQLite）会扩大主观项 §6.B.1 安全 / 性能审计面，
  风险大于收益；
- 重启即清空——评测期不重启即可，赛后部署再加持久化层。

### 3.5 拒答的非对称代价

赛题对"误拒"和"该拒不拒"的惩罚都很重，但**误拒比该拒不拒更危险**——
误拒一题量化指标几乎归零，且会被主观项扣分；该拒不拒还能拿一部分分。
因此分类器**保守倾斜**：

- 前置分类只在三条硬信号同时满足时触发：实体名出现在问题中 + 列名 fuzzy
  无匹配 + 列值无匹配；
- 边界情况留给 planner，让它在循环中产生空结果时再决定是否拒答；
- 诱导幻觉 (类别 3) 不拒答，而是先核算 user 的断言，给真实数据。

详细话术与触发逻辑见 `docs/refusal-policy.md`。

---

## 4. 性能与安全

### 4.1 性能目标

| 指标 | 目标 | 备注 |
|---|---|---|
| 单次分析端到端延迟 (≤10MB 文件) | p95 ≤ 60 s | own SLO |
| 追问延迟 | p95 ≤ 20 s | own SLO |
| 并发分析 | ≥ 4 | own SLO |
| 报告 HTML 大小 | ≤ 500 KB / 份 | 内嵌 Plotly JSON 不含 CDN |
| 大数据集采样阈值 | 总行数 > 50k 触发 | `sampling_rate` 显式标注 |

### 4.2 安全保障

| 项 | 实现 |
|---|---|
| 沙箱隔离 | subprocess + rlimit (RSS/walltime) + 清空 proxy env |
| 文件读权限 | 白名单到当前请求的 `workspace/{id}/` 与 `data/` |
| 网络封锁 | 子进程清空 `HTTPS_PROXY`/`HTTP_PROXY`，httpx 替换为禁用版本 |
| Prompt 注入防护 | planner 系统提示禁止响应"展示 prompt"类请求；越权操作走拒答类别 4 |
| Evidence 防伪 | 每条 evidence 在响应前用同一 dataset 重放过滤 + 聚合，与捕获值比较 |
| 上传文件审计 | 单文件 ≤ 50 MB；扩展名白名单 (`.csv` `.xlsx` `.xls`) |

### 4.3 可观测性

每次请求按 `workspace/{id}/trace.jsonl` 记录：

- 每次 LLM 调用：messages、temperature、tokens；
- 每次 `run_pandas_code`：代码、stdout、错误、用时；
- 每条 finding：title、detail、evidence 与抽取来源 op 索引；
- 每次拒答触发：类别、命中规则、参数。

Trace 文件用于：
- DEMO 视频解说素材；
- 自测报告 §10 数据来源；
- 复现性审计支持。

---

## 5. 复现性声明

- **代码**：Apache 2.0 协议，公开 GitHub 仓库 (URL 填于提交时)；
- **依赖**：`uv` 锁文件 `src/backend/uv.lock` + `pnpm-lock.yaml`，版本固定；
- **运行**：`bash 运行脚本/start.sh` 一键启动，端口默认 8000 (后端) + 3000 (前端)；
- **环境变量**：`.env.example` 声明所有需要的变量，敏感值 (LLM API key) 不入库；
- **数据**：组委会公开数据集放在 `data/public_datasets/`，与赛题 §2 路径一致；
- **测试**：`make check` 跑 lint + typecheck + 单元测试 + 集成测试。

---

## 6. 当前状态与里程碑

| PR | 内容 | 状态 |
|---|---|---|
| #1, #2 | 文档骨架、本地开发环境 | ✅ |
| #3 | 本设计文档 v0.1、契约对齐、自测报告 v0、评分映射 | 🚧 (本 PR) |
| #3.5 | typed plan 模块 (审计层) | ☐ |
| #4 | Profiler、ReAct planner、沙箱、证据抽取 | ☐ |
| #5 | HTML 报告渲染、≥3 种图表 | ☐ |
| #6 | 拒答分类器、追问会话、UI 多轮 | ☐ |
| #7 | 前端完整 UI (上传 / 进度 / 报告 / 追问) | ☐ |
| #8 | 15 数据集自测、性能压测、自测报告 v1 | ☐ |
| #9 | DEMO 视频、公网 URL、本文件 v1 终版 | ☐ |

详见 `docs/roadmap.md`。

---

## 7. 创新点（拟）

最终版在 PR #9 整理，当前规划方向：

1. **typed plan 审计层 + ReAct 主循环混合**：在保证证据真实性的同时获得
   结构化 trace，evidence 抽取从正则解析降级为 op 反序列化；
2. **TableVerse 报告组织**：每条 finding 在报告里以"verse"形式叙事
   (verse 1 装载 → verse 2 过滤 → verse 3 分组 → ...) 让评委可视化整个分析流；
3. **诱导幻觉的"先核算后纠正"**：不拒答类别 3，给真实数据 + 修正 user
   断言，主动展现拒幻觉的能力；
4. **追问的命名客群消解**：父轮自动给客群命名 (高价值客群、流失高发部门),
   追问时通过命名消解代词，不重新推导；
5. **报告内嵌可观测面板** (PR #5 待评估)：HTML 报告底部展示 trace 摘要,
   评委可看见每个数字背后跑了什么代码。

---

## 8. 限制与未尽事项

1. **会话状态非持久化**：评测窗口内单进程内存即可，赛后再加 SQLite；
2. **单 LLM 网关**：仅声明使用亚信 LLM 网关；不引入备份网关以满足 §7.4 #4；
3. **OCR / 图片型表格不支持**：本赛题为 CSV/Excel 结构化输入，不在范围内；
4. **大文件 (>50MB) 不支持全量**：会触发采样路径并显式标注 `sampling_rate`；
5. **多 session 跨账户隔离**：评测期免登录，无账户概念；赛后引入。

---

## 附录 A · 文件清单

| 路径 | 说明 |
|---|---|
| `README.md` | 项目说明与快速开始 |
| `PRODUCT.md` | 产品定义 |
| `docs/architecture.md` | 英文工程架构文档 (本文件的英文细节) |
| `docs/submission-contract.md` | 提交契约 (响应 JSON 字段说明) |
| `docs/scoring-map.md` | 评分项映射 |
| `docs/refusal-policy.md` | 拒答策略与统一话术 |
| `docs/session-state.md` | 追问会话状态设计 |
| `docs/roadmap.md` | PR 里程碑 |
| `架构文档/design_doc.md` | 本文件 |
| `自测报告/latest_evaluation_metrics.md` | 自测指标 (供评分模型读取) |
| `运行脚本/start.sh` | 一键启动 |
| `演示视频/` | DEMO 视频 (终版前留空) |
