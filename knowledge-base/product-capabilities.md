# TableTalker 产品能力清单

> 最后更新：2026-05-08 · 基于 commit `688126e`（fix/dotenv-planner-reports 分支）

## 产品定位

TableTalker 是一个**数据分析智能体**（Data Analysis Agent）。用户上传 CSV/Excel 文件并用自然语言提问，系统自动完成数据剖析、分析规划、代码执行、证据提取，生成包含交互式图表的独立 HTML 报告，并支持多轮追问。

**目标用户**：运营人员、分析师、决策者——任何需要从电子表格中获取答案但不想写 pandas 代码的人。

**核心差异化**：
- 每个数值都有可复算的代码证据，无法复现则主动拒答
- 报告不是终点而是对话的起点，支持多轮追问
- 报告为单一自包含 HTML，离线可查看

---

## 已实现能力清单

### 1. 数据接入与剖析

| 能力 | 说明 |
|---|---|
| 文件上传 | 支持 CSV (.csv) 和 Excel (.xlsx)，前端拖拽 + 点击上传 |
| 自动数据剖析 | 每列 dtype、缺失率、distinct count、top values、字段性质推断（numeric / categorical / temporal / text / bool） |
| 跨文件 join 检测 | 列名 + 值重叠启发式，自动识别可关联字段 |
| 上传体积限制 | 单文件最大体积由 `UPLOAD_MAX_BYTES` 控制 |

### 2. 智能分析管线（Analyze Pipeline）

| 能力 | 说明 |
|---|---|
| 自然语言提问 | 用户用中/英文自由描述分析需求 |
| LLM 规划器 | 基于 AsiaInfo LLM 网关（OpenAI 兼容），将问题转化为结构化分析计划（typed-plan DAG） |
| 15+ 数据操作算子 | `load_csv`, `load_excel`, `select_columns`, `filter_rows`, `add_column`, `group_by`, `aggregate`, `sort`, `head`, `tail`, `join`, `pivot`, `melt`, `to_table`, `to_chart` |
| 表达式 DSL | 安全的表达式语法（Literal / ColRef / BinOp / Call），白名单函数：`abs`, `round`, `min`, `max`, `lower`, `upper`, `len`, `if` |
| 沙箱执行 | pandas 代码在子进程中执行：30s 墙钟上限、1 GiB RSS 上限、只读文件白名单、无出站网络 |
| 证据提取 | 每个 finding 自动提取 `dataset / table / columns / filters / aggregation / value / row_count`，确保可复算 |
| 分阶段计时 | 7 阶段（profile → preview_plan → plan_llm → execute → evidence → finalize_llm → render）逐段计时，通过 `X-Stage-Timings` 响应头暴露 |

### 3. 报告生成

| 能力 | 说明 |
|---|---|
| 独立 HTML 报告 | 单文件自包含，无需服务器即可查看，无 CDN 依赖 |
| 3 种内联 SVG 图表 | 柱状图（bar）、折线图（line）、饼图（pie），纯 Python 生成 |
| 叙事摘要 | LLM 生成的中文分析叙事 `summary`，附带结构化 `findings` 和 `recommendations` |
| 图表锚点 | 每张图表带 `html_anchor`，报告内可跳转定位 |
| 报告托管 | `GET /reports/{id}.html` 直接在线访问 |

### 4. 拒答与反幻觉机制

| 能力 | 说明 |
|---|---|
| 4 类陷阱识别 | ① 字段缺失 ② 维度错配 ③ 诱导幻觉 ④ 越权操作 |
| 规范化拒答措辞 | 每类陷阱有中文 canonical phrasing，对齐自动评分器关键词匹配 |
| 前置拒答 | profiler 阶段即可检测字段缺失 / 维度错配，直接跳过 LLM 调用 |
| 幻觉纠正 | 第 3 类不拒答而是「先核算后纠正」，用真实数据推翻用户错误前提 |
| 证据强制绑定 | planner 禁止直接输出数值，所有数字必须来自实际代码执行结果 |

### 5. 多轮追问（Follow-up）

| 能力 | 说明 |
|---|---|
| 会话管理 | 以 parent analysis `id` 为键，内存保持完整会话状态 |
| Cohort 自动提取 | 从 findings 的 evidence 中自动提取命名子集（如「高价值客群」），follow-up 可直接引用 |
| 代词消解 | follow-up prompt 注入 parent session 摘要 + cohort 列表，支持「他们」「那三个类别」等指代 |
| 上下文一致性 | 后续分析继承已有 findings、chart_ids、cohort definitions |
| 同形响应 | follow-up 返回与首轮相同的 `AnalyzeResponse` JSON 结构 |

### 6. 批量处理（Batch）

