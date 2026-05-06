// 错误边界 + 空状态组件
// 防止某个组件崩了整页白屏；列表为空时给友好提示。

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    console.error("[ErrorBoundary] 捕获到错误：", error, errorInfo);
    if (window.ttToast) {
      window.ttToast(`组件渲染异常已隔离：${error.message}`, { type: "error", duration: 4000 });
    }
  }

  reset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div style={{
        padding: 32, margin: 24, background: "var(--surface)",
        border: "1px solid var(--line)", borderRadius: 12,
        textAlign: "center", color: "var(--ink-2)",
      }}>
        <div style={{ fontSize: 36, marginBottom: 12 }}>🪲</div>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          这块组件出了点小问题
        </div>
        <div style={{ fontSize: 13, color: "var(--ink-3)", marginBottom: 16, fontFamily: "var(--font-mono)" }}>
          {this.state.error?.message || "未知错误"}
        </div>
        <div style={{ fontSize: 12, color: "var(--ink-4)", marginBottom: 20 }}>
          系统其他部分仍可正常使用。点下面按钮重试，或刷新页面。
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
          <button onClick={this.reset} className="tt-btn tt-btn--sm tt-btn--primary">↻ 重试</button>
          <button onClick={() => window.location.reload()} className="tt-btn tt-btn--sm">刷新页面</button>
        </div>
      </div>
    );
  }
}

window.ErrorBoundary = ErrorBoundary;

// ===== 空状态组件（带品牌插画）=====
function EmptyState({ icon = "📭", title = "暂无数据", desc = "", action = null, illustration }) {
  return (
    <div style={{
      padding: "48px 32px", textAlign: "center", color: "var(--ink-3)",
    }}>
      {illustration ? (
        <div style={{ marginBottom: 20 }}>{illustration}</div>
      ) : (
        <BrandEmptySvg label={icon} />
      )}
      <div style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)", marginBottom: 6, fontFamily: "var(--font-serif)", letterSpacing: "-0.01em" }}>{title}</div>
      {desc && <div style={{ fontSize: 12.5, color: "var(--ink-3)", marginBottom: 20, maxWidth: 420, margin: "0 auto 20px", lineHeight: 1.6 }}>{desc}</div>}
      {action}
    </div>
  );
}
function BrandEmptySvg({ label }) {
  // 一张 80×80 的品牌空状态 svg：表格虚线 + 一颗签名色圆点
  return (
    <svg width="96" height="96" viewBox="0 0 96 96" style={{ marginBottom: 12 }}>
      <defs>
        <linearGradient id="empty-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--bg-2)" />
          <stop offset="100%" stopColor="var(--surface)" />
        </linearGradient>
      </defs>
      <rect x="14" y="20" width="68" height="56" rx="6" fill="url(#empty-fade)" stroke="var(--line)" strokeWidth="1" strokeDasharray="3 3" />
      <line x1="14" y1="32" x2="82" y2="32" stroke="var(--line)" strokeWidth="1" strokeDasharray="2 2" />
      <line x1="36" y1="20" x2="36" y2="76" stroke="var(--line)" strokeWidth="1" strokeDasharray="2 2" />
      <line x1="60" y1="20" x2="60" y2="76" stroke="var(--line)" strokeWidth="1" strokeDasharray="2 2" />
      <circle cx="78" cy="14" r="6" fill="var(--brand)" opacity="0.85" />
      <circle cx="78" cy="14" r="2.5" fill="var(--bg)" />
      <text x="48" y="58" fontSize="22" textAnchor="middle" opacity="0.6">{label}</text>
    </svg>
  );
}
window.EmptyState = EmptyState;

// ===== 加载中状态（升级 skeleton + 品牌 pulse）=====
function LoadingState({ text = "加载中…", lines = 3 }) {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ fontSize: 12, color: "var(--ink-3)", marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          width: 8, height: 8, borderRadius: 4,
          background: "var(--acc)",
          boxShadow: "0 0 0 0 var(--acc)",
          animation: "tt-pulse 1.4s infinite",
        }} />
        {text}
      </div>
      {[...Array(lines)].map((_, i) => (
        <div key={i} style={{
          height: 14, marginBottom: 10, borderRadius: 4,
          width: `${88 - i * 14}%`,
          background: "linear-gradient(90deg, var(--bg-2) 0%, var(--bg-3) 50%, var(--bg-2) 100%)",
          backgroundSize: "200% 100%",
          animation: `tt-shimmer 1.4s ease-in-out infinite`,
          animationDelay: `${i * 0.12}s`,
        }} />
      ))}
    </div>
  );
}
window.LoadingState = LoadingState;

