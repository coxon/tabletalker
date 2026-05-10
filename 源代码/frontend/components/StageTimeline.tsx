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
  // Op kind labels emitted by the planner LLM, in declaration order.
  // Rendered as a chip strip directly under the `plan_llm` row so the
  // user sees the plan being assembled in place rather than in a
  // separate card. Empty array → no chip strip.
  planOps?: string[];
}

/**
 * Live progress timeline shown while `/v1/analyze/stream` is running.
 *
 * Mirrors the screenshot the user asked for: a collapsible header
 * ("Ran N commands, viewed a file") with stage rows underneath, each
 * row having an icon, label, optional `Script` tag, and a status
 * indicator (spinner / check). Plan-op chips and the streaming
 * summary attach to their owning stage rows so the page stays at one
 * visual unit even when LLM intermediates are flowing.
 */
export function StageTimeline({
  stages,
  inFlight,
  planOps = [],
}: StageTimelineProps) {
  // Default collapsed: show only the currently running step + its
  // streaming children (plan-op chips, live summary). The full ledger
  // is one click away. This keeps the middle of the page tight while
  // still surfacing what's happening *right now*. After completion the
  // collapsed view shows just the header summary.
  const [collapsed, setCollapsed] = useState(true);
  const doneCount = stages.filter((s) => s.status === "done").length;
  const total = stages.length;
  // The "current" stage to surface while collapsed. Prefer an explicitly
  // running stage; fall back to the first pending one (handles the brief
  // window between two `stage` events when no row is `running` yet).
  const currentStage =
    stages.find((s) => s.status === "running") ??
    (inFlight ? stages.find((s) => s.status === "pending") : undefined);
  // 1-indexed position of the active stage. Reads more naturally than
  // "X done out of Y" while a stage is in flight ("step 6 of 7" =
  // "we're working on the 6th step right now"). Falls back to the
  // done count when the request has settled.
  const activeIdx = currentStage
    ? stages.findIndex((s) => s.name === currentStage.name) + 1
    : doneCount;
  const headerLabel = inFlight
    ? `第 ${activeIdx} / ${total} 步`
    : doneCount === total
      ? `Done · ${total} 步`
      : `已完成 ${doneCount} / ${total} 步（已结束）`;

  return (
    <div className="overflow-hidden">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center gap-2 px-2 py-2 text-left rounded-md hover:bg-stone-100/60 transition-colors"
      >
        {/* Chevron sits at the leftmost position so the click target
            and the disclosure indicator visually align with the
            indent of the rows it expands. */}
        {collapsed ? (
          <ChevronDown size={14} className="text-stone-400 shrink-0" />
        ) : (
          <ChevronUp size={14} className="text-stone-400 shrink-0" />
        )}
        <div className="text-stone-400 shrink-0">
          {inFlight ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <CheckCircle2 size={14} />
          )}
        </div>
        <div className="flex-1 min-w-0 text-[12px] text-stone-400">
          <span className="text-stone-500">{headerLabel}</span>
          {currentStage && inFlight && (
            <>
              <span className="mx-2 text-stone-300">·</span>
              <span className="text-stone-500">
                {currentStage.label}
              </span>
            </>
          )}
        </div>
      </button>

      {collapsed && currentStage && (
        // Collapsed-but-active: don't render the row chrome again
        // (label is already in the header). For `plan_llm` we show a
        // one-paragraph description of what the planner is doing —
        // the raw op-kind chip strip got dropped because it's
        // `finalize_llm`: livePartial is rendered OUTSIDE this
        // component now (in LiveProgress, as plain prose) so the
        // user sees the summary in its eventual home position. We
        // intentionally show NOTHING extra under the timeline for
        // finalize_llm — the streaming text is the indicator.
        <div className="px-2 pb-2">
          {currentStage.name === "plan_llm" &&
            currentStage.status === "running" && (
            <div className="pl-7 pt-1">
              <p className="text-[12px] leading-relaxed text-stone-500">
                规划器正在把你的问题拆成一条可复算的数据处理流程：先读取数据，再按问题需要筛选、
                计算、分组汇总，最后整理成结果表或图表。
              </p>
            </div>
          )}
        </div>
      )}

      {!collapsed && (
        // Render only steps that have been TOUCHED (running or done).
        // Future pending steps stay hidden so the expanded view grows
        // step-by-step alongside the pipeline instead of front-loading
        // a 7-row ledger of mostly-grey checkboxes. Once the request
        // settles, every step is `done` so all 7 are visible.
        <ol className="pt-1">
          {stages
            .filter((s) => s.status !== "pending")
            .map((stage) => (
              <StageRow
                key={stage.name}
                stage={stage}
                planOps={stage.name === "plan_llm" ? planOps : []}
              />
            ))}
        </ol>
      )}
    </div>
  );
}

function StageRow({
  stage,
  planOps,
}: {
  stage: StageState;
  planOps: string[];
}) {
  const isLLM = stage.name === "plan_llm" || stage.name === "finalize_llm";
  return (
    <li>
      <div className="flex items-center gap-2.5 px-2 py-1.5">
        <span className="text-stone-300 shrink-0">
          <Terminal size={12} />
        </span>
        <span className="text-[12px] text-stone-500 flex-1 min-w-0 truncate">
          {stage.label}
        </span>
        {isLLM && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded text-stone-400 shrink-0">
            LLM
          </span>
        )}
        <span className="shrink-0 w-12 text-right">
          {stage.status === "done" ? (
            <span className="text-stone-400 inline-flex items-center gap-1 text-[11px] font-mono">
              <CheckCircle2 size={12} />
              {typeof stage.duration_s === "number"
                ? `${stage.duration_s.toFixed(1)}s`
                : ""}
            </span>
          ) : stage.status === "running" ? (
            <Loader2 size={12} className="text-stone-400 animate-spin inline" />
          ) : (
            <Circle size={10} className="text-stone-200 inline" />
          )}
        </span>
      </div>
      {planOps.length > 0 && (
        <div className="px-2 pb-2 pl-7">
          <p className="text-[12px] leading-relaxed text-stone-500">
            规划器正在把你的问题拆成一条可复算的数据处理流程：先读取数据，再按问题需要筛选、
            计算、分组汇总，最后整理成结果表或图表。
          </p>
        </div>
      )}
    </li>
  );
}
