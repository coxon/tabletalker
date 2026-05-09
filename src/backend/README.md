# TableTalker 后端

FastAPI 服务，负责上传接入、数据剖析、类型化计划规划、pandas 算子执行、
evidence 抽取、报告渲染、追问、批量评测和历史记录。

## 本地启动

从仓库根目录推荐使用：

```bash
make dev
```

或单独启动后端：

```bash
cd src/backend
uv sync --dev
uv run uvicorn app.main:app --reload --port 8000
```

## 主要接口

- `GET /health`：健康检查
- `GET /version`：版本信息
- `POST /v1/analyze`：主分析请求
- `POST /v1/follow-up`：基于 `parent_id` 的追问
- `POST /v1/batch`：manifest 驱动批量分析，返回 xlsx
- `GET /v1/sessions`：历史会话列表
- `GET /v1/sessions/{id}`：历史会话详情
- `DELETE /v1/sessions/{id}`：删除历史会话
- `GET /reports/{id}.html`：HTML 报告

## 配置

后端读取仓库根目录 `.env` 中的 LLM 与服务配置。示例见 `.env.example`。
