"use client";

import { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  Terminal,
  Circle,
} from "lucide-react";
import type { StageState } from "../lib/contract";

interface StageTimelineProps {
  stages: StageState[];
  // Whether the request is still in flight. Drives the header label and
  // the spinner on the active row when no stage event has arrived yet.
  inFlight: boolean;
}

/**
 * Live progress timeline shown while `/v1/analyze/stream` is running.
 *
 * Mirrors the screenshot the user asked for: a collapsible header
 * ("Ran N commands, viewed a file") with stage rows underneath, each
 * row having an icon, label, optional `Script` tag, and a status
 * indicator (spinner / check). When the stream ends successfully the
 * caller switches the page out of the analyzing phase, so this card
 * unmounts; on failure the caller keeps the card visible so the user
 * can see which stage was running when the error landed.
 */
export function StageTimeline({ stages, inFlight }: StageTimelineProps) {
  const [collapsed, setCollapsed] = useState(false);
  const doneCount = stages.filter((s) => s.status === "done").length;
  const total = stages.length;
  const headerLabel = inFlight
    ? `已完成 ${doneCount} / ${total} 步`
    : doneCount === total
      ? `Done · ${total} 步`
      : `已完成 ${doneCount} / ${total} 步（已结束）`;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-slate-50 transition-colors text-left"
      >
        <div className="p-1.5 rounded-md bg-indigo-50 text-indigo-600">
          {inFlight ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <CheckCircle2 size={16} />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-slate-800">
            {headerLabel}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            TableTalker 正在分析你的数据 · 通常 30-90 秒
          </div>
        </div>
        {collapsed ? (
          <ChevronDown size={16} className="text-slate-400" />
        ) : (
          <ChevronUp size={16} className="text-slate-400" />
        )}
      </button>

      {!collapsed && (
        <ol className="border-t border-slate-100">
          {stages.map((stage) => (
            <StageRow key={stage.name} stage={stage} />
          ))}
        </ol>
      )}
    </div>
  );
}

function StageRow({ stage }: { stage: StageState }) {
  const isLLM = stage.name === "plan_llm" || stage.name === "finalize_llm";
  return (
    <li className="flex items-center gap-3 px-5 py-2.5 border-b border-slate-50 last:border-b-0">
      <span className="text-slate-400 shrink-0">
        <Terminal size={14} />
      </span>
      <span className="text-sm text-slate-700 flex-1 min-w-0 truncate">
        {stage.label}
      </span>
      {isLLM && (
        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 shrink-0">
          LLM
        </span>
      )}
      <span className="shrink-0 w-12 text-right">
        {stage.status === "done" ? (
          <span className="text-emerald-600 inline-flex items-center gap-1 text-[11px] font-mono">
            <CheckCircle2 size={14} />
            {typeof stage.duration_s === "number"
              ? `${stage.duration_s.toFixed(1)}s`
              : ""}
          </span>
        ) : stage.status === "running" ? (
          <Loader2 size={14} className="text-indigo-600 animate-spin inline" />
        ) : (
          <Circle size={12} className="text-slate-300 inline" />
        )}
      </span>
    </li>
  );
}
