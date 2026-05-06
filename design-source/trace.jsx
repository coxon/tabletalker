// Agent 14-step Trace — the signature visualization
// Three styles, all driven by the same data
const { useState, useEffect, useRef } = React;

function TraceViz({ steps, style = "timeline", playing, currentStep, onStepClick, compact }) {
  if (style === "timeline") return <TraceTimeline steps={steps} playing={playing} currentStep={currentStep} onStepClick={onStepClick} compact={compact} />;
  if (style === "stream") return <TraceStream steps={steps} playing={playing} currentStep={currentStep} onStepClick={onStepClick} />;
  if (style === "dna") return <TraceDNA steps={steps} playing={playing} currentStep={currentStep} onStepClick={onStepClick} />;
  return null;
}

// Style 1: Vertical timeline with grouped lanes
function TraceTimeline({ steps, playing, currentStep, onStepClick, compact }) {
  const groups = ["感知", "理解", "执行", "校验", "输出"];
  const groupColors = {
    感知: "var(--ink-3)",
    理解: "var(--elec)",
    执行: "var(--acc)",
    校验: "var(--info)",
    输出: "var(--warn)",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, padding: compact ? "8px 0" : "12px 0" }}>
      {steps.map((s, idx) => {
        const isActive = currentStep === idx;
        const isPast = currentStep > idx;
        const isSkip = s.status === "skip";
        const isRetry = s.status === "retry";
        const c = groupColors[s.group];
        return (
          <div key={s.i} onClick={() => onStepClick && onStepClick(idx)}
            tabIndex={0}
            role="button"
            aria-label={`步骤 ${s.i} · ${s.name}`}
            onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && onStepClick) { e.preventDefault(); onStepClick(idx); } }}
            style={{
              display: "grid", gridTemplateColumns: "44px 16px 1fr auto",
              gap: 10, alignItems: "center",
              padding: compact ? "5px 12px" : "8px 12px",
              cursor: "pointer",
              opacity: isSkip ? 0.35 : 1,
              background: isActive ? "var(--bg-2)" : "transparent",
              borderLeft: `2px solid ${isActive ? c : "transparent"}`,
              transition: "background 0.2s",
            }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-4)" }}>
              S{String(s.i).padStart(2, "0")}
            </div>
            <div style={{ position: "relative", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <div style={{
                width: 8, height: 8, borderRadius: "50%",
                background: isPast || isActive ? c : "var(--line-2)",
                boxShadow: isActive ? `0 0 0 4px ${c}22` : "none",
                transition: "all 0.3s",
              }} />
              {idx < steps.length - 1 && (
                <div style={{
                  position: "absolute", top: "50%", left: "50%", width: 1,
                  height: "100%", background: isPast ? c : "var(--line)",
                  transform: "translateX(-50%)",
                }} />
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 12.5, fontWeight: 500, color: "var(--ink)" }}>{s.name}</span>
                {s.badge && <span className="tt-tag tt-tag--elec">{s.badge}</span>}
                {isRetry && <span className="tt-tag tt-tag--warn">retry</span>}
                {isActive && playing && <span className="mono" style={{ fontSize: 10, color: c }}>▸ 执行中</span>}
              </div>
              {!compact && s.detail !== "—" && (
                <div style={{ fontSize: 11.5, color: "var(--ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.detail}</div>
              )}
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--ink-4)" }} className="tabular">
              {s.t > 0 ? `${s.t}ms` : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Style 2: Horizontal stream — flowing chips with progress
function TraceStream({ steps, playing, currentStep, onStepClick }) {
  const groupColors = {
    感知: "#6b6e69", 理解: "#6e3cf5", 执行: "#15875e", 校验: "#2563a8", 输出: "#c2630c",
  };
  return (
    <div style={{ padding: "12px 16px", overflowX: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 0, minWidth: "max-content" }}>
        {steps.map((s, idx) => {
          const isActive = currentStep === idx;
          const isPast = currentStep > idx;
          const isSkip = s.status === "skip";
          const c = groupColors[s.group];
          return (
            <React.Fragment key={s.i}>
              <div onClick={() => onStepClick && onStepClick(idx)}
                style={{
                  display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
                  padding: "8px 4px", cursor: "pointer", minWidth: 80,
                  opacity: isSkip ? 0.3 : 1,
                }}>
                <div style={{
                  width: isActive ? 28 : 22, height: isActive ? 28 : 22,
                  borderRadius: "50%",
                  background: isPast || isActive ? c : "var(--surface)",
                  border: `1.5px solid ${isPast || isActive ? c : "var(--line-2)"}`,
                  color: isPast || isActive ? "#fff" : "var(--ink-3)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontFamily: "var(--font-mono)", fontWeight: 600,
                  boxShadow: isActive ? `0 0 0 4px ${c}33` : "none",
                  transition: "all 0.3s",
                }}>
                  {isPast ? "✓" : s.i}
                </div>
                <div style={{
                  fontSize: 10.5, color: isActive ? c : "var(--ink-3)",
                  textAlign: "center", lineHeight: 1.2, maxWidth: 76,
                  fontWeight: isActive ? 600 : 400,
                }}>{s.name}</div>
              </div>
              {idx < steps.length - 1 && (
                <div style={{ width: 16, height: 1, background: isPast ? c : "var(--line)", marginTop: -16, opacity: isSkip ? 0.3 : 1 }} />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

// Style 3: DNA — two-helix lanes (LLM ↔ Tools)
function TraceDNA({ steps, playing, currentStep, onStepClick }) {
  const llmSteps = ["感知", "理解", "输出"];
  const colorFor = (g) => g === "执行" ? "var(--acc)" : g === "校验" ? "var(--info)" : "var(--elec)";
  return (
    <div style={{ padding: "16px 8px", position: "relative" }}>
      <div style={{ display: "flex", justifyContent: "space-between", padding: "0 24px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-4)" }}>
        <span>LLM 推理</span>
        <span>Tool 执行</span>
      </div>
      <div style={{ position: "relative" }}>
        {steps.map((s, idx) => {
          const isLLM = llmSteps.includes(s.group);
          const isActive = currentStep === idx;
          const isPast = currentStep > idx;
          const c = colorFor(s.group);
          const isSkip = s.status === "skip";
          return (
            <div key={s.i} onClick={() => onStepClick && onStepClick(idx)}
              style={{
                display: "grid", gridTemplateColumns: "1fr 60px 1fr",
                alignItems: "center", padding: "4px 0",
                cursor: "pointer", opacity: isSkip ? 0.3 : 1,
              }}>
              <div style={{ textAlign: "right", paddingRight: 12, opacity: isLLM ? 1 : 0.25 }}>
                {isLLM && (
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", background: isActive ? c : "transparent", color: isActive ? "#fff" : "var(--ink)", borderRadius: 4, fontSize: 12, border: `1px solid ${isPast || isActive ? c : "var(--line)"}` }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, opacity: 0.7 }}>S{s.i}</span>
                    <span>{s.name}</span>
                  </div>
                )}
              </div>
              <div style={{ display: "flex", justifyContent: "center", position: "relative" }}>
                <svg width="60" height="22" style={{ overflow: "visible" }}>
                  <line x1="0" y1="11" x2="60" y2="11" stroke={isPast || isActive ? c : "var(--line)"} strokeWidth="1" strokeDasharray={isLLM ? "0" : "3 3"} />
                  <circle cx="30" cy="11" r={isActive ? 5 : 3} fill={isPast || isActive ? c : "var(--line-2)"}>
                    {isActive && <animate attributeName="r" values="3;6;3" dur="1.2s" repeatCount="indefinite" />}
                  </circle>
                </svg>
              </div>
              <div style={{ paddingLeft: 12, opacity: !isLLM ? 1 : 0.25 }}>
                {!isLLM && (
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", background: isActive ? c : "transparent", color: isActive ? "#fff" : "var(--ink)", borderRadius: 4, fontSize: 12, border: `1px solid ${isPast || isActive ? c : "var(--line)"}` }}>
                    <span>{s.name}</span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, opacity: 0.7 }}>{s.t}ms</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

window.TraceViz = TraceViz;
