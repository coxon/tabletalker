# 决赛日部署 SOP

> 5/22 决赛日 / 5/24 路演前 5 分钟，照着这页**抄命令**就能起服务。
> 决赛队长 / 巧玲 双备份。

---

## 0. 前置（5/22 早上前已完成）

- [ ] 已 `git pull` 到最新版（巧玲 push 的最新 commit）
- [ ] 已在内网 / VPN 环境
- [ ] Docker / Python 3.12 / git 已安装
- [ ] 主办方 5 个模型 API Key（找队长 张扬 / 董翔老师）

---

## 1. 5 分钟从 0 到上线

### Step 1：拉代码

```zsh
cd ~/workspace
git clone http://10.19.79.176:8190/hackathon/hackathon-tabletalker-repository.git table-talker
cd table-talker
```

### Step 2：配 .env

```zsh
cp .env.example .env
nano .env   # 或 vi / code
```

**必改 4 行**（其他保持默认）：

```
LLM_API_KEY=sk-QDknIZEz6dIXhyXrPhBQQw         # 主办方 Key
LLM_BASE_URL=https://aigw.asiainfo.com/v1
LLM_MODEL_DEFAULT=aliyun/qwen3.6-plus
MOCK_MODE=false                                # 决赛用真模型
```

### Step 3：装依赖（任选一）

#### 3A. Docker（推荐，最稳）

```zsh
docker compose up -d --build
```

启动后：
- 前端：http://localhost:8080/Table-Talker.html
- 后端：http://localhost:8000/docs

#### 3B. 本地（无 Docker 时）

```zsh
cd backend-skeleton
bash install.sh   # 自动建 venv + 装依赖（含 PyPI 镜像 fallback）
source .venv/bin/activate

cd ..
bash start.sh     # 一键起前后端
```

### Step 4：5 分钟自检

```zsh
bash smoke-test.sh
```

期望：**🎉 全部 OK，可以演示 / 提交**

如果有 ❌ 项，立刻查 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) 对应章节。

---

## 2. 决赛演示前 1 小时

### 预热

```zsh
bash warmup.sh   # 把 7 个对话场景预跑一遍，浏览器 React 编译完成
```

### 浏览器最终确认

打开 `http://<部署IP>:8080/Table-Talker.html`：
- [ ] 14 步 Trace 流式动画跑完
- [ ] 答案 typewriter 逐字打出
- [ ] 圆环图 / 柱状图 / 折线图都渲染
- [ ] 切到批量评测页，上传 sample_eval.jsonl 进度条能动
- [ ] 切到看板页，"已同步 N · HH:MM:SS" 标签出现

按 `录制前自检.md` 9 大类 47 项更全面。

---

## 3. 演示中翻车应急

### 后端崩

```zsh
bash stop.sh && bash start.sh
```

### 网关 LLM 突然不通

```zsh
sed -i '' 's/MOCK_MODE=false/MOCK_MODE=true/' .env
bash stop.sh && bash start.sh
```

→ **3 秒切回 mock 模式继续演示**，评委看不出来。

### 浏览器卡住

URL 加 `?mock=true`，**不依赖后端**继续演示。

### 投影屏看不清

左下角 ⚙ → Tweaks 面板：
- 切 **Mono** 主题（黑白对比强）
- 字号拉到 **1.15x**

---

## 4. 决赛后清理

```zsh
bash stop.sh

# 清理评测产物（释放磁盘）
rm -rf backend-skeleton/eval_results/*
rm -rf reports/*

# 清理 Docker
docker compose down
docker system prune -f
```

---

## 5. 三句话救命

> **跑不起来** → `bash smoke-test.sh` 看哪步挂 → 查 TROUBLESHOOTING.md
>
> **演示崩了** → URL 加 `?mock=true` 切前端 mock，照演不误
>
> **网络挂** → `MOCK_MODE=true` 切后端 mock，3 秒恢复

---

## 6. 紧急联系（按职责）

| 紧急事项 | 联系人 | 部门 |
|---|---|---|
| API Key / 网关 | **李锦** | AIC 信息安全 |
| GitAI / 仓库 | **刘来运** | AIC AI PaaS |
| 大赛流程 | **金朝华** | HRC 人事服务 |
| 视频 / 提交 | 巧玲 / 张扬 | 队内 |

---

> 打印这一页放在演示电脑旁边，决赛日**只看这页**。
