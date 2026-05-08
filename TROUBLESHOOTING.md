# 故障排查手册 · Troubleshooting

> Table-Talker 常见错误一览。**演示前 / 提交前 / 决赛日**遇到问题查这里。
> 排不出来跑 `bash smoke-test.sh` 拿具体失败项。

---

## 🩺 万能诊断流程（30 秒）

```zsh
cd /Users/zhangql/cc/黑松客比赛asiainfo
bash smoke-test.sh
```

输出会标出"哪一项挂了"。然后按下面的章节对应排查。

---

## 一、启动 / 部署

### Q1.1 `bash start.sh` 报 `❌ 找不到 backend-skeleton/.venv`

**原因**：venv 没建。

```zsh
cd backend-skeleton
bash install.sh
```

或者手动：

```zsh
cd backend-skeleton
python3.12 -m venv .venv
source .venv/bin/activate
pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

### Q1.2 `Address already in use` 8000/8080 端口被占

```zsh
bash stop.sh             # 一键清理
# 或手动
lsof -ti :8000 | xargs kill -9
lsof -ti :8080 | xargs kill -9
```

### Q1.3 `bash start.sh` 后端启动超时（15s 仍不 OK）

看错误日志：

```zsh
tail -50 .run/backend.log
```

常见原因：
- **`ImportError: No module named X`** → venv 装包不全，重跑 `pip install -r requirements.txt`
- **`sqlite3.OperationalError: unable to open database file`** → 工作目录没写入权限，确认 `chmod 755 .` + 不要在系统目录下跑
- **`AttributeError: ... 'NoneType' object`** → schemas.json/graphrag_index.json 缺失，跑 `python tools/extract_schema.py` + `python tools/build_graphrag.py`

### Q1.4 `docker compose up -d` 报错

```zsh
docker compose logs -f backend  # 看后端容器日志
docker compose ps                # 看容器状态
```

| 错误 | 原因 | 解 |
|---|---|---|
| `port is already allocated` | 8000/8080 被宿主进程占 | `bash stop.sh` 后再跑 |
| `permission denied while trying to connect to docker daemon` | docker 服务没起 | macOS：打开 Docker Desktop；Linux：`sudo systemctl start docker` |
| `pull access denied` | 私有 registry 没登录 | `docker login registry.aigw.asiainfo.com` |
| `no space left on device` | docker 镜像占满磁盘 | `docker system prune -af` |

---

## 二、LLM 调用

### Q2.1 5 个模型全 `Connection error` 或 timeout

**90% 是没在亚信内网 / VPN**。`aigw.asiainfo.com` 是 10.x.x.x 内网域。

```zsh
# 验证
nslookup aigw.asiainfo.com
curl -v --max-time 5 https://aigw.asiainfo.com/v1
```

如果 `Could not resolve host` 或 `Connection timed out`：
- 连亚信 VPN
- 或在亚信办公网络
- 或临时改 .env 切回 `MOCK_MODE=true` 演示

### Q2.2 某个模型 `404 model not found`

模型名前缀漏了。检查 .env：

```bash
✅ aliyun/qwen3.6-plus
❌ qwen3.6-plus
✅ aliyun/deepseek-v3.2
❌ deepseek-v3.2
```

### Q2.3 `401 Unauthorized`

Key 错。

```zsh
grep LLM_API_KEY .env
# 必须以 sk- 开头，无多余空格
```

如果 Key 真的失效（信安部跟踪到泄漏会重置），找 **AIC 信息安全管理部 - 李锦**。

### Q2.4 `429 Too Many Requests`

配额限流。`adapter.py` 已经有 fallback chain，自动切下一个模型。如果 5 个全限流，等 1 分钟再试，或联系金朝华扩配额。

### Q2.5 演示中切到真模式怕崩

**最稳的策略**：演示视频用 `MOCK_MODE=true` 录制（保证可控）；评委复测时用 `MOCK_MODE=false`。

---

## 三、前端

### Q3.1 浏览器打开 `http://localhost:8080/Table-Talker.html` 一片白屏

按 F12 看 Console：
- **`Unexpected token`** → Babel 编译失败，硬刷 ⌘+Shift+R 清缓存
- **`Failed to fetch`** → 后端没起，跑 `bash start.sh`
- **`React is not defined`** → CDN 加载失败，确认能访问 unpkg.com 或换 jsdelivr

### Q3.2 切对话/页面没反应

- 检查 Console 有没有红字错误
- 关 DevTools 再重开
- ⌘+Shift+R 硬刷新

### Q3.3 14 步 trace 不动

后端没接通。Console 应该有：
```
[TT_API] streamEval response: 200 OK
[TT_API] streamEval ended, chunks=10  ← 但中间没有 event 日志
```

→ SSE 解析 `\r\n\r\n` 兼容已修。如果还有，确认浏览器**真硬刷**了，可能 jsx 缓存。

### Q3.4 批量评测进度条不动

- 后端日志看 `/api/eval/stream/<task_id>` 是否 200
- 用 `bash backend-skeleton/tools/test_eval.sh` 离线测一遍

