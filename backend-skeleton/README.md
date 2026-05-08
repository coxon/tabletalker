# Table-Talker 后端骨架

> FastAPI + SSE + DuckDB + 双模式 LLM Adapter（通义/DeepSeek 切换）

## 一、5 分钟跑通

```bash
cd backend-skeleton
pip install -r requirements.txt --break-system-packages
cp .env.example .env
# 编辑 .env：先用 MOCK_MODE=true 跑通，无需 API Key

# 启动
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 测试
curl http://localhost:8000/api/health
```

打开 http://localhost:8000/docs 看 OpenAPI 文档。

## 二、目录结构

```
backend-skeleton/
├── main.py                # FastAPI 入口
├── requirements.txt       # 依赖
├── Dockerfile             # 容器
├── .env.example           # 环境变量模板
├── api/                   # HTTP 路由层
│   ├── chat.py            # SSE 流式对话（核心）
│   ├── datasets.py        # 数据接入
│   ├── eval.py            # 批量评测（强制要求）
│   ├── dashboard.py       # 看板
│   ├── report.py          # 报告生成
│   └── health.py          # 健康检查
├── agent/                 # Agent 推理层
│   ├── orchestrator.py    # 14 步主流程
│   ├── steps.py           # 各原子步骤实现
│   └── mock.py            # Mock 模式数据（与设计稿一致）
├── llm/                   # LLM 适配层
│   └── adapter.py         # 通义/DeepSeek 切换 + 模型路由
├── tools/                 # 工具脚本
│   └── extract_schema.py  # 离线 schema 抽取
├── data/                  # 数据集（用户上传 / 公开评测集）
└── schemas.json           # 离线生成的 schema 缓存
```

## 三、API 与设计稿对接（关键）

设计稿 chat.jsx 直接调用：

```javascript
// 前端 SSE 消费示例（替换 chat.jsx 中的 mock 模式）
const evtSource = new EventSource('/api/chat/stream', {
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({question, mode: 'business'})
});
evtSource.addEventListener('trace_step', e => {
  const data = JSON.parse(e.data);
  // 更新对应步骤状态
});
evtSource.addEventListener('answer_chunk', e => {
  // 流式追加文本
});
evtSource.addEventListener('chart', e => {
  // 渲染图
});
```

> 实际用 `fetch` + `ReadableStream` 更兼容，详见 `frontend-patch/api.js`。

### 事件协议

| 事件 type | 字段 | 说明 |
|---|---|---|
| `trace_step` | i, name, group, status(running/done/skip), duration_ms, badge | 14 步推理 |
| `answer_chunk` | mode, text | 流式答案（typewriter） |
| `chart` | kind(bars/line/donut/heat/kpi), title, data | 图表 |
| `insight` | kind, text, severity(low/med/high) | 异常洞察 |
| `citation` | datasets, columns, sql, sample, rows | 引用溯源 |
| `followups` | business[], expert[] | 双模式追问 |
| `complete` | message_id, total_ms | 完成 |
| `error` | message | 异常 |

## 四、Mock 模式 vs 真实模式

| 模式 | 用途 | 启用方式 |
|---|---|---|
| **Mock**（默认推荐先跑） | 演示、视频录制、无 API Key | `MOCK_MODE=true` |
| **真实** | 接通义千问/DeepSeek | `MOCK_MODE=false` + 设 `QWEN_API_KEY` |

Mock 模式下所有接口仍然工作，但数据来自 `agent/mock.py`（与设计稿 `data.js` 完全一致）。

## 五、对接 LLM（5/4 上午做）

```bash
# 1. 拿到 API Key（队长张扬找董翔老师）
# 2. 改 .env
QWEN_API_KEY=sk-xxxxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.6-plus
MOCK_MODE=false

# 3. 跑通验证
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Q1 华南销售下滑原因", "mode": "business"}'
```

如果某步报错，依次：
1. 看 `data/` 是否有 CSV
2. 跑 `python tools/extract_schema.py` 生成 `schemas.json`
3. 把 `agent/steps.py` 中失败的那一步降级为 mock fallback

## 六、数据准备（5/4 下午做）

把主办方公开数据集放到 `data/`：

```bash
mkdir -p data
# 把 15 个 CSV 拷进来
cp /path/to/contest/data/*.csv data/

# 抽取 schema
python tools/extract_schema.py --data-dir ./data --out ./schemas.json
```

## 七、运行检查

```bash
# 健康检查
curl http://localhost:8000/api/health

# 对话（mock 模式）
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Q1 华南销售环比", "mode": "business"}'

# 数据集列表
curl http://localhost:8000/api/datasets/

# 批量评测（上传 jsonl）
curl -F "file=@../frontend-demo/sample_eval.jsonl" \
  http://localhost:8000/api/eval/run
# 返回 task_id 后再
curl -N http://localhost:8000/api/eval/stream/<task_id>
```

## 八、与前端联调步骤

```
1. 后端 (本目录) 启动 → 8000 端口
2. 前端 (design-source/) 启动：
   cd ../design-source
   python3 -m http.server 8080
3. 浏览器访问 http://localhost:8080/Table-Talker.html
4. 改 design-source/Table-Talker.html，加：
   <script src="api.js"></script>
   并设 window.TT_API_BASE = "http://localhost:8000"
5. chat.jsx 中的 mock setInterval 替换为 TT_API.chatStream(...)
   （详见 frontend-patch/）
```

## 九、TODO（按 7 天计划）

- [x] FastAPI 骨架 + SSE 协议
- [x] LLM Adapter（通义/DeepSeek）
- [x] Mock 模式（与设计稿一致）
- [x] 14 步 orchestrator
- [x] DuckDB 沙盒
- [x] 自动选图
- [x] 异常检测（IQR 法）
- [x] 批量评测
- [ ] schema 抽取脚本（已写，需跑）
- [ ] Docker Compose 集成（前端+后端+Redis）
- [ ] GraphRAG 真实实现（D3 升级）
- [ ] TTL RDFLib 真实实现（D3 升级）
- [ ] 看板/报告 持久化（D4 升级）
- [ ] 多租户/审计/SSO（D5+）
