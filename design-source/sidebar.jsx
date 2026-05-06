// Table-Talker — Main app
const { useState, useEffect, useRef, useMemo } = React;
const { useTweaks } = window;

// ---------- Sidebar (history) ----------
function Sidebar({ current, onChange, onNew, page, setPage, density, currentUser, onLogout, history, onDelete }) {
  const D = window.TT_DATA;
  const padY = density === "compact" ? 4 : 7;
  // 历史合并：用户实时（live）+ 预置示例 → 一段，按时间倒序，示例追加到末尾
  const liveHistory = (history || []).filter(h => h._live);
  const exampleHistory = (D.history || []).map(h => ({ ...h, _example: true }));
  const merged = [...liveHistory, ...exampleHistory];
  return (
    <aside style={{
      width: 248, flexShrink: 0,
      background: "var(--surface-2)",
      borderRight: "1px solid var(--line)",
      display: "flex", flexDirection: "column",
      height: "100%",
    }}>
      <div style={{ padding: "16px 16px 12px", display: "flex", alignItems: "center", gap: 10 }}>
        <Logo size={28} />
        <div className="tt-side-text" style={{ display: "flex", flexDirection: "column", lineHeight: 1.05 }}>
          <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.015em", fontFamily: "var(--font-serif)" }}>
            Table<span style={{ color: "var(--brand)" }}>·</span>Talker
          </span>
          <span style={{ fontSize: 10, color: "var(--ink-4)", fontFamily: "var(--font-mono)" }}>v1.0 · 亚信</span>
        </div>
      </div>

      <button onClick={() => onNew && onNew()} style={{
        margin: "0 12px 8px", padding: "9px 12px",
        background: "var(--ink)", color: "var(--bg)",
        borderRadius: 8, fontSize: 13, fontWeight: 500,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <span style={{ fontSize: 14 }}>＋</span>
        <span>新建对话</span>
        <span style={{ marginLeft: "auto", opacity: 0.6, fontSize: 10 }} className="mono">⌘K</span>
      </button>

      <NavGroup label="工作区">
        <NavItem icon="📊" active={page === "dashboard"} onClick={() => setPage("dashboard")} data-tt-nav="dashboard">看板</NavItem>
        <NavItem icon="📄" active={page === "report"} onClick={() => setPage("report")}>报告</NavItem>
        <NavItem icon="🗂" active={page === "data"} onClick={() => setPage("data")}>数据接入</NavItem>
        <NavItem icon="🧪" active={page === "eval"} onClick={() => setPage("eval")}>批量评测<span className="tt-tag" style={{ marginLeft: "auto" }}>评委</span></NavItem>
        <NavItem icon="⚙" active={page === "settings"} onClick={() => setPage("settings")}>设置</NavItem>
      </NavGroup>

      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 12px" }}>
        {/* === 历史会话（live + 示例 合并在一起） === */}
        <div style={{ padding: "8px 8px 4px", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-4)", letterSpacing: "0.06em", textTransform: "uppercase", display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 4, height: 4, borderRadius: 2, background: liveHistory.length > 0 ? "var(--acc)" : "var(--ink-4)" }} />
          历史会话
          {liveHistory.length > 0 && <span style={{ background: "var(--acc-soft)", color: "var(--acc)", padding: "1px 6px", borderRadius: 3, fontSize: 9 }}>{liveHistory.length}</span>}
        </div>
        {merged.length === 0 ? (
          <div style={{ padding: "12px 10px", fontSize: 11, color: "var(--ink-4)", textAlign: "center", lineHeight: 1.6, background: "var(--bg-2)", borderRadius: 6, margin: "4px 0 12px" }}>
            <div style={{ fontSize: 18, marginBottom: 4, opacity: 0.6 }}>💬</div>
            还没有会话 · 点上方"新建对话"开始
          </div>
        ) : (
          <div>
            {merged.map(h => {
              const isExample = h._example;
              const dotColor = h.mode === "expert" ? "var(--elec)" : (isExample ? "var(--ink-4)" : "var(--acc)");
              const isActive = current === h.id;
              return (
                <div key={h.id} className="tt-side-item" style={{
                  position: "relative",
                  background: isActive ? (isExample ? "var(--bg-2)" : "var(--acc-soft)") : "transparent",
                  borderRadius: 6, marginBottom: 2,
                }}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = "var(--bg-2)"; if (!isExample) { const x = e.currentTarget.querySelector(".tt-del-btn"); if (x) x.style.opacity = 1; } }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = "transparent"; const x = e.currentTarget.querySelector(".tt-del-btn"); if (x) x.style.opacity = 0; }}>
                  <button onClick={() => onChange(h.id)} style={{
                    display: "flex", flexDirection: "column", gap: 2,
                    width: "100%", textAlign: "left",
                    padding: `${padY}px ${(!isExample && onDelete) ? 28 : 10}px ${padY}px 10px`, borderRadius: 6,
                    background: "transparent",
                    color: isExample ? "var(--ink-2)" : "var(--ink)",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ width: 4, height: 4, borderRadius: 2, background: dotColor }} />
                      <span style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, fontWeight: isActive ? 600 : 400, opacity: isExample ? 0.85 : 1 }}>{h.title}</span>
                      {isExample && <span style={{ fontSize: 9, color: "var(--ink-4)", fontFamily: "var(--font-mono)", padding: "0 4px", border: "1px solid var(--line)", borderRadius: 3 }}>示例</span>}
                    </div>
                    <span style={{ fontSize: 10.5, color: "var(--ink-4)", paddingLeft: 10, fontFamily: "var(--font-mono)" }}>
                      {h.ts && window.timeAgo ? window.timeAgo(h.ts) : (h.time || "刚刚")}
                    </span>
                  </button>
                  {!isExample && onDelete && (
                    <button
                      className="tt-del-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (window.confirm(`删除这条会话？\n\n"${h.title}"\n\n此操作不可撤销。`)) onDelete(h.id);
                      }}
                      title="删除"
                      aria-label={`删除会话 ${h.title}`}
                      style={{
                        position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)",
                        opacity: 0, transition: "opacity 0.15s",
                        width: 22, height: 22, borderRadius: 4,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "var(--ink-4)", cursor: "pointer",
                        background: "transparent", border: "none", fontSize: 14,
                      }}
                      onMouseEnter={e => { e.currentTarget.style.background = "var(--surface)"; e.currentTarget.style.color = "var(--danger)"; }}
                      onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--ink-4)"; }}
                    >×</button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ borderTop: "1px solid var(--line)", padding: 12, display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 28, height: 28, borderRadius: "50%", background: "var(--acc-soft)", color: "var(--acc)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 600 }}>
          {(currentUser?.name || "巧").charAt(0)}
        </div>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15, flex: 1, overflow: "hidden" }}>
          <span style={{ fontSize: 12, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {currentUser?.name || currentUser?.sub || "巧玲"}
          </span>
          <span style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
            AIC · {currentUser?.role || "power_user"}
          </span>
        </div>
        <button
          style={{ color: "var(--ink-3)", padding: 4, cursor: "pointer", borderRadius: 6 }}
          title="主题 / 字号 / 密度 设置"
          onClick={() => window.postMessage({ type: "__activate_edit_mode" }, "*")}
          onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-2)"; e.currentTarget.style.color = "var(--ink)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--ink-3)"; }}
        >⚙</button>
        <button
          style={{ color: "var(--ink-3)", padding: 4, cursor: "pointer", borderRadius: 6, fontSize: 13 }}
          title="退出登录"
          onClick={() => {
            if (confirm("确认退出登录？")) {
              onLogout && onLogout();
            }
          }}
          onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-2)"; e.currentTarget.style.color = "var(--danger)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--ink-3)"; }}
        >⏻</button>
      </div>
    </aside>
  );
}

