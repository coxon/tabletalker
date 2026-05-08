# TableTalker

A data analysis agent. Give it a CSV or Excel file and a plain-English
question; get back an interactive HTML report with follow-up Q&A grounded
in the data.

> 🚧 In active development — see [`docs/roadmap.md`](docs/roadmap.md) for the
> shipping plan.

## Project layout

```
src/backend/      FastAPI service (Python 3.11+, managed by uv)
src/frontend/     Next.js 15 + React 19 app (managed by pnpm)
src/templates/    Jinja templates for HTML reports (filled in PR #5)
架构文档/          architecture docs (organizer-required)
运行脚本/          `start.sh` — boots from a clean clone
演示视频/          demo video (filled in PR #9)
自测报告/          `latest_evaluation_metrics.md` — read directly by
                   the organizer's auto-grader; numbers are measured,
                   never estimated
docs/             internal engineering docs — `roadmap.md`,
                   `architecture.md`, `submission-contract.md`,
                   `scoring-map.md`, `refusal-policy.md`,
                   `session-state.md`
tests/            cross-cutting tests
```

`PRODUCT.md` is the product brief. `CLAUDE.md` is the per-repo guidance for
Claude Code.

## Local development

Prereqs: [`uv`](https://docs.astral.sh/uv/), Node 20+, `pnpm` (via
`corepack enable`), GNU `make`.

```bash
make install   # backend (uv sync) + frontend (pnpm install)
make dev       # backend on :8000, frontend on :3000, Ctrl+C stops both
make check     # lint + typecheck + test (the pre-PR gate)
```

Quick smoke check once `make dev` is up:

```bash
curl localhost:8000/health           # → {"ok": true}
curl localhost:3000/api/health       # dev → {"ok": true, "backend": "..."}; prod → {"ok": true}
# Open http://localhost:3000 in your browser → "Hello, TableTalker"
# (mac: `open URL` · linux: `xdg-open URL` · windows: `start URL`)
```

Containerization is deferred to a later PR — local-first dev loop comes first.

## Submission (organizer view)

The organizer's grader pulls the repo (default → master → main, in that
order), then:

1. Reads `自测报告/latest_evaluation_metrics.md` for self-reported metrics.
2. Runs `bash 运行脚本/start.sh` to bring the system up.
3. Hits `POST /v1/analyze` with the JSON contract frozen in
   [`docs/submission-contract.md`](docs/submission-contract.md).
4. Opens `report_html_url` and the `演示视频/` recording.

See [`docs/scoring-map.md`](docs/scoring-map.md) for how each rubric line
maps to a module and PR, and [`docs/refusal-policy.md`](docs/refusal-policy.md)
for the four trap categories and their canonical phrasings.

## Web UI 功能说明

启动后打开 `http://localhost:3000`，顶部导航栏包含三个页面：

### 提问分析（首页）

1. 上传一个 CSV 或 Excel 文件（≤ 20 MiB）。
2. 输入分析问题，点击"开始分析"或按 `⌘+Enter`。
3. 等待 30–60 秒，系统自动生成带图表的 HTML 报告。
4. 在报告下方的追问区域继续提问，基于同一份数据深入分析。

### 历史分析（/history）

查看所有历史分析会话，支持：
- 按标题或文件名搜索
- 按状态筛选（已完成 / 已拒答）
- 点击展开查看每轮问答详情和报告链接
- 删除不需要的记录

### 批量评测（/batch）

用于一次性运行多个分析任务：

1. 准备 manifest 文件（JSONL 或 CSV 格式），每行描述一个任务：
   ```jsonl
   {"file": "sales.csv", "question": "哪个月销售额最高？"}
   {"file": "orders.csv", "question": "退货率最高的品类是什么？"}
   ```
   字段：`file`（数据文件名）、`question`（分析问题）。
   可选字段：`extra_files`、`sampling_rate`。

2. 上传 manifest 文件（.jsonl 或 .csv）。
3. 上传对应的数据文件（可多选 .csv / .xlsx）。
4. 点击"开始批量评测"，等待所有任务完成。
5. 完成后自动下载 `tabletalker-batch-results.xlsx` 结果文件。

## License

[Apache 2.0](LICENSE).
