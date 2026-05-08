# 前端对接补丁（frontend-patch）

> 把 design-source（设计稿）变成能调真实后端的前端，零改动主代码。

## 一、安装步骤（5 分钟）

### 1. 把 api.js 拷到设计稿目录

```bash
cp frontend-patch/api.js design-source/api.js
```

### 2. 在 Table-Talker.html 加一行 script 引用

打开 `design-source/Table-Talker.html`，找到这块：

```html
<script src="data.js"></script>
<script type="text/babel" src="tweaks-panel.jsx"></script>
```

在 `data.js` 之后插入：

```html
<script src="data.js"></script>
<script src="api.js"></script>          <!-- 👈 新增这行 -->
<script type="text/babel" src="tweaks-panel.jsx"></script>
```

### 3. 改 chat.jsx 的 mock 路径为 TT_API

打开 `design-source/chat.jsx`，找到 `playDemo` 函数（约第 54 行），替换为：

```jsx
const playDemo = (overrideQuestion) => {
  setPlaying(true);
  setCurrentStep(-1);
  setTypewriter({ active: false, text: "" });

  const question = overrideQuestion || conv.question;
  const traceState = D.traceSteps.map(s => ({ ...s, _status: "pending" }));
  let typedText = "";

  window.TT_API.chatStream(
    { question, mode, conversationId: convId, palette: tweaks.palette },
    {
      onTraceStep: (ev) => {
        // 推一步
        setCurrentStep(ev.i - 1);
      },
      onAnswerChunk: (text, _mode) => {
        typedText += text;
        setTypewriter({ active: true, text: typedText });
      },
      onChart: (ev) => {
        // 设计稿用 conv.charts 渲染图，可以累加到 messages 状态里
      },
      onInsight: (ev) => { /* 累加到 insights */ },
      onCitation: (ev) => { /* 设计稿底部"引用"用 */ },
      onFollowups: ({ business, expert }) => {
        // 替换 conv.bizFollowups / conv.expertFollowups
      },
      onComplete: () => {
        setPlaying(false);
        setTypewriter({ active: false, text: typedText });
      },
      onError: (e) => {
        console.error(e);
        showToast("后端调用失败：" + e.message);
      },
    }
  );
};
```

### 4. 决定是 Mock 还是 Real

**保持 Mock 模式（推荐先这样）**：在 HTML 里加：
```html
<script>window.TT_API_MOCK = true;</script>
```

**切换到 Real 后端**：
```html
<script>
  window.TT_API_BASE = "http://localhost:8000";  // 本地
  // window.TT_API_BASE = "http://10.19.79.X:8000";  // 亚信云内网
</script>
```

或在 URL 加 `?mock=true` 一键切回 mock。

## 二、TT_API 完整接口

```javascript
window.TT_API = {
  BASE: "http://localhost:8000",
  FORCE_MOCK: false,

  // 对话流式（替换 chat.jsx 的 mock setInterval）
  chatStream({ question, mode, sessionId, conversationId, datasetHint }, handlers),

  // REST
  listDatasets(),         // → {datasets: [...]}
  listConversations(),    // → {conversations: [...]}
  listDashboards(),       // → {dashboards: [...]}

  // 数据接入
  uploadFile(file, {name, description}),

  // 批量评测（评委用）
  startEval(file),                       // → {task_id, total}
  streamEval(taskId, {onProgress, onComplete}),
  downloadEval(taskId, "results" | "metrics"),

  // 看板
  pinToDashboard(messageId, dashboardId, title, annotation),

  // 报告
  generateReport({conversation_id, template, format}),
};
```

## 三、后端不在时怎么办（强 mock 模式）

`api.js` 启动时会读取 `window.TT_API_MOCK` 或 `?mock=true`，如果为真，**所有接口走 design-source/data.js 的本地 mock**——chat.jsx 几乎无需改动。

也就是说：
- **后端没起**：URL 加 `?mock=true`，演示如常
- **后端起了**：去掉 `?mock=true`，自动切真后端

## 四、调试技巧

### 看实时事件流

打开浏览器 DevTools → Network → XHR → 点 `/api/chat/stream` → 看 EventStream tab。

### 后端日志

```bash
cd backend-skeleton
tail -f logs/*.log  # 或直接看 uvicorn 控制台
```

### 跨域问题

后端 `.env` 里加：
```
CORS_ORIGINS=http://localhost:8080,http://10.19.79.X
```

## 五、Day 1 联调清单

- [ ] 后端 8000 端口起来，`curl /api/health` 返回 ok
- [ ] 前端 `python -m http.server 8080` 起来
- [ ] 浏览器打开 `http://localhost:8080/Table-Talker.html`
- [ ] 控制台输出 `[Table-Talker API] Ready. mode=MOCK` ← 第一步
- [ ] 设 `window.TT_API_MOCK = false`，重新打开 → `mode=REAL`
- [ ] 新对话发送一句话 → 后端日志看到请求 → 14 步 trace 流式回来
- [ ] 切换 business / expert 模式 → 答案文本不同
