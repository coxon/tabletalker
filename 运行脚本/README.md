# 运行脚本

`start.sh` 是面向组委会和本地自测的一键启动脚本。干净克隆仓库后运行：

```bash
bash 运行脚本/start.sh
```

宿主机需要准备：

- Python 3.11+，并安装 [`uv`](https://docs.astral.sh/uv/)
- Node 20+，并安装 `pnpm`
- 可访问的 `LLM_BASE_URL` 与 `LLM_API_KEY`，配置方式见 `.env.example`

脚本会同时启动后端和前端，并在前台等待。运行期间可以访问：

- 后端：http://localhost:8000
  - `/health` — 健康检查
  - `/v1/analyze` 和 `/v1/follow-up` — 提交契约接口
    （见 `docs/submission-contract.md`）
  - `/v1/batch` 和 `/v1/sessions` — 批量评测和历史接口
  - `/v1/self-test/*` — 自测报告接口（HTML / Markdown / JSONL / Excel）
- 前端：http://localhost:3000
  - `/` — 评委使用页面（分析主页）
  - `/history` — 历史分析页面
  - `/batch` — 批量评测页面
  - `/self-test` — 自测报告（独立页，无侧栏；评委可直接访问）
  - `/v2/*` 旧路径会 308 重定向到上述新路径（兼容已分享出去的 URL）

按 `Ctrl+C` 可以同时停止两个服务。

该脚本是组委会可能直接运行的入口，应保持可重复执行、无需交互确认。

## 其他本地部署方式

`start.sh` 之外还有两套等价的本地部署方式：

- **docker-compose**：`docker compose up --build` — 后端 + 前端 + sessions 持久化卷
- **kubectl / oc**：`kubectl apply -f k8s/ -n <namespace>` — manifest 不绑定命名空间，
  本地与生产可复用同一份。`k8s/backend.yaml` 含 PVC（1Gi）持久化
  `sessions.db`；LLM 凭据走 Secret，启动前需替换 `sk-replace-me` 占位符。

三种方式互不影响，挑一种即可。
