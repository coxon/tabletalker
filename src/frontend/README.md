# TableTalker 前端

Next.js 15 + React 19 前端，提供分析、历史、批量、报告列表和状态页面。

## 本地启动

从仓库根目录推荐使用：

```bash
make dev
```

或单独启动前端：

```bash
cd src/frontend
pnpm install
pnpm dev
```

默认后端地址为 `http://localhost:8000`，可通过 `BACKEND_URL` 覆盖。

## 主要页面

- `/`：分析主页
- `/history`：历史分析
- `/batch`：批量评测
- `/reports`：报告列表
- `/status`：服务状态

`/v2/*` 旧路径会自动 308 重定向到对应的根路径（兼容已分享出去的 URL）。

## 国内网络

如安装依赖较慢，可在本机 `~/.npmrc` 中配置：

```text
registry=https://registry.npmmirror.com/
```

仓库内 `.npmrc` 保持默认 registry，避免影响 CI 和非国内环境。
