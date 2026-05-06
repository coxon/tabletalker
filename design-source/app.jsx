// Table-Talker — main app shell
const { useState: uSA } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "defaultMode": "business",
  "density": "cozy",
  "traceStyle": "timeline",
  "palette": "emerald",
  "fontScale": 1
}/*EDITMODE-END*/;

const PALETTES = {
  emerald: ["#15875e", "#9bc7b3", "#6e3cf5", "#c2630c"],
  ocean: ["#1d6fa5", "#9ec1d6", "#0fb5a8", "#c2630c"],
  warm: ["#c2410c", "#e9b08a", "#15875e", "#6e3cf5"],
  mono: ["#1a1d1a", "#9a9d96", "#6b6e69", "#c2410c"],
};

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [page, setPage] = uSA("chat");
  // 启动时检查 localStorage 中的 token；有就先认为登录态，再异步校验
  const [logged, setLogged] = uSA(() => !!(window.TT_API && window.TT_API.getAuthToken && window.TT_API.getAuthToken()));
  const [currentUser, setCurrentUser] = uSA(() => (window.TT_API && window.TT_API.getAuthUser && window.TT_API.getAuthUser()) || null);
  const [conv, setConv] = uSA("new");        // 默认进入新建对话页（空白欢迎页）
  const [reportConv, setReportConv] = uSA("c1");
  const [navFlash, setNavFlash] = uSA(null);

  // ===== 动态历史对话 + 用户会话快照（跨组件共享）=====
  // 持久化到 localStorage（key 带 v1，将来字段改了 +v2 不冲突）
  const HIST_KEY = "tt_history_v1", CONVS_KEY = "tt_liveConvs_v1";
  const [history, setHistory] = uSA(() => {
    try { return JSON.parse(localStorage.getItem(HIST_KEY) || "[]"); } catch { return []; }
  });
  const [liveConvs, setLiveConvs] = uSA(() => {
    try { return JSON.parse(localStorage.getItem(CONVS_KEY) || "{}"); } catch { return {}; }
  });

  // 把短标题从问题里提取出来（去掉问号/句号，最多 18 字）
  const titleFromQuestion = (q) => {
    if (!q) return "新对话";
    const t = String(q).trim().replace(/[?？。！!]+$/g, "").replace(/\s+/g, " ");
    return t.length > 18 ? t.slice(0, 18) + "…" : t;
  };

  // 持久化：history / liveConvs（LRU 50 条 · B-017 配额满时通知用户）
  React.useEffect(() => {
    const trimmed = history.slice(0, 50);
    try { localStorage.setItem(HIST_KEY, JSON.stringify(trimmed)); } catch (e) {
      try {
        localStorage.setItem(HIST_KEY, JSON.stringify(trimmed.slice(0, 25)));
        window.ttToast && window.ttToast("⚠ 本地存储接近上限，已自动压缩到最近 25 条会话", { type: "warn", duration: 5000 });
      } catch {
        window.ttToast && window.ttToast("⚠ 本地存储已满，新会话不会被保存。请到设置 → 版本历史 清理。", { type: "error", duration: 6000 });
      }
    }
  }, [history]);
  React.useEffect(() => {
    const validIds = new Set(history.map(h => h.id));
    const trimmed = {};
    for (const [k, v] of Object.entries(liveConvs)) if (validIds.has(k)) trimmed[k] = v;
    try { localStorage.setItem(CONVS_KEY, JSON.stringify(trimmed)); } catch (e) {
      try { localStorage.setItem(CONVS_KEY, "{}"); } catch {}
      window.ttToast && window.ttToast("⚠ 会话快照空间不足，已清空临时缓存（不影响使用）", { type: "warn", duration: 5000 });
    }
  }, [liveConvs, history]);

  // 在用户发新问题时调用：追加历史 + 存会话快照（id 唯一）
  const recordConversation = React.useCallback((convData) => {
    const id = convData.id || `live_${Date.now().toString(36)}`;
    const cleanTitle = titleFromQuestion(convData.title || convData.question || "新对话");

    setHistory(prev => {
      const filtered = prev.filter(h => h.id !== id);
      return [{
        id, title: cleanTitle,
        time: "刚刚", ts: Date.now(),
        mode: convData.mode || "business",
        active: true, _live: true,
      }, ...filtered.map(h => ({ ...h, active: false }))];
    });
    setLiveConvs(prev => ({ ...prev, [id]: convData }));
    setConv(id);
    return id;
  }, []);

  // 在 charts/insights/citation 等更新时持续刷新当前会话快照
  const updateLiveConv = React.useCallback((id, patch) => {
    if (!id || !id.startsWith("live_")) return;
    setLiveConvs(prev => ({
      ...prev,
      [id]: { ...(prev[id] || {}), ...patch },
    }));
  }, []);

  // 删除一条 live 会话
  const deleteLiveConv = React.useCallback((id) => {
    setHistory(prev => prev.filter(h => h.id !== id));
    setLiveConvs(prev => {
      const next = { ...prev }; delete next[id]; return next;
    });
    setConv(c => (c === id ? "new" : c));
  }, []);

  // 重命名 live 会话
  const renameLiveConv = React.useCallback((id, newTitle) => {
    setHistory(prev => prev.map(h => h.id === id ? { ...h, title: newTitle } : h));
    setLiveConvs(prev => prev[id] ? { ...prev, [id]: { ...prev[id], title: newTitle } } : prev);
  }, []);

  // B-008 跨 tab 同步：另一个 tab 改了 history/liveConvs 时，本 tab 自动 reload
  React.useEffect(() => {
    const onStorage = (e) => {
      if (e.key === HIST_KEY && e.newValue) {
        try { setHistory(JSON.parse(e.newValue) || []); } catch {}
      }
      if (e.key === CONVS_KEY && e.newValue) {
        try { setLiveConvs(JSON.parse(e.newValue) || {}); } catch {}
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // ⌘K / Ctrl+K → 全局命令面板
  const [paletteOpen, setPaletteOpen] = uSA(false);
  React.useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // 启动后异步验证 token 是否还有效
  React.useEffect(() => {
    if (!logged || !window.TT_API || !window.TT_API.fetchMe) return;
    window.TT_API.fetchMe().then(user => {
      if (user) setCurrentUser(user);
      else { setLogged(false); setCurrentUser(null); }
    });
    // eslint-disable-next-line
  }, []);

  const onLogin = () => {
    const u = window.TT_API && window.TT_API.getAuthUser && window.TT_API.getAuthUser();
    setCurrentUser(u);
    setLogged(true);
  };

  const onLogout = async () => {
    if (window.TT_API && window.TT_API.logout) await window.TT_API.logout();
    setLogged(false);
    setCurrentUser(null);
  };

  const goto = (p, opts) => {
    setPage(p);
    if (p === "report" && opts && opts.convId) setReportConv(opts.convId);
    setNavFlash(p);
    setTimeout(() => setNavFlash(null), 600);
  };
  const switchConv = (id) => { setConv(id); if (page !== "chat") setPage("chat"); };
  const newChat = () => { setConv("new"); setPage("chat"); };

  React.useEffect(() => {
    document.documentElement.dataset.theme = tweaks.theme === "dark" ? "dark" : "light";
    document.documentElement.dataset.density = tweaks.density === "compact" ? "compact" : "cozy";
    document.documentElement.style.fontSize = (14 * (tweaks.fontScale || 1)) + "px";
  }, [tweaks.theme, tweaks.fontScale, tweaks.density]);

  const palette = PALETTES[tweaks.palette] || PALETTES.emerald;
  const ctx = { ...tweaks, palette, goto };

  if (!logged) return <><LoginPage onEnter={onLogin} /><TweaksUI tweaks={tweaks} setTweak={setTweak} /></>;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar current={conv} onChange={switchConv} onNew={newChat} page={page} setPage={goto}
        density={tweaks.density} currentUser={currentUser} onLogout={onLogout}
        history={history} onDelete={deleteLiveConv} />
      <main style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", position: "relative" }}>
        {page === "chat" && <ChatPage tweaks={ctx} convId={conv} goto={goto} switchConv={switchConv}
          recordConversation={recordConversation} updateLiveConv={updateLiveConv}
          liveConvs={liveConvs} setReportConv={setReportConv} />}
        {page === "data" && <DataPage tweaks={ctx} />}
        {page === "dashboard" && <DashboardPage tweaks={ctx} liveConvs={liveConvs} deleteLiveConv={deleteLiveConv} renameLiveConv={renameLiveConv} />}
        {page === "report" && <ReportPage tweaks={ctx} convId={reportConv} liveConvs={liveConvs} />}
        {page === "eval" && <EvalPage tweaks={ctx} />}
        {page === "settings" && <SettingsPage tweaks={ctx} />}
        {navFlash && <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "var(--acc)", opacity: 0, animation: "tt-nav-flash 0.6s ease-out" }} />}
      </main>
      <TweaksUI tweaks={tweaks} setTweak={setTweak} />
      {paletteOpen && window.CommandPalette && <window.CommandPalette
        onClose={() => setPaletteOpen(false)}
        history={history}
        onJump={(target) => {
          setPaletteOpen(false);
          if (target.kind === "page") goto(target.id);
          else if (target.kind === "conv") { setConv(target.id); setPage("chat"); }
          else if (target.kind === "new") { setConv("new"); setPage("chat"); }
          else if (target.kind === "template") { setConv("new"); setPage("chat"); setTimeout(() => window.dispatchEvent(new CustomEvent("tt-fill-input", { detail: target.prompt })), 100); }
          else if (target.kind === "dataset") { setConv("new"); setPage("chat"); setTimeout(() => window.dispatchEvent(new CustomEvent("tt-fill-input", { detail: `@${target.name} ` })), 100); }
        }} />}
    </div>
  );
}

