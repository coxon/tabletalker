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
- 前端：http://localhost:3000
  - `/` — 评委使用页面（分析主页）
  - `/history` — 历史分析页面
  - `/batch` — 批量评测页面
  - `/v2/*` 旧路径会 308 重定向到上述新路径（兼容已分享出去的 URL）

按 `Ctrl+C` 可以同时停止两个服务。

该脚本是组委会可能直接运行的入口，应保持可重复执行、无需交互确认。
