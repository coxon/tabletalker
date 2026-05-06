// Table-Talker variations canvas — side-by-side artboards
// Self-contained: doesn't depend on the main app's components.

const PAL = {
  acc: "#15875e", acc2: "#1aa074", accSoft: "#e2f1eb",
  ink: "#1a1d1a", ink2: "#3a3d3a", ink3: "#6b6e69", ink4: "#9a9d96",
  line: "#e5e5dd", bg: "#fafaf8", bg2: "#f3f3ee",
  warn: "#c2630c", warnSoft: "#fbecd6",
  info: "#2563a8", infoSoft: "#e3edf7",
  elec: "#6e3cf5", elecSoft: "#ece4fe",
};

const F = "Inter, system-ui, sans-serif";
const FM = "JetBrains Mono, monospace";

// ────── Reusable atoms ──────
const Frame = ({ children, bg = "#fff", style }) => (
  <div style={{ width: "100%", height: "100%", background: bg, fontFamily: F, color: PAL.ink, display: "flex", flexDirection: "column", overflow: "hidden", ...style }}>{children}</div>
);
const Bar = ({ children, height = 38 }) => (
  <div style={{ height, borderBottom: `1px solid ${PAL.line}`, background: "#fff", display: "flex", alignItems: "center", padding: "0 12px", gap: 8, flexShrink: 0 }}>{children}</div>
);
const Tag = ({ c, bg, children, sz = 9 }) => (
  <span style={{ background: bg, color: c, padding: "2px 7px", fontSize: sz, fontFamily: FM, fontWeight: 500, borderRadius: 3, textTransform: "uppercase", letterSpacing: "0.04em" }}>{children}</span>
);
const Logo = ({ sz = 14 }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: sz, fontWeight: 600, letterSpacing: "-0.01em" }}>
    <svg width={sz - 1} height={sz - 1} viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke={PAL.acc} strokeWidth="2"/><circle cx="12" cy="12" r="5.5" fill="none" stroke={PAL.acc} strokeWidth="1.4" opacity="0.6"/><circle cx="12" cy="12" r="2" fill={PAL.acc}/></svg>
    Table-Talker
  </span>
);

// =================================================================
// SECTION 1 — CHAT REPLY LAYOUT VARIATIONS
// =================================================================