// ===== 通用 Modal hook：Esc 关闭 + 锁滚动 + 焦点收敛 + ARIA =====
// 用法：const ref = useModal({ open: shareOpen, onClose });
// 然后挂到 modal 容器最外层 div：<div ref={ref} role="dialog" aria-modal="true">
function useModal({ open, onClose }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    // 锁 body 滚动
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Esc 关闭
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); onClose && onClose(); } };
    document.addEventListener("keydown", onKey, true);
    // 自动聚焦第一个 input/textarea/button（除了关闭按钮）
    setTimeout(() => {
      const root = ref.current;
      if (!root) return;
      const target = root.querySelector("input:not([type=hidden]), textarea, select, button:not([aria-label='关闭']):not([title='关闭'])");
      if (target && typeof target.focus === "function") target.focus();
    }, 30);
    return () => {
      document.body.style.overflow = prev;
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open, onClose]);
  return ref;
}
window.useModal = useModal;

// ===== timeago 统一格式化（跟 UI 任何"X 分钟前"都用它）=====
function timeAgo(ts) {
  if (!ts) return "—";
  const now = Date.now();
  const t = typeof ts === "number" ? ts : new Date(ts).getTime();
  const sec = Math.max(0, Math.floor((now - t) / 1000));
  if (sec < 30) return "刚刚";
  if (sec < 60) return sec + " 秒前";
  const min = Math.floor(sec / 60);
  if (min < 60) return min + " 分钟前";
  const hr = Math.floor(min / 60);
  if (hr < 24) return hr + " 小时前";
  const day = Math.floor(hr / 24);
  if (day === 1) return "昨天";
  if (day === 2) return "前天";
  if (day < 7) return day + " 天前";
  if (day < 30) return Math.floor(day / 7) + " 周前";
  if (day < 365) return Math.floor(day / 30) + " 个月前";
  return Math.floor(day / 365) + " 年前";
}
window.timeAgo = timeAgo;

// ===== 业务术语词典：让中英文混排自动统一（写一处、改一处、显一致）=====
// 默认按照 zh 显示；调用 ttTerm("yoy") → "同比"；ttTerm("yoy", "en") → "YoY"
const TT_TERMS = {
  yoy:        { zh: "同比",       en: "YoY",   tooltip: "Year-over-Year" },
  qoq:        { zh: "环比",       en: "QoQ",   tooltip: "Quarter-over-Quarter / Period-over-Period" },
  wow:        { zh: "周环比",     en: "WoW",   tooltip: "Week-over-Week" },
  mom:        { zh: "月环比",     en: "MoM",   tooltip: "Month-over-Month" },
  ytd:        { zh: "年累计",     en: "YTD",   tooltip: "Year-to-Date" },
  mtd:        { zh: "月累计",     en: "MTD",   tooltip: "Month-to-Date" },
  arr:        { zh: "年化经常收入", en: "ARR",  tooltip: "Annual Recurring Revenue" },
  mrr:        { zh: "月经常收入", en: "MRR",   tooltip: "Monthly Recurring Revenue" },
  arpu:       { zh: "ARPU",       en: "ARPU",  tooltip: "用户平均收入 · Average Revenue Per User" },
  gmv:        { zh: "成交额",     en: "GMV",   tooltip: "Gross Merchandise Volume" },
  nps:        { zh: "NPS",        en: "NPS",   tooltip: "Net Promoter Score · 净推荐值" },
  dau:        { zh: "日活",       en: "DAU",   tooltip: "Daily Active Users" },
  mau:        { zh: "月活",       en: "MAU",   tooltip: "Monthly Active Users" },
  sla:        { zh: "服务级别协议", en: "SLA", tooltip: "Service Level Agreement" },
  bu:         { zh: "事业部",     en: "BU",    tooltip: "Business Unit" },
  pii:        { zh: "敏感信息",   en: "PII",   tooltip: "Personally Identifiable Information" },
  iqr:        { zh: "四分位距",   en: "IQR",   tooltip: "Inter-Quartile Range · 异常检测算法" },
  zscore:     { zh: "Z 分数",     en: "Z-Score", tooltip: "标准化分数 · 异常检测算法" },
  stl:        { zh: "STL 分解",   en: "STL",   tooltip: "Seasonal-Trend-Loess · 时间序列分解" },
  cusum:      { zh: "CUSUM",      en: "CUSUM", tooltip: "Cumulative Sum · 突变点检测" },
  sql:        { zh: "SQL",        en: "SQL",   tooltip: "Structured Query Language" },
  ttl:        { zh: "TTL 推理",   en: "TTL",   tooltip: "Term Translation Layer · 业务术语→字段映射" },
  rag:        { zh: "GraphRAG",   en: "GraphRAG", tooltip: "Graph-augmented Retrieval-Augmented Generation" },
};
function ttTerm(key, lang) {
  const t = TT_TERMS[(key || "").toLowerCase()];
  if (!t) return key;
  if (lang === "en") return t.en;
  if (lang === "tooltip") return t.tooltip;
  return t.zh;
}
window.TT_TERMS = TT_TERMS;
window.ttTerm = ttTerm;

