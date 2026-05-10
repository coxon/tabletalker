# 路线图

TableTalker 以小步 PR 推进，最终提交目标是 2026-05-10 18:00（中国标准时间）。

## 已完成里程碑

| # | 分支 / 主题 | 目标日期 | 范围 | 状态 |
|---|---|---|---|---|
| 1 | `docs/bootstrap` | 5/4 | README、路线图、CodeRabbit 配置 | ✅ |
| 2 | `chore/skeleton` | 5/5 | Next.js + FastAPI 骨架、Makefile、CI | ✅ |
| 3 | `feat/spec-alignment` | 5/5 | 提交契约、拒答策略、评分映射、自测报告 v0、数据集放置 | ✅ |
| 3.5 | `feat/spreadsheet` | 5/6 | 类型化计划引擎、15 个 pandas 算子、结构化追踪 | ✅ |
| 4 | `feat/analyze-pipeline` | 5/7 | 数据剖析 → 规划 → 执行 → 证据 → 契约响应 | ✅ |
| 5 | `feat/report-render` | 5/8 | Jinja HTML 报告、内联 ECharts、`report_html_url` | ✅ |
| 6 | `feat/followup-session` | 5/8 | Session state、follow-up、拒答分类、多轮 UI | ✅ |
| 7 | `feat/web-ui` | 5/9 | 上传、提问、进度状态、报告 iframe | ✅ |
| 8 | `chore/evaluation` | 5/9 | 自测、性能测量、自测报告刷新 | ✅ |
| 9 | `chore/submission` | 5/10 | DEMO 视频、公网 URL、最终提交 | ☐ |
| 16 | `feat/batch` | 5/8 | `/v1/batch` 批量评测与 xlsx 输出 | ✅ |
| 17 | `feat/official-metrics` | 5/8 | 官方 9 节自测报告渲染器 | ✅ |
| 18 | `feat/session-history` | 5/8 | SQLite 历史索引与 `/v1/sessions` API | ✅ |
| 19 | `feat/frontend-shell` | 5/8 | 分析、历史、批量、报告、状态页面（最初挂在 `/v2/*`，后由 PR #21 提为根路径） | ✅ |
| 20 | `fix/dotenv-planner-reports` | 5/8 | 20 题提交回归、多文件 TMDB、完整 telecom、自测报告刷新 | ✅ |
| 21 | `fix/dotenv-planner-reports` (cont.) | 5/9 | 错误路径 stage_timings + executor 输入形状日志 + start.sh 落盘；v2 提为默认路径；`heatmap`/`box` 图表；`join` 非对称键 + 模糊建议；`explode_json` 算子 + JSON 列识别；trap 样本补诱导/越权；模型选型决策入档 | ✅ |
| 22 | `fix/dotenv-planner-reports` (cont.) | 5/9 | LLM-driven 拒答：新增 `RefuseOp` 类型化算子 + planner prompt 教 4 类陷阱 + handler 短路；移除 `_TRAP_KEYWORDS` 关键词分类器；结构性 Cat 4 路径扫描；`evidence` 渲染白名单加 `lower/upper/len/if`；DSL 算术类型校验；finalize 多 finding 输出（≥2，平均 2.9）+ summary 400-700 字 | ✅ |
| 23 | `fix/dotenv-planner-reports` (cont.) | 5/9 | Batch 端点支持官方 jsonl 格式（`user_query` / `type` / `parent_id` 嗅探）+ §5.2 兜底 zip 输出（predictions.jsonl + reports/）；CLI 工具 `eval/render_official_predictions.py`；样本生成器 `eval/build_official_requirements.py` | ✅ |

## 合并规则

- 每次改动保持范围清晰。
- 改动能力或评分口径时，同步更新 `自测报告/latest_evaluation_metrics.md`。
- 自测报告数字只来自真实运行，不手工拔高。
- 提交前至少跑相关 lint / pytest。

## 提交 Gate

| 项 | 状态 |
|---|---|
| 公网免登录 URL 可访问 | ✅ https://table-talker-frontend-ai-llm.apps.dc2.asiainfo.com/ |
| 自测报告反映真实测量 | ✅ |
| `架构文档/design_doc.md` 已对齐当前架构 | ✅ |
| `演示视频/` 包含最终 demo | ☐ |
| `运行脚本/start.sh` 可从干净 clone 启动 | ✅ |
| 默认分支是组委会应拉取的分支 | ☐ |
| 至少 3 类图表端到端可用 | ✅ |
| 拒答使用固定中文话术 | ✅ |
| 多轮追问保留上下文 | ✅ |

## 当前最高优先级

1. 录制并提交 DEMO 视频。
2. 在 aigw + reasoning 模式下重跑 20 题，把 PR #21-#23 的能力变化反映到
   `自测报告/latest_evaluation_metrics.md`（当前自测报告仍是 5/8 的
   89/100 数据，PR #21-#23 之后的能力变化未体现）。
3. 提交前合并到默认分支并设为送测分支。