| 能力 | 说明 |
|---|---|
| Manifest 驱动 | 上传 JSONL / CSV manifest + 数据文件，一次提交多个分析任务 |
| XLSX 输出 | 批量结果导出为 Excel 文件下载 |
| 前端批量页面 | `/batch` 路由，manifest 上传 + 数据文件上传 + 进度状态 |

### 7. 历史记录（History）

| 能力 | 说明 |
|---|---|
| 会话索引 | `GET /v1/sessions` 列出所有会话，支持状态筛选（completed / refused） |
| 会话详情 | `GET /v1/sessions/{id}` 返回完整对话轮次 |
| 会话删除 | `DELETE /v1/sessions/{id}` |
| 统计概览 | 会话总数、完成数、拒答数等 stats |
| 前端历史页面 | `/history` 路由，带搜索、筛选、详情展开、动画交互 |

### 8. Web UI

| 能力 | 说明 |
|---|---|
| 技术栈 | Next.js 15 + React 19 + Tailwind CSS + Framer Motion |
| 三页面路由 | `/`（分析主页）、`/history`（历史记录）、`/batch`（批量处理） |
| 拖拽上传 | 全页面拖拽覆盖层 + 点击上传，支持 `.csv` / `.xlsx` |
| 对话式交互 | 首轮提问 → 报告展示 → 追问输入，类聊天产品体验 |
| 快捷键 | `⌘+Enter` / `Ctrl+Enter` 提交 |
| 状态反馈 | uploading → analyzing → done / refused / error，带骨架屏加载态 |
| 报告内嵌 | `TurnCard` 组件直接渲染每轮报告内容 |
| Toast 通知 | sonner 集成，错误 / 成功即时反馈 |
| 后端健康检测 | shell layout 层自动探测后端连通状态 |

### 9. API 契约

共 **8 个端点**，契约冻结不可漂移：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/analyze` | POST (multipart) | 上传文件 + 提问 → `AnalyzeResponse` |
| `/v1/follow-up` | POST (JSON) | 追问，携带 `parent_id` |
| `/v1/batch` | POST (multipart) | 批量分析（manifest + 数据文件） |
| `/v1/sessions` | GET | 会话列表，支持分页和筛选 |
| `/v1/sessions/{id}` | GET | 会话详情（含所有 turns） |
| `/v1/sessions/{id}` | DELETE | 删除会话 |
| `/reports/{id}.html` | GET | 渲染好的报告 HTML |
| `/health` | GET | 健康检查 |
| `/version` | GET | 版本信息 |

**AnalyzeResponse 结构**：`id`, `report_html_url`, `summary`, `findings[]`, `charts[]`, `recommendations[]`, `is_refusal`, `confidence`

### 10. 工程质量

| 能力 | 说明 |
|---|---|
| 自测报告 | `自测报告/latest_evaluation_metrics.md`，15 个数据集实测，数字仅来自真实运行 |
| 测试覆盖 | 30+ 测试文件，涵盖 API / planner / executor / evidence / report / session / batch / spreadsheet ops |
| 类型安全 | Pydantic `extra="forbid"` strict model + 前端 TypeScript 类型 |
| 一键启动 | `运行脚本/start.sh` 从零克隆到运行 |
| Makefile 工作流 | `make install` / `make dev` / `make check`（lint + typecheck + test） |
| 提交规范 | 架构文档 / 运行脚本 / 演示视频 / 自测报告 四目录齐备 |

---

## 实测指标（截至 2026-05-06）

| 维度 | 当前值 | 目标 |
|---|---|---|
| 计划生成成功率 | 100% (15/15) | ≥ 95% |
| 沙箱执行成功率 | 100% | ≥ 98% |
| 证据可复算率 | 100% | 100% |
| 报告渲染成功率 | 100% | ≥ 99% |
| 图表种类覆盖 | 3 种 | ≥ 3 种 |
| 跟进调用成功率 | 93.3% | 100% |
| 综合拒答准确率 | 20% (1/5) | ≥ 95% |
| 误拒率 | 0% | ≤ 5% |

---

## 当前局限（已知待改进）

1. **图表种类不足**：仅 3 种（bar / line / pie），合约定义了 6 种（散点图 / 热力图 / 箱线图待补）
2. **拒答准确率偏低**：综合 20%，trap 识别算法需加强
3. **报告篇幅不足**：摘要平均 299 字，目标 800–2000 字
4. **会话状态无持久化**：纯内存，重启即丢失
5. **无认证机制**：赛事要求免登录，产品化需补充
6. **无作业队列**：单进程 asyncio，高并发场景未验证
7. **编码支持有限**：仅 UTF-8 系列，GBK / GB18030 未触发验证