// V1A — Inline narrative (compact, conversation-feel)
function ChatV_Inline() {
  return (
    <Frame bg={PAL.bg2}>
      <Bar><Logo /><Tag c={PAL.acc} bg={PAL.accSoft}>Inline</Tag></Bar>
      <div style={{ flex: 1, padding: 18, overflow: "auto" }}>
        <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
          <div style={{ width: 24, height: 24, borderRadius: 12, background: PAL.ink, color: "#fff", fontSize: 10, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>李</div>
          <div style={{ background: "#fff", padding: "9px 13px", borderRadius: 12, fontSize: 13 }}>Q1 各大区成交额对比，并解释华南区波动</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ width: 24, height: 24, borderRadius: 12, background: PAL.acc, color: "#fff", fontSize: 11, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>T</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, lineHeight: 1.7, color: PAL.ink2, marginBottom: 12 }}>
              Q1 全国六大区成交额合计 <b className="tabular" style={{ color: PAL.ink }}>6,727 万元</b>，同比 +1.6%。<b style={{ color: PAL.warn }}>华南区</b> 1,116 万 <span className="tabular" style={{ color: PAL.warn }}>(−12.0%)</span>，是当季最大拖累项。
            </div>
            <div style={{ background: "#fff", padding: 12, borderRadius: 8, border: `1px solid ${PAL.line}` }}>
              <MiniBars />
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
              {["为什么华南下降？", "对比 2024Q1", "渠道维度下钻"].map(c => (
                <span key={c} style={{ fontSize: 11, padding: "4px 10px", border: `1px solid ${PAL.line}`, borderRadius: 999, color: PAL.ink2, background: "#fff" }}>{c}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Frame>
  );
}

// V1B — Card-stacked (clear sections)
function ChatV_Cards() {
  return (
    <Frame bg={PAL.bg2}>
      <Bar><Logo /><Tag c={PAL.elec} bg={PAL.elecSoft}>Cards</Tag></Bar>
      <div style={{ flex: 1, padding: 14, overflow: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ background: "#fff", borderRadius: 8, border: `1px solid ${PAL.line}`, overflow: "hidden" }}>
          <div style={{ padding: "8px 12px", borderBottom: `1px solid ${PAL.line}`, fontSize: 10, fontFamily: FM, color: PAL.ink4, textTransform: "uppercase", letterSpacing: "0.05em" }}>结论</div>
          <div style={{ padding: 12, fontSize: 13, lineHeight: 1.6, color: PAL.ink2 }}>
            Q1 合计 <b style={{ color: PAL.ink }}>6,727 万</b>，同比 <b style={{ color: PAL.acc }}>+1.6%</b>。华南是唯一两位数下滑大区。
          </div>
        </div>
        <div style={{ background: "#fff", borderRadius: 8, border: `1px solid ${PAL.line}`, overflow: "hidden" }}>
          <div style={{ padding: "8px 12px", borderBottom: `1px solid ${PAL.line}`, fontSize: 10, fontFamily: FM, color: PAL.ink4, textTransform: "uppercase", letterSpacing: "0.05em" }}>图表 · Q1 各大区</div>
          <div style={{ padding: 12 }}><MiniBars /></div>
        </div>
        <div style={{ background: "#fff", borderRadius: 8, border: `1px solid ${PAL.line}`, overflow: "hidden" }}>
          <div style={{ padding: "8px 12px", borderBottom: `1px solid ${PAL.line}`, fontSize: 10, fontFamily: FM, color: PAL.ink4, textTransform: "uppercase", letterSpacing: "0.05em" }}>关键数字</div>
          <div style={{ padding: 12, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            {[["合计", "6,727", PAL.ink], ["同比", "+1.6%", PAL.acc], ["华南", "−12%", PAL.warn]].map(([l, v, c]) => (
              <div key={l}><div style={{ fontSize: 9, color: PAL.ink4, fontFamily: FM, textTransform: "uppercase" }}>{l}</div><div className="tabular" style={{ fontSize: 18, fontWeight: 600, color: c }}>{v}</div></div>
            ))}
          </div>
        </div>
      </div>
    </Frame>
  );
}

// V1C — Split-canvas (left text, right viz)
function ChatV_Split() {
  return (
    <Frame bg="#fff">
      <Bar><Logo /><Tag c={PAL.warn} bg={PAL.warnSoft}>Split</Tag></Bar>
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", overflow: "hidden" }}>
        <div style={{ padding: 16, overflow: "auto", borderRight: `1px solid ${PAL.line}` }}>
          <div style={{ fontSize: 10, fontFamily: FM, color: PAL.ink4, marginBottom: 6, textTransform: "uppercase" }}>Question</div>
          <div style={{ fontSize: 13, color: PAL.ink, marginBottom: 16, fontWeight: 500 }}>Q1 各大区成交额对比</div>
          <div style={{ fontSize: 10, fontFamily: FM, color: PAL.ink4, marginBottom: 6, textTransform: "uppercase" }}>Answer</div>
          <div className="serif" style={{ fontSize: 14, lineHeight: 1.7, color: PAL.ink2 }}>
            合计 <b style={{ color: PAL.ink }}>6,727 万</b>，同比 +1.6%。华南区 <b style={{ color: PAL.warn }}>−12%</b>，单点拖累 152 万。华北 <b style={{ color: PAL.acc }}>+8.1%</b> 领跑。
          </div>
          <div style={{ marginTop: 14, padding: 10, background: PAL.bg2, borderRadius: 6, fontSize: 11.5, color: PAL.ink3 }}>
            ⚡ 自动检测：华南环比下滑 1.8 pp，建议下钻
          </div>
        </div>
        <div style={{ padding: 16, background: PAL.bg2, overflow: "auto" }}>
          <MiniBars />
          <div style={{ marginTop: 12, fontSize: 10, color: PAL.ink4, textAlign: "center", fontFamily: FM }}>图 · Q1 各大区成交额（万元）</div>
        </div>
      </div>
    </Frame>
  );
}

// =================================================================
// SECTION 2 — TRACE VISUALIZATION VARIATIONS
// =================================================================

function TraceV_Timeline() {
  const steps = [
    ["分类", "意图", PAL.acc],
    ["语义", "schema", PAL.acc],
    ["合成", "SQL", PAL.elec],
    ["执行", "1.4s", PAL.info],
    ["校验", "PASS", PAL.acc],
    ["归因", "Δ维", PAL.warn],
    ["结论", "成稿", PAL.ink],
  ];
  return (
    <Frame bg="#fff">
      <Bar><Logo /><Tag c={PAL.acc} bg={PAL.accSoft}>Timeline</Tag></Bar>
      <div style={{ flex: 1, padding: 22, overflow: "auto" }}>
        <div style={{ fontSize: 11, fontFamily: FM, color: PAL.ink4, marginBottom: 14, textTransform: "uppercase" }}>14-step trace · 8.4s</div>
        <div style={{ position: "relative" }}>
          <div style={{ position: "absolute", left: 6, top: 6, bottom: 6, width: 2, background: PAL.line }} />
          {steps.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 12, marginBottom: 12, position: "relative" }}>
              <div style={{ width: 14, height: 14, borderRadius: 7, background: s[2], boxShadow: `0 0 0 3px #fff, 0 0 0 4px ${s[2]}33`, flexShrink: 0, marginTop: 2 }} />
              <div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{s[0]}</div>
                <div style={{ fontSize: 10.5, color: PAL.ink4, fontFamily: FM }}>{s[1]}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Frame>
  );
}

function TraceV_Stream() {
  return (
    <Frame bg="#0e0f0d">
      <Bar><span style={{ color: "#ecede8", fontSize: 12, fontWeight: 600 }}>Table-Talker</span><Tag c="#36d597" bg="#1a3128">Stream</Tag></Bar>
      <div style={{ flex: 1, padding: 18, overflow: "auto", fontFamily: FM, fontSize: 11, color: "#c3c5be" }}>
        {[
          ["00.12", "01", "✓", "意图分类 → comparison_query"],
          ["00.31", "02", "✓", "语义解析 → 6 entities"],
          ["00.62", "03", "✓", "schema match → sales_orders"],
          ["00.94", "04", "▸", "SQL 合成 (3 candidates)"],
          ["01.41", "05", "▸", "执行 → 6 rows / 1.4s"],
          ["02.18", "06", "▸", "异常检测 → 1 outlier"],
          ["02.74", "07", "▸", "归因分析 → 渠道贡献"],
          ["03.05", "08", "✓", "结论合成 → ready"],
        ].map(([t, n, st, msg], i) => (
          <div key={i} style={{ display: "flex", gap: 10, padding: "3px 0", opacity: 0.5 + 0.07 * i }}>
            <span style={{ color: "#5a5d56" }}>{t}s</span>
            <span style={{ color: "#5a5d56" }}>{n}</span>
            <span style={{ color: st === "✓" ? "#36d597" : "#6e3cf5" }}>{st}</span>
            <span>{msg}</span>
          </div>
        ))}
      </div>
    </Frame>
  );
}

function TraceV_DNA() {
  return (
    <Frame bg="#fff">
      <Bar><Logo /><Tag c={PAL.elec} bg={PAL.elecSoft}>DNA</Tag></Bar>
      <div style={{ flex: 1, padding: 22, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg viewBox="0 0 220 320" width="100%" height="100%" style={{ maxHeight: 360 }}>
          {Array.from({ length: 14 }).map((_, i) => {
            const y = 12 + i * 22;
            const x1 = 110 + Math.sin(i * 0.6) * 50;
            const x2 = 110 - Math.sin(i * 0.6) * 50;
            const c = i < 4 ? PAL.acc : i < 9 ? PAL.elec : PAL.warn;
            return (
              <g key={i}>
                <line x1={x1} y1={y} x2={x2} y2={y} stroke={PAL.line} strokeWidth="1" />
                <circle cx={x1} cy={y} r="5" fill={c} />
                <circle cx={x2} cy={y} r="5" fill={c} opacity="0.5" />
                <text x={x1 + 10} y={y + 3} fontFamily={FM} fontSize="8" fill={PAL.ink3}>{String(i + 1).padStart(2, "0")}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </Frame>
  );
}

// =================================================================
// SECTION 3 — DASHBOARD CARD STYLES
// =================================================================

function DashV_Minimal() {
  return (
    <Frame bg={PAL.bg2}>
      <Bar><Logo /><Tag c={PAL.ink3} bg={PAL.bg2}>Minimal</Tag></Bar>
      <div style={{ flex: 1, padding: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, overflow: "auto" }}>
        {[1, 2, 3, 4].map(i => (
          <div key={i} style={{ background: "#fff", padding: 12, border: `1px solid ${PAL.line}`, borderRadius: 4 }}>
            <div style={{ fontSize: 9, fontFamily: FM, color: PAL.ink4, textTransform: "uppercase" }}>指标 0{i}</div>
            <div className="tabular" style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>{[6727, 1116, 8.1, 24][i-1]}<span style={{ fontSize: 11, color: PAL.ink4, marginLeft: 3 }}>{["万", "万", "%", "条"][i-1]}</span></div>
            <div style={{ height: 22, marginTop: 8, background: `linear-gradient(to top, ${PAL.accSoft}, transparent)` }} />
          </div>
        ))}
      </div>
    </Frame>
  );
}

function DashV_Editorial() {
  return (
    <Frame bg="#1a1d1a" style={{ color: "#fff" }}>
      <Bar><span style={{ color: "#fff", fontSize: 12, fontWeight: 600 }}>Table-Talker</span><Tag c="#36d597" bg="#1a3128">Editorial</Tag></Bar>
      <div style={{ flex: 1, padding: 18, overflow: "auto" }}>
        <div className="serif" style={{ fontSize: 11, color: "#8a8c84", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>Q1 / 2026</div>
        <div className="serif" style={{ fontSize: 26, lineHeight: 1.15, marginBottom: 16, fontWeight: 500 }}>华南区 单点拖累 152 万</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <div style={{ fontSize: 9, color: "#8a8c84", fontFamily: FM, textTransform: "uppercase" }}>当季</div>
            <div className="tabular" style={{ fontSize: 28, fontWeight: 500 }}>6,727</div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: "#8a8c84", fontFamily: FM, textTransform: "uppercase" }}>同比</div>
            <div className="tabular" style={{ fontSize: 28, color: "#36d597", fontWeight: 500 }}>+1.6%</div>
          </div>
        </div>
        <div style={{ marginTop: 16, padding: 12, background: "#161814", borderRadius: 4, fontSize: 11.5, color: "#c3c5be", lineHeight: 1.6 }} className="serif">
          华北以 +8.1% 领跑；华东、华北合计贡献 51.4%，结构集中度环比上升 1.8pp。
        </div>
      </div>
    </Frame>
  );
}

function DashV_Mosaic() {
  return (
    <Frame bg={PAL.bg2}>
      <Bar><Logo /><Tag c={PAL.warn} bg={PAL.warnSoft}>Mosaic</Tag></Bar>
      <div style={{ flex: 1, padding: 10, display: "grid", gridTemplateColumns: "2fr 1fr", gridTemplateRows: "1fr 1fr 1fr", gap: 8, overflow: "hidden" }}>
        <div style={{ gridRow: "1 / 3", background: "#fff", borderRadius: 6, padding: 12 }}>
          <div style={{ fontSize: 9, fontFamily: FM, color: PAL.ink4, textTransform: "uppercase" }}>各大区成交</div>
          <MiniBars />
        </div>
        <div style={{ background: PAL.acc, color: "#fff", borderRadius: 6, padding: 10 }}>
          <div style={{ fontSize: 9, fontFamily: FM, opacity: 0.7, textTransform: "uppercase" }}>合计</div>
          <div className="tabular" style={{ fontSize: 20, fontWeight: 600, marginTop: 2 }}>6,727</div>
        </div>
        <div style={{ background: "#fff", borderRadius: 6, padding: 10 }}>
          <div style={{ fontSize: 9, fontFamily: FM, color: PAL.ink4, textTransform: "uppercase" }}>同比</div>
          <div className="tabular" style={{ fontSize: 20, fontWeight: 600, color: PAL.acc, marginTop: 2 }}>+1.6%</div>
        </div>
        <div style={{ gridColumn: "1 / 3", background: PAL.warnSoft, borderRadius: 6, padding: 10 }}>
          <div style={{ fontSize: 10, color: PAL.warn, fontWeight: 600 }}>⚠ 华南区 −12% · 单点拖累 152 万</div>
        </div>
      </div>
    </Frame>
  );
}

// =================================================================
// SECTION 4 — REPORT COVER VARIATIONS
// =================================================================

function ReportV_Editorial() {
  return (
    <Frame bg="#fff">
      <div style={{ padding: 22, height: "100%", display: "flex", flexDirection: "column" }} className="serif">
        <div style={{ fontSize: 10, fontFamily: FM, color: PAL.ink4, textTransform: "uppercase", letterSpacing: "0.1em" }}>2026 Q1 · 报告 · 03/08</div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ fontSize: 11, color: PAL.acc, fontFamily: FM, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>区域成交额对比</div>
          <h1 style={{ fontSize: 30, fontWeight: 500, lineHeight: 1.15, margin: 0, letterSpacing: "-0.015em" }}>华南区是<br/>当季最大拖累项</h1>
          <div style={{ marginTop: 22, fontSize: 13.5, color: PAL.ink2, lineHeight: 1.7, maxWidth: 320 }}>
            合计 6,727 万元 · 同比 +1.6% · 华南 −12.0% · 华北 +8.1%
          </div>
        </div>
        <div style={{ borderTop: `1px solid ${PAL.line}`, paddingTop: 10, fontSize: 10, fontFamily: FM, color: PAL.ink4, display: "flex", justifyContent: "space-between" }}>
          <span>Table-Talker · 自动生成</span><span>2026-04-03</span>
        </div>
      </div>
    </Frame>
  );
}

function ReportV_Brief() {
  return (
    <Frame bg={PAL.bg2}>
      <div style={{ padding: 18, height: "100%", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
          <Logo sz={13} /><div style={{ marginLeft: "auto", fontSize: 9, fontFamily: FM, color: PAL.ink4 }}>v3 · 2026-04-03</div>
        </div>
        <div style={{ background: "#fff", padding: 16, borderRadius: 6, marginBottom: 10 }}>
          <div style={{ fontSize: 10, fontFamily: FM, color: PAL.acc, textTransform: "uppercase", marginBottom: 6 }}>TL;DR</div>
          <div style={{ fontSize: 14, lineHeight: 1.6, color: PAL.ink2 }}>
            Q1 全国 <b style={{ color: PAL.ink }}>6,727 万</b>，同比 <b style={{ color: PAL.acc }}>+1.6%</b>。
            华南区 <b style={{ color: PAL.warn }}>−12%</b>，是唯一两位数下滑大区。
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
          {[["六大区", "6,727 万"], ["最强", "华北 +8.1%"], ["最弱", "华南 −12%"]].map(([l, v]) => (
            <div key={l} style={{ background: "#fff", padding: 10, borderRadius: 4 }}>
              <div style={{ fontSize: 9, color: PAL.ink4, fontFamily: FM, textTransform: "uppercase" }}>{l}</div>
              <div className="tabular" style={{ fontSize: 12, fontWeight: 600, marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>
        <div style={{ flex: 1, marginTop: 10, background: "#fff", borderRadius: 6, padding: 10 }}>
          <MiniBars />
        </div>
      </div>
    </Frame>
  );
}

function ReportV_Magazine() {
  return (
    <Frame bg="#fff">
      <div style={{ height: "100%", display: "grid", gridTemplateColumns: "1fr 1fr" }}>
        <div style={{ background: PAL.ink, color: "#fff", padding: 18, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <Logo sz={12} />
          <div>
            <div className="serif" style={{ fontSize: 11, color: "#8a8c84", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>章节 03</div>
            <div className="serif" style={{ fontSize: 22, lineHeight: 1.2, fontWeight: 500 }}>区域成交额对比</div>
          </div>
          <div style={{ fontSize: 9, fontFamily: FM, opacity: 0.6 }}>2026 · Q1 · 销售归因</div>
        </div>
        <div style={{ padding: 16, display: "flex", flexDirection: "column" }} className="serif">
          <div style={{ fontSize: 10, fontFamily: FM, color: PAL.acc, textTransform: "uppercase", marginBottom: 6 }}>关键数字</div>
          <div className="tabular" style={{ fontSize: 38, fontWeight: 500, lineHeight: 1, color: PAL.ink }}>6,727<span style={{ fontSize: 12, color: PAL.ink3, marginLeft: 4 }}>万</span></div>
          <div style={{ marginTop: 12, fontSize: 12, color: PAL.ink2, lineHeight: 1.6 }}>
            合计成交额 · 同比 <span style={{ color: PAL.acc }}>+1.6%</span>
          </div>
          <div style={{ marginTop: "auto", fontSize: 11, color: PAL.warn, padding: 10, background: PAL.warnSoft, borderRadius: 4 }}>
            ⚠ 华南区 −12% · 拖累 152 万
          </div>
        </div>
      </div>
    </Frame>
  );
}

// =================================================================
// SECTION 5 — LOGIN / WELCOME VARIATIONS
// =================================================================

function LoginV_Trace() {
  return (
    <Frame bg={PAL.bg2}>
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <svg viewBox="0 0 200 200" width="80%">
            {[14, 11, 8, 5, 2.5].map((r, i) => <circle key={i} cx="100" cy="100" r={r * 6} fill="none" stroke={PAL.acc} strokeWidth="0.8" opacity={0.2 + i * 0.15} />)}
            {Array.from({ length: 14 }).map((_, i) => {
              const a = (i / 14) * Math.PI * 2;
              return <circle key={i} cx={100 + Math.cos(a) * 78} cy={100 + Math.sin(a) * 78} r="3" fill={PAL.acc} />;
            })}
            <circle cx="100" cy="100" r="6" fill={PAL.acc} />
          </svg>
        </div>
        <div style={{ padding: 22, display: "flex", flexDirection: "column", justifyContent: "center", background: "#fff" }}>
          <Logo sz={16} />
          <div className="serif" style={{ fontSize: 22, fontWeight: 500, marginTop: 16, lineHeight: 1.2 }}>Ask. See. Decide.</div>
          <div style={{ fontSize: 11, color: PAL.ink3, marginTop: 6 }}>对话即洞察</div>
          <input placeholder="组织邮箱" style={{ marginTop: 18, padding: "10px 12px", border: `1px solid ${PAL.line}`, borderRadius: 6, fontSize: 12 }} />
          <button style={{ marginTop: 8, padding: "10px 12px", background: PAL.ink, color: "#fff", border: "none", borderRadius: 6, fontSize: 12, fontWeight: 500 }}>使用 SSO 继续 →</button>
        </div>
      </div>
    </Frame>
  );
}

function LoginV_Hero() {
  return (
    <Frame bg={PAL.ink} style={{ color: "#fff" }}>
      <div style={{ flex: 1, padding: 24, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <Logo sz={14} />
        <div>
          <div style={{ fontSize: 10, color: "#8a8c84", fontFamily: FM, textTransform: "uppercase", marginBottom: 6 }}>Table-Talker · 2026</div>
          <div className="serif" style={{ fontSize: 38, fontWeight: 500, lineHeight: 1.1, letterSpacing: "-0.02em" }}>把数据库<br/>变成同事</div>
          <div style={{ fontSize: 13, color: "#c3c5be", marginTop: 14, maxWidth: 320 }}>14 步 Trace · 双模式 · 看板 / 报告一键产出</div>
        </div>
        <button style={{ alignSelf: "flex-start", padding: "10px 18px", background: PAL.acc, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600 }}>开始问 →</button>
      </div>
    </Frame>
  );
}

function LoginV_Form() {
  return (
    <Frame bg="#fff">
      <div style={{ flex: 1, padding: 28, display: "flex", flexDirection: "column", justifyContent: "center", maxWidth: 280, margin: "0 auto" }}>
        <Logo sz={14} />
        <div style={{ fontSize: 18, fontWeight: 600, marginTop: 18, letterSpacing: "-0.01em" }}>欢迎回来</div>
        <div style={{ fontSize: 11.5, color: PAL.ink3, marginTop: 4 }}>使用组织账户登录</div>
        <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 8 }}>
          <input placeholder="邮箱地址" style={{ padding: "9px 11px", border: `1px solid ${PAL.line}`, borderRadius: 6, fontSize: 12 }} />
          <input placeholder="密码" type="password" style={{ padding: "9px 11px", border: `1px solid ${PAL.line}`, borderRadius: 6, fontSize: 12 }} />
          <button style={{ padding: "9px 11px", background: PAL.ink, color: "#fff", border: "none", borderRadius: 6, fontSize: 12, fontWeight: 600 }}>登录</button>
          <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "6px 0" }}>
            <div style={{ flex: 1, height: 1, background: PAL.line }} /><span style={{ fontSize: 10, color: PAL.ink4 }}>OR</span><div style={{ flex: 1, height: 1, background: PAL.line }} />
          </div>
          <button style={{ padding: "9px 11px", border: `1px solid ${PAL.line}`, borderRadius: 6, fontSize: 12, background: "#fff" }}>SSO · 飞书</button>
          <button style={{ padding: "9px 11px", border: `1px solid ${PAL.line}`, borderRadius: 6, fontSize: 12, background: "#fff" }}>SSO · 钉钉</button>
        </div>
      </div>
    </Frame>
  );
}

// ────── Mini bars helper ──────
function MiniBars() {
  const data = [["华东", 1735, PAL.acc], ["华南", 1116, PAL.warn], ["华北", 1722, PAL.acc], ["西南", 920, PAL.ink3], ["华中", 880, PAL.ink3], ["东北", 354, PAL.ink3]];
  const max = 1800;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {data.map(([n, v, c]) => (
        <div key={n} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 32, fontSize: 10, color: PAL.ink3 }}>{n}</span>
          <div style={{ flex: 1, height: 14, background: PAL.bg2, borderRadius: 2, overflow: "hidden" }}>
            <div style={{ width: `${(v / max) * 100}%`, height: "100%", background: c, opacity: 0.85 }} />
          </div>
          <span className="tabular mono" style={{ width: 36, fontSize: 9.5, color: PAL.ink3, textAlign: "right" }}>{v}</span>
        </div>
      ))}
    </div>
  );
}

// =================================================================
// MAIN — composed canvas
// =================================================================
function TTVariationsCanvas() {
  return (
    <DesignCanvas>
      <DCSection id="chat" title="对话回答布局" subtitle="同样的问答数据 · 三种信息组织方式">
        <DCArtboard id="inline" label="A · Inline narrative · 对话感最强" width={420} height={520}><ChatV_Inline /></DCArtboard>
        <DCArtboard id="cards" label="B · Card-stacked · 模块清晰" width={420} height={520}><ChatV_Cards /></DCArtboard>
        <DCArtboard id="split" label="C · Split canvas · 文图并列" width={520} height={520}><ChatV_Split /></DCArtboard>
      </DCSection>

      <DCSection id="trace" title="Trace 可视化风格" subtitle="14 步推理过程 · 视觉语言探索">
        <DCArtboard id="timeline" label="A · Timeline · 节奏明确" width={300} height={460}><TraceV_Timeline /></DCArtboard>
        <DCArtboard id="stream" label="B · Stream · 终端式时间戳" width={420} height={460}><TraceV_Stream /></DCArtboard>
        <DCArtboard id="dna" label="C · DNA · 品牌图腾" width={300} height={460}><TraceV_DNA /></DCArtboard>
      </DCSection>

      <DCSection id="dashboard" title="看板卡片视觉" subtitle="同样的指标 · 三种信息密度与情绪">
        <DCArtboard id="minimal" label="A · Minimal · 数字优先" width={420} height={400}><DashV_Minimal /></DCArtboard>
        <DCArtboard id="editorial" label="B · Editorial Dark · 沉浸阅读" width={420} height={400}><DashV_Editorial /></DCArtboard>
        <DCArtboard id="mosaic" label="C · Mosaic · 形状构图" width={420} height={400}><DashV_Mosaic /></DCArtboard>
      </DCSection>

      <DCSection id="report" title="报告章节版式" subtitle="自动生成的报告章节 · 三种版式语调">
        <DCArtboard id="editorial" label="A · Editorial · 杂志感" width={360} height={500}><ReportV_Editorial /></DCArtboard>
        <DCArtboard id="brief" label="B · Brief · TL;DR 优先" width={360} height={500}><ReportV_Brief /></DCArtboard>
        <DCArtboard id="magazine" label="C · Magazine · 双栏" width={420} height={500}><ReportV_Magazine /></DCArtboard>
      </DCSection>

      <DCSection id="login" title="欢迎页 / 登录" subtitle="第一印象 · 三种品牌叙事">
        <DCArtboard id="trace" label="A · Trace 图腾" width={520} height={380}><LoginV_Trace /></DCArtboard>
        <DCArtboard id="hero" label="B · 大字 Hero" width={360} height={380}><LoginV_Hero /></DCArtboard>
        <DCArtboard id="form" label="C · 极简表单" width={300} height={380}><LoginV_Form /></DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

Object.assign(window, { TTVariationsCanvas });