### Q3.5 演示中浏览器突然崩了

- 关 DevTools
- 关 Tweaks 面板（防抖动）
- 换 Chrome / Safari 重开
- 极端情况：URL 加 `?mock=true` 强制前端纯本地 mock，不依赖后端

---

## 四、数据 / Schema

### Q4.1 `schemas.json` 不存在警告

```zsh
cd backend-skeleton
source .venv/bin/activate
python tools/extract_schema.py --data-dir ../data --out ../schemas.json
```

### Q4.2 没有 mock 数据

```zsh
python tools/generate_mock_data.py    # 生成 15 个 CSV 到 data/
python tools/extract_schema.py        # 抽 schema
python tools/build_business_terms.py  # 业务术语词典
python tools/build_graphrag.py        # GraphRAG 索引
bash ../stop.sh && bash ../start.sh   # 重启加载
```

### Q4.3 主办方真实数据集和 mock 字段名不一致

替换 `data/` 下 CSV 后**必须重跑**：

```zsh
python tools/extract_schema.py
```

否则 Agent 用的还是旧 schema。

---

## 五、数据库 / 持久化

### Q5.1 看板"钉住"了重启后丢

确认 `tt.db` 在哪：

```zsh
ls -la backend-skeleton/tt.db
```

- 本地：在 `backend-skeleton/` 下
- Docker：在 `/app/tt.db`，需要 docker-compose 加 volumes

### Q5.2 Docker 部署后数据丢

`docker-compose.yml` 加挂载：

```yaml
services:
  backend:
    volumes:
      - ./tt-data:/app   # 持久化 tt.db
```

### Q5.3 SQLite `database is locked`

并发写冲突。重启后端：

```zsh
bash stop.sh && bash start.sh
```

生产化时换 PostgreSQL（`requirements.txt` 已有 psycopg2-binary）。

---

## 六、Git / 推送

### Q6.1 `Connection refused 10.19.79.176`

不在亚信内网。详见 [推送到-GitAI.md](./推送到-GitAI.md) 第 4 章。

### Q6.2 `Authentication failed`

NT 账号密码错。亚信 NT 账号是 `zhangql` 而不是 `zhangql@asiainfo.com`。

### Q6.3 `pre-receive hook declined`

仓库可能要求 PR 流程。联系 **AIC AI PaaS 部 - 刘来运**。

### Q6.4 误把 .env push 了

```zsh
git rm --cached .env
echo ".env" >> .gitignore
git commit -am "chore: 移除 .env"
git push --force   # 谨慎用
```

立刻联系 **AIC 信安部 - 李锦** 重置 API Key。

---

## 七、测试

### Q7.1 `pytest tests/` 报 `ModuleNotFoundError`

```zsh
cd backend-skeleton
source .venv/bin/activate
pytest tests/ -v   # 必须在 backend-skeleton/ 目录跑
```

### Q7.2 测试报 `sqlite3.OperationalError: no such table`

conftest.py 已经在每个测试前 `init_db()`，如果还报：

```zsh
rm /tmp/test*.db   # 清旧 DB
pytest tests/ -v
```

---

## 八、性能 / 时延

### Q8.1 单查询超过 30s

- 检查 `backend.log` 卡在哪一步
- 多半是 LLM 网关慢，看 fallback chain 是否正常切
- 真实模式时 `MAX_TOKENS` 减半

### Q8.2 批量评测慢

mock 模式 10 题 5 秒；真实模式 10 题约 60-90 秒。如果更慢：
- 看 LLM 配额是否 throttle
- 评测脚本里加并发（`asyncio.gather`）

---

## 九、决赛日紧急方案

### 演示中后端突然崩

```zsh
bash stop.sh && bash start.sh
```

或浏览器 URL 加 `?mock=true` 切纯前端 mock，**不依赖后端**继续演示。

### 投影屏配色不清楚

浏览器 → Tweaks 面板（左下角 ⚙）→ 切 **Mono** 主题 + 字号 1.15x。

### 视频录制翻车

按 [`录制前自检.md`](./录制前自检.md) 第 7 章灾备方案。

---

## 十、万不得已：联系人

| 场景 | 找谁 |
|---|---|
| GitAI / 仓库 | **AIC AI PaaS 部 - 刘来运** |
| API Key | **AIC 信息安全管理部 - 李锦** |
| 大赛流程 | **HRC 人事服务部 - 金朝华** |
| 赛题答疑 | **评委组 - 张峰** |
| 资料同步 | **董翔老师** |
| 队内技术 | 张扬 / 巧玲 |

---

## 附：核心日志位置

```
.run/backend.log         # uvicorn 后端日志（含 Request ID 追踪）
.run/frontend.log        # http.server 前端日志
backend-skeleton/eval_results/<task_id>/  # 评测产物
reports/<report_id>/     # 报告 docx 文件
tt.db                    # SQLite 持久化
schemas.json             # 数据集 schema 缓存
business_terms.json      # 业务术语词典
graphrag_index.json      # GraphRAG 社区索引
```
