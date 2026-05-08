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

  // ===== JWT Token 管理 =====
  const TOKEN_KEY = "tt_auth_token";
  const USER_KEY = "tt_auth_user";
  function getAuthToken() {
    try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }
  function setAuthToken(token, user) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY);
      if (user) localStorage.setItem(USER_KEY, JSON.stringify(user)); else localStorage.removeItem(USER_KEY);
    } catch (e) { /**/ }
  }
  function getAuthUser() {
    try {
      const s = localStorage.getItem(USER_KEY);
      return s ? JSON.parse(s) : null;
    } catch (e) { return null; }
  }
  function clearAuth() { setAuthToken(null, null); }

  // 给所有 fetch 自动加 Authorization header
  function authHeaders(extra) {
    const h = { ...(extra || {}) };
    const t = getAuthToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }

  // ===== 打字机音效（Web Audio API 生成的轻微 click，无需外部文件）=====
  // 关闭：localStorage.setItem('tt_sound', 'off')
  let _audioCtx = null;
  let _typeCounter = 0;
  function playTypeClick(volume) {
    if (typeof window === "undefined") return;
    if (window.localStorage && window.localStorage.getItem("tt_sound") === "off") return;
    try {
      _audioCtx = _audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const ctx = _audioCtx;
      // Safari 在用户首次交互后才允许 resume
      if (ctx.state === "suspended") ctx.resume();
      const t = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      // 随机轻微 click 频率 700-1200Hz，模拟机械键盘
      osc.frequency.setValueAtTime(700 + Math.random() * 500, t);
      osc.type = "square";
      gain.gain.setValueAtTime(volume || 0.025, t);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.025);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.03);
    } catch (e) { /* 安静失败 */ }
  }
  // 节流版：每 N 字符播一次（避免太密）
  function playTypeClickThrottled() {
    _typeCounter = (_typeCounter + 1) % 4;
    if (_typeCounter === 0) playTypeClick();
  }

  // ===== 全局 Toast（替代 alert，更优雅） =====
  function showToast(msg, opts) {
    opts = opts || {};
    const dur = opts.duration || 2200;
    const type = opts.type || "info"; // info / success / warn / error
    const colors = {
      info:    { bg: "rgba(31,33,30,0.92)", fg: "#fff", icon: "ℹ" },
      success: { bg: "rgba(21,135,94,0.95)", fg: "#fff", icon: "✓" },
      warn:    { bg: "rgba(194,99,12,0.92)", fg: "#fff", icon: "⚠" },
      error:   { bg: "rgba(184,52,26,0.92)", fg: "#fff", icon: "✕" },
    };
    const c = colors[type] || colors.info;
    const el = document.createElement("div");
    el.style.cssText = `
      position:fixed;top:20px;left:50%;transform:translateX(-50%) translateY(-10px);
      background:${c.bg};color:${c.fg};padding:10px 18px;border-radius:8px;
      font:13px/1.5 -apple-system,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,0.18);
      backdrop-filter:blur(20px);z-index:99999;opacity:0;transition:all .25s ease-out;
      max-width:420px;display:flex;align-items:center;gap:8px;`;
    el.innerHTML = `<span style="font-size:14px">${c.icon}</span><span>${msg}</span>`;
    document.body.appendChild(el);
    requestAnimationFrame(() => { el.style.opacity = "1"; el.style.transform = "translateX(-50%) translateY(0)"; });
    setTimeout(() => {
      el.style.opacity = "0"; el.style.transform = "translateX(-50%) translateY(-10px)";
      setTimeout(() => el.remove(), 300);
    }, dur);
  }
  window.ttToast = showToast;
  window.playTypeClick = playTypeClick;
  window.playTypeClickThrottled = playTypeClickThrottled;

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
        headers: authHeaders({ "Content-Type": "application/json", "Accept": "text/event-stream" }),
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
        // SSE 事件分隔符兼容 \r\n\r\n / \n\n（sse-starlette 默认 \r\n\r\n）
        const events = buf.split(/\r?\n\r?\n/);
        buf = events.pop() || "";
        for (const block of events) {
          const dataLine = block.split(/\r?\n/).find(l => l.startsWith("data:"));
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
    const url = `${BASE}/api/eval/stream/${taskId}`;
    console.log("[TT_API] streamEval fetch:", url);
    (async () => {
      try {
        const resp = await fetch(url, {
          signal: ctrl.signal, headers: { "Accept": "text/event-stream" },
        });
        console.log("[TT_API] streamEval response:", resp.status, resp.statusText);
        if (!resp.ok) { handlers.onError?.(new Error("HTTP " + resp.status)); return; }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let chunks = 0;
        while (true) {
          const { value, done } = await reader.read();
          if (done) { console.log("[TT_API] streamEval ended, chunks=", chunks); break; }
          chunks++;
          buf += decoder.decode(value, { stream: true });
          const events = buf.split(/\r?\n\r?\n/);
          buf = events.pop() || "";
          for (const b of events) {
            const dl = b.split(/\r?\n/).find(l => l.startsWith("data:"));
            if (!dl) continue;
            try {
              const ev = JSON.parse(dl.slice(5).trim());
              console.log("[TT_API] streamEval event:", ev.type, "done=" + ev.done);
              if (ev.type === "progress") handlers.onProgress?.(ev);
              else if (ev.type === "complete") handlers.onComplete?.(ev);
            } catch (e) { console.warn("[TT_API] bad chunk:", b.slice(0,80)); }
          }
        }
      } catch (e) {
        console.error("[TT_API] streamEval error:", e);
        handlers.onError?.(e);
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
      method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(opts),
    });
    return r.json();
  }

  // ============ 鉴权接口 ============

  /** 账密登录 → 拿 JWT 存 localStorage */
  async function login(email, password) {
    const r = await fetch(`${BASE}/api/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await r.json();
    if (r.ok && data.token) {
      setAuthToken(data.token, data.user);
      return { ok: true, user: data.user };
    }
    return { ok: false, error: data.message || data.detail || "登录失败" };
  }

  /** 评委 magic-link token 登录 */
  async function judgeLogin(token) {
    const r = await fetch(`${BASE}/api/auth/judge-login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = await r.json();
    if (r.ok && data.token) {
      setAuthToken(data.token, data.user);
      return { ok: true, user: data.user, redirect: data.redirect };
    }
    return { ok: false, error: data.message || data.detail || "评委 token 无效" };
  }

  /** 验证当前 token 是否还有效（启动时调） */
  async function fetchMe() {
    if (!getAuthToken()) return null;
    try {
      const r = await fetch(`${BASE}/api/auth/me`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        return data.user;
      }
    } catch (e) { /* 网络失败时返回缓存 user */ }
    if (!navigator.onLine) return getAuthUser();
    // token 失效，清掉
    clearAuth();
    return null;
  }

  /** 登出（前端清 token，后端无状态） */
  async function logout() {
    try { await fetch(`${BASE}/api/auth/logout`, { method: "POST", headers: authHeaders() }); } catch (e) {/**/}
    clearAuth();
  }

  /** 多模型 A/B 对比 — 失败/mock 模式自动给 5 模型示意结果 */
  async function multiModelCompare(question, models) {
    const mockData = () => ({
      question,
      winner: "通义 3.6 Plus",
      winner_reason: "结论清晰、SQL 正确、引用完整",
      consistency_score: 0.86,
      results: [
        { model: "通义 3.6 Plus", latency_ms: 2840, tokens: 612, characteristics: "稳定 · 长文本 · 业务语言友好", answer: question + "\n\n核心结论：主指标同比下滑，主因 BU-3 客户经理流失（−18%）。建议优先稳定团队 + 倾斜直销激励。", agreement_score: 0.92 },
        { model: "DeepSeek-V3.2", latency_ms: 1920, tokens: 458, characteristics: "性价比高 · 推理强", answer: question + "\n\n下钻 BU 维度：BU-3 贡献度从 32%→22%，与流失率 r=0.81 强相关。突变点 2026-01。", agreement_score: 0.89 },
        { model: "Kimi K2.5",     latency_ms: 3210, tokens: 720, characteristics: "长上下文 · 引用密", answer: question + "\n\n基于 sales_orders × fin_pnl 两表 JOIN，结果在 IQR 范围内，无空值，结论可信度高。", agreement_score: 0.84 },
        { model: "MiniMax-M2.5",  latency_ms: 2100, tokens: 530, characteristics: "中文增强", answer: question + "\n\nBU-3 客户经理流失传导到签单链路，是主拖累。其他 BU 表现稳定。", agreement_score: 0.82 },
        { model: "GLM 5",         latency_ms: 2680, tokens: 590, characteristics: "代码强 · 国产", answer: question + "\n\n建议下钻 SQL：region_l1='south_china' AND bu_id='BU-3' GROUP BY month。", agreement_score: 0.78 },
      ],
    });
    if (FORCE_MOCK) {
      await new Promise(res => setTimeout(res, 600));
      return mockData();
    }
    try {
      const r = await fetch(`${BASE}/api/multi-model/compare`, {
        method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ question, models, mode: "business" }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      if (!j || !j.results) throw new Error("invalid response");
      return j;
    } catch (e) {
      console.warn("[multiModelCompare] fallback to mock:", e);
      return mockData();
    }
  }

  /** 指标库 API */
  async function searchMetrics(query) {
    const r = await fetch(`${BASE}/api/metrics/search?q=${encodeURIComponent(query)}`, { headers: authHeaders() });
    return r.json();
  }
  async function listMetrics(category) {
    const url = category ? `${BASE}/api/metrics/?category=${category}` : `${BASE}/api/metrics/`;
    const r = await fetch(url, { headers: authHeaders() });
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
    // 鉴权
    login,
    judgeLogin,
    fetchMe,
    logout,
    getAuthToken,
    getAuthUser,
    // 多模型 A/B
    multiModelCompare,
    // 指标库
    searchMetrics,
    listMetrics,
  };

  console.log(`%c[Table-Talker API] Ready. mode=${FORCE_MOCK ? "MOCK" : "REAL"} base=${BASE}`,
    "color:#15875e;font-weight:bold");
})();