function NavGroup({ label, children }) {
  return (
    <div style={{ padding: "0 8px 8px" }}>
      <div style={{ padding: "6px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-4)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>{children}</div>
    </div>
  );
}

function NavItem({ icon, active, onClick, children, ...rest }) {
  return (
    <button onClick={onClick} {...rest} style={{
      display: "flex", alignItems: "center", gap: 9,
      padding: "7px 10px", borderRadius: 6,
      background: active ? "var(--bg-2)" : "transparent",
      color: active ? "var(--ink)" : "var(--ink-2)",
      fontSize: 13, fontWeight: active ? 500 : 400, textAlign: "left",
    }}
    onMouseEnter={e => { if (!active) e.currentTarget.style.background = "var(--bg-2)"; }}
    onMouseLeave={e => { if (!active) e.currentTarget.style.background = "transparent"; }}>
      <span style={{ fontSize: 13, opacity: 0.85 }}>{icon}</span>
      <span className="tt-side-text" style={{ flex: 1, display: "flex", alignItems: "center" }}>{children}</span>
    </button>
  );
}

function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-label="Table-Talker">
      {/* 主底 · 黑 */}
      <rect x="2" y="2" width="28" height="28" rx="7" fill="var(--ink)" />
      {/* 品牌签名色一笔（左上对话气泡 · 暖橙） */}
      <path d="M 5 7 Q 5 5 7 5 L 13 5 Q 15 5 15 7 L 15 10 Q 15 12 13 12 L 9 12 L 7 14 L 7 12 Q 5 12 5 10 Z" fill="var(--brand)" opacity="0.9" />
      {/* 表格 3 行 · 翠绿数据条 */}
      <rect x="11" y="14" width="14" height="2" rx="1" fill="var(--acc-2)" />
      <rect x="11" y="18" width="10" height="1.5" rx="0.75" fill="var(--bg)" opacity="0.6" />
      <rect x="11" y="21.5" width="7" height="1.5" rx="0.75" fill="var(--bg)" opacity="0.45" />
      {/* 右下"洞察"圆点 */}
      <circle cx="24" cy="24" r="3" fill="var(--acc-2)" />
      <circle cx="24" cy="24" r="1.2" fill="var(--ink)" />
    </svg>
  );
}

// Wordmark 版（Logo + 文字组合）
function LogoWordmark({ height = 24, showVer = true }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <Logo size={height + 4} />
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.05 }}>
        <span style={{ fontSize: height * 0.6, fontWeight: 600, letterSpacing: "-0.01em", fontFamily: "var(--font-serif)", color: "var(--ink)" }}>
          Table<span style={{ color: "var(--brand)" }}>·</span>Talker
        </span>
        {showVer && <span style={{ fontSize: height * 0.4, color: "var(--ink-4)", fontFamily: "var(--font-mono)", marginTop: 1 }}>v1.0 · 亚信</span>}
      </div>
    </div>
  );
}
window.LogoWordmark = LogoWordmark;

window.Sidebar = Sidebar;
window.Logo = Logo;
