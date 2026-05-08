# TableTalker 产品能力清单

> 最后更新：2026-05-09 · 含 PR #21 / #22 / #23 能力变化（refuse op、
> 多 finding、batch 官方格式）。aigw 路径下的官方格式自测报告以
> `自测报告/latest_evaluation_metrics.md` 为准（仍是 5/8 89/100）。

## 产品定位

TableTalker 是一个结构化数据智能分析 Agent。评委或用户上传 CSV / Excel
文件，用自然语言提出分析需求，系统自动完成数据剖析、类型化计划规划、
pandas 算子执行、证据抽取、报告生成和多轮追问。

当前形态是赛事提交原型：优先服务「上传隐藏数据集 → 输入分析问题 →
查看交互式 HTML 报告 → 继续追问」的评测流程，同时提供批量评测和历史记录
能力，便于复盘。

## 已实现能力

### 1. 数据接入与剖析

| 能力 | 说明 |
|---|---|
| 单文件上传 | `/v1/analyze` 接受主数据文件 |
| 多文件上传 | `/v1/analyze` 接受 `extra_files`；TMDB movies + credits 已在 20 题回归中触发 |
| 文件格式 | 代码支持 `.csv` / `.xlsx` / `.xls`；上一轮 20 题实测触发 CSV 与多文件，Excel 冒烟用例已加入待重跑 |
| 上传限制 | 默认单文件 256 MiB、单请求总量 512 MiB；可用 `TABLETALKER_UPLOAD_MAX_BYTES` / `TABLETALKER_UPLOAD_MAX_TOTAL_BYTES` 调整 |
| 自动剖析 | 每列 dtype、缺失率、distinct count、top values、字段性质推断 |

### 2. 智能分析管线

| 能力 | 说明 |
|---|---|
| LLM 类型化规划 | 通过 AsiaInfo 兼容 OpenAI 协议的 LLM 网关生成结构化 JSON 计划 |
| 本地 pandas 执行 | LLM 不写 Python 代码；执行器运行白名单 pandas 算子处理器 |
| 15 个数据操作算子 | `load_csv`, `load_excel`, `select_columns`, `filter_rows`, `add_column`, `group_by`, `aggregate`, `sort`, `head`, `tail`, `join`, `pivot`, `melt`, `to_table`, `to_chart` |
| 表达式 DSL | 安全表达式解析，拒绝任意 `eval` / import / 属性访问 |
| 证据抽取 | 从 `OpResult` / 执行结果抽取 `dataset / table / columns / filters / aggregation / value / row_count` |
| 阶段计时 | `X-Stage-Timings` 暴露数据剖析、规划、执行、证据、定稿、渲染等阶段耗时 |

### 3. 报告生成

| 能力 | 说明 |
|---|---|
| 独立 HTML 报告 | `GET /reports/{id}.html` 在线访问 |
| 无 CDN 依赖 | ECharts 运行时作为本地资源内联到 HTML |
| 图表类型 | 6 类 ECharts：柱状图、折线图、饼图、散点图、热力图、箱线图（PR #21 加 heatmap+box） |
| 多 finding | finalize 输出 ≥2 个独立维度的关键发现，平均 2.9 个/case（PR #22） |
| 摘要长度 | 400-700 字范围，平均 ~650 字（PR #22） |
| 报告结构 | 摘要、关键发现、证据、图表、建议、拒答状态 |
| 拒答报告 | 拒答也生成 HTML 报告，避免 `report_html_url` 断链 |

### 4. 拒答与反幻觉

| 能力 | 说明 |
|---|---|
| LLM 自主拒答（主路径） | planner 系统提示教 4 类陷阱（字段缺失/维度错配/诱导幻觉/越权），命中即 emit `RefuseOp`；handler 短路 plan 执行（PR #22） |
| 结构性 Cat 4 兜底 | `_scan_plan_for_oob_paths` 扫描 plan op 中的 `path` 字段，命中绝对路径/URL/穿越段即在执行前转拒答 |
| 执行失败转 Cat 1 | planner 引用不存在的列时，executor KeyError 升级为 Cat 1 拒答 |
| 已删除 | `_TRAP_KEYWORDS` 关键词字典 + `_detect_refusal()` 在 PR #22 移除（不可泛化、违背 §7.4 #2 防作弊精神） |
| 统一话术 | 4 类话术维护在 `docs/refusal-policy.md`，对齐官方关键词要求 |
| 本轮实测 | trap_strict 92.9% (13/14)、trap_lenient 87% (13/15)、误拒 0% — 全靠 LLM 自主判断 |

