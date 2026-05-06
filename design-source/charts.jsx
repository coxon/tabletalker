// Inline SVG charts — no external lib needed
const { useMemo } = React;

// 统一 chart 色板（与 CSS --chart-* 对齐）
const TT_CHART = {
  cat: ["#15875e", "#6e3cf5", "#c2410c", "#2563a8", "#b8341a", "#9a8c0c", "#5e615c", "#1aa074"],
  seqStart: "#f0f9f4",
  seqEnd:   "#0a4a35",
  divNeg:   "#b8341a",
  divMid:   "#b0b3a9",
  divPos:   "#15875e",
};
window.TT_CHART = TT_CHART;

function BarsChart({ data, height = 200, palette }) {
  const max = Math.max(...data.flatMap(d => [d.q1_2025, d.q1_2026]));
  const colors = palette || ["#15875e", "#9bc7b3"];
  return (
    <svg viewBox={`0 0 600 ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {[0, 0.25, 0.5, 0.75, 1].map((t, i) => (
        <line key={i} x1="40" y1={20 + (height - 50) * t} x2="590" y2={20 + (height - 50) * t} stroke="var(--line)" strokeDasharray={i === 4 ? "0" : "2 4"} />
      ))}
      {data.map((d, i) => {
        const x = 50 + i * (540 / data.length);
        const bw = 540 / data.length / 2.6;
        const h1 = ((height - 50) * d.q1_2025) / max;
        const h2 = ((height - 50) * d.q1_2026) / max;
        const isNeg = d.delta < 0;
        // diverging：负值用 brand 暖红，正值用 emerald
        const fillCurr = isNeg ? "var(--chart-d1)" : "var(--chart-d5)";
        const fillPrev = "var(--bg-3)";
        const labelColor = isNeg ? "var(--chart-d1)" : "var(--acc)";
        return (
          <g key={i}>
            <rect x={x} y={height - 30 - h1} width={bw} height={h1} fill={fillPrev} rx="2" />
            <rect x={x + bw + 4} y={height - 30 - h2} width={bw} height={h2} fill={fillCurr} rx="2">
              <animate attributeName="height" from="0" to={h2} dur="0.6s" fill="freeze" />
              <animate attributeName="y" from={height - 30} to={height - 30 - h2} dur="0.6s" fill="freeze" />
            </rect>
            <text x={x + bw + 2} y={height - 14} textAnchor="middle" fontSize="11" fill="var(--ink-3)" fontFamily="var(--font-sans)">{d.region}</text>
            <text x={x + bw + 2} y={height - 30 - h2 - 4} textAnchor="middle" fontSize="10" fill={labelColor} className="tabular" fontWeight="600">{d.delta > 0 ? "+" : ""}{d.delta}%</text>
          </g>
        );
      })}
      <text x="40" y="14" fontSize="10" fill="var(--ink-4)" fontFamily="var(--font-mono)">单位 · 万元</text>
    </svg>
  );
}

function LineChart({ data, height = 180, palette }) {
  const max = Math.max(...data.map(d => d.val)) * 1.1;
  const min = Math.min(...data.map(d => d.val)) * 0.85;
  const range = max - min;
  const points = data.map((d, i) => {
    const x = 40 + (i * 540) / (data.length - 1);
    const y = 20 + ((max - d.val) / range) * (height - 50);
    return [x, y, d];
  });
  const path = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`).join(" ");
  const area = `${path} L${points[points.length - 1][0]},${height - 30} L${points[0][0]},${height - 30} Z`;
  const acc = (palette && palette[0]) || "var(--acc)";
  return (
    <svg viewBox={`0 0 600 ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
      <defs>
        <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={acc} stopOpacity="0.18" />
          <stop offset="100%" stopColor={acc} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((t, i) => (
        <line key={i} x1="40" y1={20 + (height - 50) * t} x2="580" y2={20 + (height - 50) * t} stroke="var(--line)" strokeDasharray={i === 4 ? "0" : "2 4"} />
      ))}
      <path d={area} fill="url(#lineGrad)" />
      <path d={path} fill="none" stroke={acc} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <animate attributeName="stroke-dasharray" from="0 2000" to="2000 0" dur="1s" fill="freeze" />
      </path>
      {points.map(([x, y, d], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="3" fill="var(--surface)" stroke={acc} strokeWidth="2" />
          <text x={x} y={height - 12} textAnchor="middle" fontSize="10" fill="var(--ink-3)" fontFamily="var(--font-mono)">{d.m.slice(5)}</text>
        </g>
      ))}
    </svg>
  );
}

function KPICard({ label, value, delta, sub }) {
  const neg = delta < 0;
  const tone = neg ? "var(--chart-d1)" : "var(--acc)";
  return (
    <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 4, height: "100%" }}>
      <div style={{ fontSize: 10.5, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.06em", fontFamily: "var(--font-mono)" }}>{label}</div>
      <div style={{ fontSize: "var(--fs-2xl, 28px)", fontWeight: 600, letterSpacing: "-0.025em", color: neg ? tone : "var(--ink)", fontFamily: "var(--font-serif)", lineHeight: 1.05 }} className="tabular">
        {delta > 0 ? "+" : ""}{value}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 2 }}>
        <span style={{ fontSize: 11.5, color: tone, fontWeight: 600 }} className="tabular">{delta > 0 ? "▲" : "▼"} {Math.abs(delta)}%</span>
        <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{sub}</span>
      </div>
    </div>
  );
}

function HeatChart({ height = 200, palette }) {
  const rows = ["BU-1", "BU-2", "BU-3", "BU-4", "BU-5"];
  const cols = ["华东", "华北", "华南", "西南", "华中", "东北"];
  const acc = (palette && palette[0]) || "#15875e";
  const data = [
    [82, 71, 44, 68, 73, 51], [78, 80, 38, 65, 70, 49],
    [69, 72, 22, 60, 68, 47], [74, 76, 51, 71, 75, 56],
    [80, 79, 48, 70, 72, 53],
  ];
  const cellW = 80, cellH = 28;
  return (
    <svg viewBox={`0 0 ${60 + cols.length * cellW} ${20 + rows.length * cellH + 20}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {rows.map((r, ri) => (
        <g key={ri}>
          <text x={50} y={36 + ri * cellH} textAnchor="end" fontSize="11" fill="var(--ink-3)" fontFamily="var(--font-mono)">{r}</text>
          {cols.map((c, ci) => {
            const v = data[ri][ci];
            const op = v / 100;
            return (
              <g key={ci}>
                <rect x={60 + ci * cellW} y={20 + ri * cellH} width={cellW - 2} height={cellH - 2} fill={acc} fillOpacity={op} rx="2" />
                <text x={60 + ci * cellW + cellW / 2 - 1} y={36 + ri * cellH} textAnchor="middle" fontSize="10" fill={op > 0.55 ? "#fff" : "var(--ink-2)"} className="tabular">{v}</text>
              </g>
            );
          })}
        </g>
      ))}
      {cols.map((c, ci) => (
        <text key={ci} x={60 + ci * cellW + cellW / 2 - 1} y={20 + rows.length * cellH + 14} textAnchor="middle" fontSize="11" fill="var(--ink-3)">{c}</text>
      ))}
    </svg>
  );
}

function DonutChart({ height = 180, palette }) {
  const cats = (window.TT_CHART && window.TT_CHART.cat) || ["#15875e", "#6e3cf5", "#c2410c", "#2563a8"];
  const segs = [
    { name: "直销", val: 42, color: cats[0] },
    { name: "渠道", val: 28, color: cats[7] },  // mint，跟主色和谐
    { name: "线上", val: 18, color: cats[1] },  // violet
    { name: "OEM", val: 12,  color: cats[2] },  // maple
  ];
  let acc = 0;
  const total = segs.reduce((a, b) => a + b.val, 0);
  const r = 60, cx = 90, cy = 90;
  return (
    <svg viewBox={`0 0 320 ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {segs.map((s, i) => {
        const start = (acc / total) * Math.PI * 2 - Math.PI / 2;
        acc += s.val;
        const end = (acc / total) * Math.PI * 2 - Math.PI / 2;
        const large = end - start > Math.PI ? 1 : 0;
        const x1 = cx + r * Math.cos(start), y1 = cy + r * Math.sin(start);
        const x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end);
        return (
          <path key={i} d={`M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`} fill={s.color} stroke="var(--surface)" strokeWidth="2" />
        );
      })}
      <circle cx={cx} cy={cy} r={36} fill="var(--surface)" />
      <text x={cx} y={cy - 2} textAnchor="middle" fontSize="11" fill="var(--ink-3)" fontFamily="var(--font-mono)">渠道</text>
      <text x={cx} y={cy + 14} textAnchor="middle" fontSize="16" fontWeight="600" fill="var(--ink)" className="tabular">100%</text>
      {segs.map((s, i) => (
        <g key={i} transform={`translate(180, ${30 + i * 30})`}>
          <rect width="10" height="10" fill={s.color} rx="2" />
          <text x="16" y="9" fontSize="11" fill="var(--ink-2)">{s.name}</text>
          <text x="120" y="9" fontSize="11" fill="var(--ink)" textAnchor="end" className="tabular" fontWeight="500">{s.val}%</text>
        </g>
      ))}
    </svg>
  );
}

Object.assign(window, { BarsChart, LineChart, KPICard, HeatChart, DonutChart });
