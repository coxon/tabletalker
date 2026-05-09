# 评分映射

本文件把赛题 4 官方评分项映射到当前实现和已测产物。

官方总分：

`final score = objective score * 50% + subjective score * 50%`

客观项和主观项各自满分 100。

## 客观项

官方客观项读取 `自测报告/latest_evaluation_metrics.md`。当前测量来源：

`eval/runs/eval20-official-20260508-223200/summary.json`

| 官方项 | 分值 | 当前 owner | 当前证据 |
|---|---:|---|---|
| 数据接入 | 20 | `app/api/analyze.py`, `app/limits.py`, `app/analyze/profiler.py`, `app/spreadsheet/ops/load.py` | CSV 和多文件已触发；Excel 冒烟用例已加入，待重跑刷新 |
| 单轮交互 | 智能交互的一部分 | `app/analyze/handler.py`, `app/api/analyze.py` | 主分析 18/20 成功 |
| 多轮交互 | 智能交互的一部分 | `app/api/follow_up.py`, `app/session/store.py`, `app/session/prompt.py` | follow-up 94.4%，session carry 94.4% |
| 拒答说明 | 智能交互的一部分 | `app/analyze/handler.py`, `docs/refusal-policy.md` | 陷阱题宽松判定 10/10，严格判定 9/9，误拒 0 |
| 统计分析 | 16 | `app/spreadsheet/executor.py`, `app/spreadsheet/ops/*`, `app/analyze/evidence.py` | evidence 完整率 100% |
| 趋势分析 | 18 | planner + typed ops + finalize | 最新自测 16/18 |
| 根因分析 | 26 | 规划器 + 定稿器 + 建议生成 | 最新自测 22/26 |

当前自测分：**89 / 100**。

主要客观缺口：

- Excel 未在最新 run 中触发，自测报告诚实标为 `否`。
- 主分析 18/20；失败包含一次 LLM gateway timeout 和一次 planner/executor 列名边界问题。
- 趋势和根因结论通常正确，但解释偏浅。

## 主观项

| 官方项 | 分值 | 当前 owner | 当前状态 |
|---|---:|---|---|
| 架构分层 | 12 | `架构文档/design_doc.md`, `docs/architecture.md`, 前后端结构 | 较强：前端、后端、类型化计划、报告、会话分层清晰 |
| 扩展性 | 12 | typed op schema、chart factory、batch/session API | 较好：新增 op/chart 影响局部，但没有插件运行时 |
| 性能设计 | 8 | `app/analyze/stages.py`, `X-Stage-Timings`, 上传限制, LLM timeout | 可观测但慢：P95 174.6s，瓶颈在 LLM |
| 安全设计 | 8 | LLM 不写代码、上传路径隔离、表达式 DSL、代理信任控制 | 满足赛事范围；免登录是赛事要求 |
| 交互创新 | 8 | Web 界面、报告、追问、历史 | 较好；公网 URL 和演示视频待补 |
| 数据处理创新 | 8 | 数据剖析、类型化计划、结构化证据 | 较好；JSON 嵌套仍是缺口 |
| 分析算法 | 15 | 类型化规划器、证据构造器、拒答 | 较好；TMDB JSON 和根因深度是风险 |
| 报告设计 | 5 | ECharts 报告渲染器 | 较好；热力图、箱线图尚未输出 |
| 架构文档 | 5 | `架构文档/design_doc.md` | 基本就绪；数据库字典可更显式 |
| DEMO 视频 | 5 | `演示视频/` | 缺失，只有 `.gitkeep` |
| 自测报告 | 5 | `自测报告/latest_evaluation_metrics.md` | 最新且可追溯 |
| Git 质量 | 5 | README, LICENSE, 结构, 测试 | 较好；README 仍需填公网 URL |

## 官方高风险条款

| 官方风险 | 当前缓解 | 剩余缺口 |
|---|---|---|
| URL 不可访问 | `start.sh` 可本地启动，`APP_PUBLIC_URL` 已配置 | 仍需公网免登录 URL |
| evidence 幻觉 | 数值来自 typed-op 执行和 `OpResult` | JSON 嵌套字段仍可能导致差计划 |
| 错误拒答 | 硬信号拒答 + 缺失列执行错误转拒答 | 诱导幻觉 / 越权样本需扩充 |
| JSON 嵌套字段 | 已列为限制 | TMDB cast/crew/genres 需实现或清晰降级 |
| 图表多样性 | 已观测 4 类 | 仍无热力图、箱线图 |
| 追问丢上下文 | session 保存父轮文件、findings、cohorts、extra files | 最新 run 有 1 个 follow-up timeout |
| 采样未声明 | eval runner 会转发 `sampling_rate` | 当前 telecom 使用完整 CSV，未采样 |

## 测试位置

多数测试在 `src/backend/tests/`，不是根目录 `tests/`。常用入口：

- `test_analyze_api.py`
- `test_analyze_evidence.py`
- `test_eval_render_official.py`
- `test_eval_run_validators.py`
- `test_followup_api.py`
- `test_report_charts.py`
- `test_session_*`
- `test_spreadsheet_*`