function TweaksUI({ tweaks, setTweak }) {
  return (
    <TweaksPanel title="Tweaks">
      <TweakSection title="主题">
        <TweakRadio label="模式" value={tweaks.theme} onChange={v => setTweak("theme", v)} options={[{value: "light", label: "Light"}, {value: "dark", label: "Dark"}]} />
        <TweakSelect label="图表色板" value={tweaks.palette} onChange={v => setTweak("palette", v)} options={[
          {value: "emerald", label: "Emerald (默认)"},
          {value: "ocean", label: "Ocean"},
          {value: "warm", label: "Warm"},
          {value: "mono", label: "Mono"},
        ]} />
        <TweakSlider label="字号" value={tweaks.fontScale} onChange={v => setTweak("fontScale", v)} min={0.9} max={1.15} step={0.05} />
      </TweakSection>
      <TweakSection title="对话">
        <TweakRadio label="默认模式" value={tweaks.defaultMode} onChange={v => setTweak("defaultMode", v)} options={[{value: "business", label: "商业"}, {value: "expert", label: "专家"}]} />
        <TweakRadio label="密度" value={tweaks.density} onChange={v => setTweak("density", v)} options={[{value: "compact", label: "紧凑"}, {value: "cozy", label: "宽松"}]} />
      </TweakSection>
      <TweakSection title="Trace 视觉">
        <TweakRadio label="风格" value={tweaks.traceStyle} onChange={v => setTweak("traceStyle", v)} options={[
          {value: "timeline", label: "时间线"},
          {value: "stream", label: "流"},
          {value: "dna", label: "DNA"},
        ]} />
      </TweakSection>
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
