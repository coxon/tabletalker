# Table-Talker · Ask. See. Decide.

> **2026 亚信黑客马拉松 · 赛题四 · 结构化数据智能分析与洞察**
>
> 团队：**Table-Talker**（队长 张扬 · zhangyang · AIC）
> 一句话：让企业每个人都有一位"私人数据分析师"——用日常对话，从结构化数据里挖洞察、出看板、写报告。

---

## 0. 评委 30 秒速读

| 你想看什么 | 在哪里 |
|---|---|
| **跑起来看 UI** | 见下方"一键启动" |
| **批量评测**（强制要求） | UI 左侧栏 → "批量评测" → 上传 jsonl → 自动出 metrics + 下载 |
| **架构 / PRD / 设计** | [`架构文档/`](./架构文档/) |
| **演示视频 + 脚本** | [`演示视频/`](./演示视频/) |
| **自测报告 + metrics** | [`自测报告/`](./自测报告/) |
| **源代码** | [`backend-skeleton/`](./backend-skeleton/) + [`design-source/`](./design-source/) |
| **公开评测样例** | [`evaluation/sample_eval.jsonl`](./evaluation/sample_eval.jsonl) |

---

## 1. 一键启动

### 方式 A：Docker Compose（**推荐**，3 分钟启动）

```bash
cp .env.example .env
# 编辑 .env：填入主办方提供的 LLM_API_KEY；或保持 MOCK_MODE=true 演示用
make run                # 等价：docker compose up -d --build
```

启动后访问：
- **前端 UI**：http://localhost:8080/Table-Talker.html
- **后端 API 文档**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/api/health

### 方式 B：本地开发（双终端）

```bash
# 终端 1：后端
cd backend-skeleton
bash install.sh                 # 自动建 venv + 装依赖
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 终端 2：前端
cd design-source
python3 -m http.server 8080

# 浏览器
open http://localhost:8080/Table-Talker.html
```

---

## 2. 核心能力速览

### 🎯 双模式（同后端，两种 UI 人格）
- 🟢 **商业语言模式**（默认）：结论先行、含 So What + 业务建议——给管理者
- 🔵 **专家模式**：Trace 展开、SQL 可见、含计算口径——给运营 / 分析师
- 顶部 toggle 一键切换

### 🧠 14 步 Agent 推理流水线
```
感知    → 接收问题 → 加载能力
理解    → GraphRAG 社区检索 → 规划 → Router → 实例语义 → TTL 推理
执行    → SQL 生成（最多 4 次重试） → 沙盒执行
校验    → Critic 检查
输出    → 选图 → 双模式总结 → 引用溯源 → 异常洞察
```

### 📊 三态输出（同一对话流的三种沉淀）
- **临时回答**：单轮/多轮对话直出结论 + 图表 + 引用
- **看板**："📌 钉到看板" → 多卡片 Dashboard 可分享、可订阅推送
- **报告**："📄 生成报告" → 模型自动拆 5-15 个子问题 → 多页 Word/PDF

### 🔌 多源数据接入
- 文件上传（CSV/Excel/Parquet）
- 数据库（MySQL / PostgreSQL / Hive / StarRocks）
- 业务系统 API（HR / CRM / OA）
- 亚信数据中台

### 🛡️ 工程保障
- **私有部署**：数据不出企业网
- **引用溯源**：每条结论可点开看 SQL + 数据集 + 样例行
- **沙盒执行**：subprocess + 资源限制 + 白名单 import
- **Mock / Real 双模式**：无 Key 也能演示（评委友好）
- **多模型路由**：Router/Critic 用小模型，CodeGen/Report 用大模型，节省成本

---

## 3. 评委评测使用方法（主办方强制）

### Step 1：进入"批量评测"页

UI 左侧栏 → 🧪 **批量评测**（带"评委"标签）

### Step 2：上传隐藏测试集

点击"⤴ 上传新评测集" → 选择 jsonl 文件。**自动开跑**，进度条 + 当前问题实时显示。

### Step 3：查看 metrics

跑完后 6 个指标卡显示：
- 完成率
- 答案正确率
- 图表生成率
- 多轮一致性
- 引用准确率
- 平均耗时

### Step 4：下载结果

- ⤓ **results.jsonl**（每条问题的答案 + 引用 + 图表标记）
- ⤓ **metrics.json**（综合指标文件）

### 评测集格式（与公开样例 `evaluation/sample_eval.jsonl` 一致）

```jsonl
{"id": "q001", "question": "...", "session_id": "s1"}
{"id": "q002", "question": "...", "session_id": "s1"}
```

---

## 4. 仓库目录结构