### 5. 多轮追问

| 能力 | 说明 |
|---|---|
| 内存热层 | `app/session/store.py` 保存父轮工作目录、发现、客群、图表锚点、辅助文件 |
| SQLite 历史层 | `app/persistence/sessions.py` / `app/api/sessions.py` 提供历史索引、搜索、筛选、删除 |
| 多文件追问 | 父轮 `extra_files` 会保留，追问不会退化为单文件 |
| 本轮实测 | 追问成功率 100%，会话继承率 100% |

### 6. 批量处理

| 能力 | 说明 |
|---|---|
| Manifest 驱动 | `/v1/batch` 接收 JSONL / CSV manifest 与数据文件 |
| 双格式自动嗅探 | native（`question`/`file`）→ xlsx 输出；官方（`user_query`/`type`/`parent_id`）→ §5.2 兜底 zip（PR #23） |
| §5.2 zip 输出 | `predictions.jsonl` + `reports/{id}.html` + `MANIFEST.txt`，匹配赛题官方离线兜底契约 |
| 多任务并发 | 默认 `BATCH_CONCURRENCY=4`，可用环境变量调整 |
| 命令行 CLI | `eval/render_official_predictions.py` 不依赖 HTTP 服务运行（PR #23） |
| 前端页面 | `/batch` 批量入口（旧 `/v2/batch` 自动 308 → `/batch`） |

### 7. Web 界面

| 能力 | 说明 |
|---|---|
| 技术栈 | Next.js 15 + React 19 |
| 主要页面 | `/` 分析主页、`/history` 历史、`/batch` 批量、`/reports` 报告列表、`/status` 状态（旧 `/v2/*` 自动 308 重定向到对应根路径） |
| 上传交互 | 拖拽/点击上传 CSV、Excel，多文件在批量与 API 路径支持 |
| 状态反馈 | 分析中、完成、拒答、错误等状态明确展示 |
| 报告查看 | 前端代理 `/api/reports/{id}` 到后端 `/reports/{id}.html` |

### 8. API 契约

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/analyze` | POST multipart | 上传文件 + 提问，返回 `AnalyzeResponse` |
| `/v1/follow-up` | POST JSON | 基于 `parent_id` 追问 |
| `/v1/batch` | POST multipart | 批量评测；嗅探格式输出 xlsx 或 zip |
| `/v1/sessions` | GET | 会话列表、筛选、统计 |
| `/v1/sessions/{id}` | GET | 会话详情 |
| `/v1/sessions/{id}` | DELETE | 删除会话 |
| `/reports/{id}.html` | GET | HTML 报告 |
| `/health` | GET | 健康检查 |
| `/version` | GET | 版本信息 |

## 20 题回归指标（PR #22 后，newgw 内部测速）

| 维度 | 当前值 |
|---|---:|
| 主分析成功率 | 100% (20/20) |
| 证据完整率 | 100% |
| 图表种类覆盖 | 6 类 |
| 报告渲染成功率 | 100% |
| 平均 finding 数 | 2.9 / case |
| 平均 summary 长度 | 652 字 |
| 拒答准确率 | trap_lenient 87%，trap_strict 92.9% |
| 误拒率 | 0% |
| 多轮成功率 | 100% |
| 多文件能力 | 已触发 |
| Excel 能力 | 已触发 |

> 注：上面是 newgw 内部测速结果（非 reasoning 路径），仅供能力追踪。
> aigw 网关 + reasoning 路径下的官方格式自测报告仍以
> `自测报告/latest_evaluation_metrics.md` 为准。

## 当前局限

1. trap_strict 92.9% 压线 90% 阈值，隐藏 5 题如有 ≥1 个 LLM 误判
   会跌回 89%。Cat 3 诱导幻觉的 narrative 措辞稳定性需要更多验证。
2. Cat 1 字段缺失全靠 LLM 自主判断，民族 / 婚姻 / 年龄类 borderline
   trap 偶发漏判。
3. LLM 往返调用是主要性能瓶颈，aigw + reasoning 路径 P95 ~138s。
4. follow-up 在批量 §5.2 路径上跳过（标 status=skipped），符合
   §4.2「追问由评委即时发起」的描述但限制了完全离线兜底的能力。