// 包装术语为带 tooltip 的 React 元素：<TermTip k="yoy" />
function TermTip({ k, lang }) {
  const t = TT_TERMS[(k || "").toLowerCase()];
  if (!t) return React.createElement("span", null, k);
  const display = lang === "en" ? t.en : t.zh;
  return React.createElement("span", {
    title: t.tooltip,
    style: { borderBottom: "1px dotted var(--ink-4)", cursor: "help" },
  }, display);
}
window.TermTip = TermTip;

// ===== 虚拟滚动列表（>50 条时才启用，否则原生渲染避免抖动）=====
// 用法：<VirtualList items={arr} itemHeight={60} maxHeight={400} renderItem={(it,i)=>...} />
function VirtualList({ items, itemHeight = 60, maxHeight = 400, renderItem }) {
  const [scrollTop, setScrollTop] = React.useState(0);
  const containerRef = React.useRef(null);
  const total = items.length;
  // 少于 50 条不启用虚拟化
  if (total <= 50) {
    return React.createElement("div", { style: { maxHeight, overflowY: "auto" } },
      items.map((it, i) => React.createElement("div", { key: i, style: { minHeight: itemHeight } }, renderItem(it, i)))
    );
  }
  const viewportH = maxHeight;
  const startIdx = Math.max(0, Math.floor(scrollTop / itemHeight) - 3);
  const endIdx   = Math.min(total, Math.ceil((scrollTop + viewportH) / itemHeight) + 3);
  const visible = items.slice(startIdx, endIdx);
  return React.createElement("div", {
    ref: containerRef,
    onScroll: (e) => setScrollTop(e.currentTarget.scrollTop),
    style: { maxHeight: viewportH, overflowY: "auto", position: "relative" },
  },
    React.createElement("div", { style: { height: total * itemHeight, position: "relative" } },
      React.createElement("div", { style: { position: "absolute", top: startIdx * itemHeight, left: 0, right: 0 } },
        visible.map((it, i) => React.createElement("div", { key: startIdx + i, style: { height: itemHeight } }, renderItem(it, startIdx + i)))
      )
    )
  );
}
window.VirtualList = VirtualList;

// ===== 报告/看板 版本快照（P2-23）=====
// 简单实现：当用户钉到看板或导出报告时，往 localStorage 推一份快照；可在 Settings 里看历史
const VERSIONS_KEY = "tt_versions_v1";
function ttSnapshot(kind, payload) {
  try {
    const all = JSON.parse(localStorage.getItem(VERSIONS_KEY) || "[]");
    all.unshift({
      id: `v_${Date.now().toString(36)}`,
      ts: Date.now(),
      kind,        // "report" | "dashboard" | "answer"
      title: payload.title || "未命名",
      summary: payload.summary || "",
      data: payload,
    });
    // 最多保留 50 个
    localStorage.setItem(VERSIONS_KEY, JSON.stringify(all.slice(0, 50)));
  } catch {}
}
function ttListVersions(kind) {
  try {
    const all = JSON.parse(localStorage.getItem(VERSIONS_KEY) || "[]");
    return kind ? all.filter(v => v.kind === kind) : all;
  } catch { return []; }
}
window.ttSnapshot = ttSnapshot;
window.ttListVersions = ttListVersions;

// "飞向看板"彩蛋 — 从触发按钮飞到 sidebar 的"看板"导航项
function ttFlyToDashboard(fromEl, emoji = "📌") {
  if (!fromEl) return;
  const target = document.querySelector('[data-tt-nav="dashboard"]')
                || document.querySelector('aside button[onclick*="dashboard"]');
  const r1 = fromEl.getBoundingClientRect();
  const r2 = target ? target.getBoundingClientRect() : { top: 100, left: 32, width: 24, height: 24 };
  const fly = document.createElement("div");
  fly.className = "tt-fly-pin";
  fly.textContent = emoji;
  fly.style.left = (r1.left + r1.width / 2 - 11) + "px";
  fly.style.top  = (r1.top  + r1.height / 2 - 11) + "px";
  document.body.appendChild(fly);
  // 触发位移
  requestAnimationFrame(() => {
    fly.style.left = (r2.left + r2.width / 2 - 11) + "px";
    fly.style.top  = (r2.top  + r2.height / 2 - 11) + "px";
    fly.style.transform = "scale(0.5) rotate(360deg)";
    fly.style.opacity = "0.2";
  });
  setTimeout(() => fly.remove(), 750);
  // 目标抖一下
  if (target) {
    target.style.transition = "transform 0.3s";
    setTimeout(() => target.style.transform = "scale(1.1)", 700);
    setTimeout(() => target.style.transform = "", 1000);
  }
}
window.ttFlyToDashboard = ttFlyToDashboard;