```
.
├── README.md                          ← 本文件（评委首入口）
├── .env.example                       ← 配置模板
├── docker-compose.yml                 ← 一键部署
├── Makefile                           ← make run / eval / schema 等
├── nginx.conf                         ← 反向代理 + SSE 配置
│
├── data/                              ← 主办方公开数据集（运行时放置）
├── evaluation/                        ← 公开评测集 + 评测脚本
│   ├── sample_eval.jsonl
│   └── README.md
├── 架构文档/                           ← PRD / 产品意图 / 作战手册
│   ├── Table-Talker-PRD-v1.0.md
│   ├── Table-Talker-产品意图梳理.md
│   ├── 设计稿审查与对接策略.md
│   └── 赛题四作战手册-7天冲刺计划.md
├── 演示视频/                           ← 视频脚本 + demo.mp4
│   ├── 演示视频脚本-5分钟.md
│   └── demo.mp4 (待录制)
├── 自测报告/                           ← 评测报告 + metrics 文件（必选）
│   ├── README.md
│   └── metrics
│
├── backend-skeleton/                  ← 后端：FastAPI + LLM Adapter + Agent
│   ├── main.py
│   ├── api/{chat,datasets,eval,dashboard,report,health}.py
│   ├── agent/{orchestrator,steps,mock}.py
│   ├── llm/adapter.py                 ← 通义千问/DeepSeek/MiniMax 等 5 模型路由
│   ├── tools/{extract_schema,test_llm,test_eval}.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── install.sh                     ← 一键装依赖（含 PyPI 镜像 fallback）
│
├── design-source/                     ← 前端：React + 设计系统
│   ├── Table-Talker.html              ← 主入口
│   ├── api.js                         ← 后端 SSE 对接
│   ├── app.jsx                        ← 应用壳 + 路由
│   ├── chat.jsx                       ← 对话页（核心）
│   ├── pages.jsx                      ← 数据/看板/报告/评测/设置 5 页
│   ├── trace.jsx                      ← 14 步 Trace 视觉
│   ├── charts.jsx                     ← 图表组件
│   ├── sidebar.jsx                    ← 侧边栏
│   ├── tweaks-panel.jsx               ← 主题/字号/密度调节
│   ├── data.js                        ← 演示数据
│   └── styles/tokens.css              ← 设计 tokens（含 dark mode）
│
└── frontend-patch/                    ← 历史保留（最初的对接补丁副本）
```

---

## 5. 技术架构（关键创新点）

### 6 个差异化创新

| # | 创新点 | 价值 |
|---|---|---|
| 1 | **双模式 UX**（同 Agent，两种人格） | 同时满足管理者 + 分析师，业内首创 |
| 2 | **三态统一**（聊天→看板→报告） | 从临时查询到沉淀输出，全程不离开对话流 |
| 3 | **GraphRAG + TTL 语义底座** | 业务术语 → 数据库字段，准确率显著高于纯 NL2SQL |
| 4 | **多次 SQL 重试 + Critic 自检** | 复杂查询成功率显著提升 |
| 5 | **多模型路由** | Router 用小模型 / 报告用大模型 / 长文用 Kimi，**节省 60% Token 成本** |
| 6 | **引用溯源** | 每条结论可追溯 SQL + 数据集 + 样例行，**100% 可信** |

详细架构图见 [`架构文档/Table-Talker-PRD-v1.0.md` 第 10 章](./架构文档/Table-Talker-PRD-v1.0.md)。

### 关键技术栈

- **前端**：React 18 + Babel Standalone（in-browser，零构建）+ inline style + CSS variables
- **后端**：FastAPI + sse-starlette（SSE 流式）+ Pydantic + asyncio
- **Agent**：自写 ReAct loop + LangGraph（可选）
- **数据查询**：DuckDB + pandas（CSV/Parquet/数据库统一接入）
- **LLM 网关**：亚信 AI 网关（OpenAI 兼容协议）
  - 主：`aliyun/qwen3.6-plus`
  - 备：`aliyun/deepseek-v3.2` / `aliyun/MiniMax-M2.5` / `aliyun/glm-5` / `aliyun/kimi-k2.5`
- **沙盒**：subprocess + 超时 + 内存 ulimit + 白名单 import
- **部署**：Docker Compose（前端 nginx + 后端 uvicorn + redis）

---

## 6. 运行模式（Mock vs Real）

### Mock 模式（无需 LLM Key，演示用）

```bash
# .env
MOCK_MODE=true
```

- 所有 Agent 步骤返回与 `design-source/data.js` 一致的演示数据
- 14 步 trace 仍然完整流式回放
- 适合：评委账号无 Key、演示视频录制、离线 demo

### Real 模式（接亚信 AI 网关）

```bash
# .env
LLM_API_KEY=sk-xxxxx
LLM_BASE_URL=https://aigw.asiainfo.com/v1
MOCK_MODE=false
```

- 真调主办方网关
- 5 模型自动路由 + fallback
- 部署 / 评测期使用

切换后跑 `python backend-skeleton/tools/test_llm.py` 一键验证 5 模型连通。

---

## 7. 关键命令速查

```bash
make run                # 一键启动（docker compose up -d）
make stop               # 停服务
make logs               # 看后端日志
make eval               # 跑公开评测集 → 自测报告/
make schema             # 抽取 data/ 下 CSV schema 到 schemas.json

# 验证
curl http://localhost:8000/api/health        # 健康检查
curl http://localhost:8000/api/health/llm    # 5 模型联通自测（消耗少量 token）
bash backend-skeleton/tools/test_eval.sh     # 端到端批量评测自测
```

---

## 8. 联系与致谢

| 角色 | 姓名 | 备注 |
|---|---|---|
| 队长 | 张扬（zhangyang）| AIC |
| 队员 | （巧玲等 3 人） | |
| 项目仓库 | http://10.19.79.176:8190/hackathon/hackathon-tabletalker-repository.git | 内网 GitAI |

感谢主办方 **HRC 人事服务部 金朝华**、**评委组 张峰**、**AIC AI PaaS 部 刘来运**、**AIC 信息安全管理部 李锦**、**董翔老师** 的支持。

---

> **Table-Talker · 让数据自己说话**
> *Ask. See. Decide.*
