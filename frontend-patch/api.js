// Table-Talker 前端对接补丁
// 把这个文件放到 design-source/ 目录，并在 Table-Talker.html 中加：
//    <script src="api.js"></script>
// 这一行需要放在 data.js 之后、其他 jsx 之前。
//
// 用法：在 chat.jsx 中替换原来的 setInterval mock 为 window.TT_API.chatStream(...)

(function () {
  // 读取 URL 参数 ?mock=true 或 window.TT_API_MOCK 强制使用 mock；否则用真后端
  const params = new URLSearchParams(location.search);
  const FORCE_MOCK = params.get("mock") === "true" || window.TT_API_MOCK === true;
  const BASE = window.TT_API_BASE || "http://localhost:8000";

  /**
   * 流式对话
   * @param {object} opts {question, mode, sessionId, conversationId, datasetHint}
   * @param {object} handlers
   *   onTraceStep(stepEvent)  - 每步 running/done 都触发
   *   onAnswerChunk(text, mode)
   *   onChart(chartEvent)
   *   onInsight(insightEvent)
   *   onCitation(citationEvent)
   *   onFollowups({business[], expert[]})
   *   onComplete(meta)
   *   onError(err)
   * @returns abort function
   */
  async function chatStream(opts, handlers) {
    const { question, mode = "business", sessionId, conversationId, datasetHint, palette } = opts;
    if (FORCE_MOCK) {
      return mockChatStream(opts, handlers);
    }

    const ctrl = new AbortController();
    try {
      const resp = await fetch(`${BASE}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
        body: JSON.stringify({
          question,
          mode,
          session_id: sessionId,
          conversation_id: conversationId,
          dataset_hint: datasetHint,
          palette,
        }),
        signal: ctrl.signal,
      });

      if (!resp.ok) {
        handlers.onError?.(new Error(`HTTP ${resp.status}`));
        return () => ctrl.abort();
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // SSE 分隔符 \n\n
        const events = buf.split("\n\n");
        buf = events.pop() || "";
        for (const block of events) {
          const dataLine = block.split("\n").find(l => l.startsWith("data:"));
          if (!dataLine) continue;
          const json = dataLine.slice(5).trim();
          try {
            const ev = JSON.parse(json);
            dispatch(ev, handlers);
          } catch (e) {
            console.warn("bad SSE chunk", json);
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") handlers.onError?.(e);
    }
    return () => ctrl.abort();
  }

  function dispatch(ev, h) {
    switch (ev.type) {
      case "trace_step": h.onTraceStep?.(ev); break;
      case "answer_chunk": h.onAnswerChunk?.(ev.text, ev.mode); break;
      case "chart": h.onChart?.(ev); break;
      case "insight": h.onInsight?.(ev); break;
      case "citation": h.onCitation?.(ev); break;
      case "followups": h.onFollowups?.({ business: ev.business || [], expert: ev.expert || [] }); break;
      case "complete":
      case "done": h.onComplete?.(ev); break;
      case "error": h.onError?.(new Error(ev.message)); break;
    }
  }

  // ============ Mock 模式（用 design-source 现有的 TT_DATA） ============
  async function mockChatStream(opts, handlers) {
    const D = window.TT_DATA;
    const conv = D.conversations[opts.conversationId] || D.conversations.c1;
    const mode = opts.mode || "business";
    let aborted = false;

    // 14 步
    for (const s of D.traceSteps) {
      if (aborted) return;
      handlers.onTraceStep?.({ type: "trace_step", ...s, status: "running" });
      await sleep(Math.min(280, 80 + s.t / 8));
      if (aborted) return;
      handlers.onTraceStep?.({ type: "trace_step", i: s.i, status: s.status || "done", duration_ms: s.t });
    }

    // 图
    for (const ch of (conv.charts || [])) {
      if (aborted) return;
      handlers.onChart?.({ type: "chart", ...ch });
    }
    // 洞察
    for (const ins of (conv.insights || [])) {
      if (aborted) return;
      handlers.onInsight?.({ type: "insight", ...ins });
    }
    // 引用
    handlers.onCitation?.({ type: "citation", ...D.citation });
    // 追问
    handlers.onFollowups?.({
      business: conv.bizFollowups || [],
      expert: conv.expertFollowups || [],
    });

    // 流式答案
    const text = mode === "business" ? conv.bizText : conv.expertText;
    for (let i = 0; i < text.length; i += 3) {
      if (aborted) return;
      handlers.onAnswerChunk?.(text.slice(i, i + 3), mode);
      await sleep(18);
    }

    handlers.onComplete?.({ type: "complete", message_id: "mock-" + Date.now() });
    return () => { aborted = true; };
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ============ REST 接口 ============
  async function listDatasets() {
    if (FORCE_MOCK) return { datasets: window.TT_DATA.datasets };
    const r = await fetch(`${BASE}/api/datasets/`);
    return r.json();
  }
  async function listConversations() {
    if (FORCE_MOCK) return { conversations: window.TT_DATA.history };
    const r = await fetch(`${BASE}/api/chat/conversations`);
    return r.json();
  }
  async function listDashboards() {
    if (FORCE_MOCK) return { dashboards: window.TT_DATA.dashGroups };
    const r = await fetch(`${BASE}/api/dashboard/`);
    return r.json();
  }

  // 文件上传
  async function uploadFile(file, opts = {}) {
    const fd = new FormData();
    fd.append("file", file);
    if (opts.name) fd.append("name", opts.name);
    if (opts.description) fd.append("description", opts.description);
    const r = await fetch(`${BASE}/api/datasets/upload`, { method: "POST", body: fd });
    return r.json();
  }

  // 批量评测
  async function startEval(file) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`${BASE}/api/eval/run`, { method: "POST", body: fd });
    return r.json(); // {task_id, total}
  }

  function streamEval(taskId, handlers) {
    const ctrl = new AbortController();
    (async () => {
      const resp = await fetch(`${BASE}/api/eval/stream/${taskId}`, {
        signal: ctrl.signal, headers: { "Accept": "text/event-stream" },
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split("\n\n");
        buf = events.pop() || "";
        for (const b of events) {
          const dl = b.split("\n").find(l => l.startsWith("data:"));
          if (!dl) continue;
          try {
            const ev = JSON.parse(dl.slice(5).trim());
            if (ev.type === "progress") handlers.onProgress?.(ev);
            else if (ev.type === "complete") handlers.onComplete?.(ev);
          } catch (e) {/**/ }
        }
      }
    })();
    return () => ctrl.abort();
  }

  function downloadEval(taskId, type = "results") {
    location.href = `${BASE}/api/eval/download/${taskId}/${type}`;
  }

  // 看板"钉住"
  async function pinToDashboard(messageId, dashboardId, title, annotation) {
    const r = await fetch(`${BASE}/api/dashboard/pin`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId, dashboard_id: dashboardId, title, annotation }),
    });
    return r.json();
  }

  // 报告生成
  async function generateReport(opts) {
    const r = await fetch(`${BASE}/api/report/generate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opts),
    });
    return r.json();
  }

  // ============ 暴露到 window ============
  window.TT_API = {
    BASE,
    FORCE_MOCK,
    chatStream,
    listDatasets,
    listConversations,
    listDashboards,
    uploadFile,
    startEval,
    streamEval,
    downloadEval,
    pinToDashboard,
    generateReport,
  };

  console.log(`%c[Table-Talker API] Ready. mode=${FORCE_MOCK ? "MOCK" : "REAL"} base=${BASE}`,
    "color:#15875e;font-weight:bold");
})();
