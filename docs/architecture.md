# 工程架构

本文件面向研发维护，评委侧中文设计文档见 `架构文档/design_doc.md`。

## 1. 系统目标

TableTalker 提供一个 Web 结构化数据分析 Agent：

1. 接收 CSV / Excel 单文件或多文件上传。
2. 对数据做字段剖析，调用 LLM 生成 typed JSON plan。
3. 用本地 pandas 白名单算子执行 plan，LLM 不写任意代码。
4. 从执行结果生成可复算 evidence。
5. 渲染包含 ECharts 图表的 HTML 报告。
6. 支持基于父轮会话状态继续追问。
7. 对数据不支持的问题给出固定拒答。

## 2. 拓扑

```text
浏览器
  │
  ▼
Next.js 前端
  ├─ /             分析主页
  ├─ /history     历史分析
  ├─ /batch       批量评测
  ├─ /reports     报告列表
  └─ /status      服务状态
  │
  ▼
FastAPI 后端
  ├─ /v1/analyze       主分析
  ├─ /v1/follow-up     追问
  ├─ /v1/batch         批量
  ├─ /v1/sessions      历史
  └─ /reports/{id}.html
      │
      ├─ Profiler
      ├─ Refusal pre-check
      ├─ 规划器（AsiaInfo LLM 网关）
      ├─ 执行器（本地 pandas 类型化算子）
      ├─ 证据构造器
      ├─ 定稿器（AsiaInfo LLM 网关）
      ├─ Report renderer（Jinja + 内联 ECharts）
      ├─ Session store（内存热层）
      └─ Session recorder（SQLite 历史层）
```

## 3. 核心模块

| 模块 | 路径 | 职责 |
|---|---|---|
| 上传入口 | `app/api/analyze.py` | 保存主文件和 `extra_files`，限制大小，创建 workspace |
| 数据剖析 | `app/analyze/profiler.py` | dtype、缺失率、top values、字段性质、JSON-string 列识别 |
| 分析编排 | `app/analyze/handler.py` | refuse op 短路、Cat 4 路径扫描、planner→executor→evidence→finalize、Cat 1 缺失列拒答兜底 |
| LLM planner | `app/spreadsheet/planner.py` | 输出 typed JSON plan；prompt 含 4 类陷阱教学，可 emit `RefuseOp` 直接拒答 |
| typed executor | `app/spreadsheet/executor.py`, `app/spreadsheet/ops/*` | 校验 DAG 并执行 16 个 pandas 算子（含 `explode_json`） |
| 表达式 DSL | `app/spreadsheet/expr.py` | filter/add_column 表达式安全求值；算术运算前置类型校验 |
| evidence | `app/analyze/evidence.py` | 抽取 dataset/table/columns/filters/aggregation/value/row_count |
| 报告 | `app/report/*` | 生成 HTML 与 ECharts 配置（bar/line/pie/scatter/heatmap/box 6 类），内存托管 |
| 追问热层 | `app/session/store.py`, `app/session/prompt.py` | 保存父轮 workspace、findings、cohorts、chart anchors |
| 历史持久层 | `app/persistence/sessions.py`, `app/api/sessions.py` | SQLite 索引、搜索、统计、详情、删除 |
| 批量 | `app/api/batch.py`, `app/batch/*` | 自动嗅探 native vs 官方 jsonl；输出 xlsx 或 §5.2 `predictions.zip` |
| 阶段计时 | `app/analyze/stages.py` | `X-Stage-Timings` 七段耗时（含错误路径） |

## 4. 为什么用类型化计划

官方要求 evidence 可复算，最危险的是 LLM 直接编数字或写任意代码。当前设计把边界切开：

- LLM 只决定“做什么”，输出结构化 plan。
- pandas 本地 handler 决定“算出来是什么”。
- Pydantic 拒绝未知 op 和错误 schema。
- executor 校验 DAG，拒绝悬挂 src、重复 out、错误算子连接。
- evidence 从 `OpResult` 和执行 payload 抽取，不从 LLM 文本反推。

代价是 single-shot plan 出错会返回 422 或被转拒答；收益是审计面窄、可复现、易测试。

## 5. 单次分析数据流

1. 前端上传文件和问题到 `/v1/analyze`。
2. 后端保存 workspace，剖析所有上传表。
3. 规划器调用 LLM 生成类型化计划（**LLM 可主动 emit `RefuseOp` 拒答**，
   handler 在 step 3.5 短路；同时 `_scan_plan_for_oob_paths` 扫描 plan
   args 防止越权路径走到 executor）。
4. executor 本地执行 pandas op。如缺失列触发 KeyError，
   `_classify_op_failure` 把它升级为 Cat 1 拒答。
5. evidence builder 为 findings 绑定证据。
6. finalize 调 LLM 生成中文摘要、标题、**多 finding 列表**、建议。
7. report renderer 生成 HTML，写入 `REPORT_STORE`。
8. `SESSION_STORE` 保存热会话，`SESSION_RECORDER` 写入 SQLite 历史索引。
9. 返回分析响应 `AnalyzeResponse`。

## 6. 非功能现状

| 项 | 当前状态 |
|---|---|
| 图表 | 6 类：bar / line / pie / scatter / heatmap / box（PR #21 加 heatmap+box） |
| evidence | 20 题回归完整率 100% |
| 多 finding | 平均 2.9 个/case，根因评分门槛 1.5 已过（PR #22） |
| 摘要长度 | 平均 652 字符，趋势评分门槛 400 已过（PR #22） |
| 拒答 | 100% LLM 主导（无关键词字典）；trap_strict 92.9%（PR #22） |
| 性能 | aigw 网关 P50 116s / P95 138s（reasoning model） |
| 文件大小 | 默认 256 MiB / 文件，512 MiB / 请求，ENV 可调 |
| 网络 | 除声明的 LLM 网关外，分析路径不需要外部网络 |
| 持久化 | 历史记录用 SQLite；追问热状态用内存 LRU + TTL |
| 批量兜底 | `/v1/batch` + `eval/render_official_predictions.py` CLI 支持 §5.2 官方 jsonl 输入 |

## 7. 已知缺口

1. JSON 嵌套字段：`explode_json` op 已实现（PR #21），但隐藏题命中率
   不可控。
2. trap_strict 在 92.9%，靠的是 LLM 自主判断；隐藏 5 题如有 ≥1 个 LLM 误判
   会跌回 89%。Cat 3 诱导幻觉的 narrative 措辞稳定性需要更多验证。
3. LLM 延迟（aigw + reasoning）是 P95 的全部来源；产品侧无优化空间。
4. follow-up 在批量路径上跳过（标 status=skipped），符合 §4.2「追问由
   评委即时发起」的描述但限制了完全离线兜底的能力。
