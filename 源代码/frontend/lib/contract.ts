// Mirror of 源代码/backend/app/analyze/schema.py (the frozen submission
// contract). Kept structural — `Record<string, unknown>` for fields the
// UI doesn't actively render — so additive backend changes don't break
// the build, but anything we *do* render is typed.

export type ChartKind =
  | "柱状图"
  | "折线图"
  | "饼图"
  | "散点图"
  | "热力图"
  | "箱线图";

export interface Evidence {
  dataset: string;
  table: string;
  columns: string[];
  filters: string;
  aggregation: string;
  value: number | string;
  row_count?: number | null;
}

export interface Finding {
  title: string;
  detail: string;
  evidence: Evidence[];
}

export interface Chart {
  type: ChartKind;
  title: string;
  html_anchor: string;
  // JSON-encoded ECharts option for inline render in the chat thread.
  // Optional — only the first chart of each analyze response carries
  // it (backend caps inline render at 1/turn to keep the chat tight).
  // Empty string / undefined → fall back to the report iframe.
  echarts_option?: string | null;
}

export interface AnalyzeResponse {
  id: string;
  report_html_url: string;
  summary: string;
  findings: Finding[];
  charts: Chart[];
  recommendations: string[];
  suggested_questions?: string[];
  is_refusal: boolean;
  confidence?: number | null;
}

// Discriminated union the page uses to render the conversation. Each
// turn is the raw response plus the question that produced it. The
// optional `stagesSnapshot` / `planOps` capture the per-turn pipeline
// trace at the moment the response landed so the StageTimeline stays
// rendered (collapsed) above each AssistantMessage in the thread —
// rather than vanishing as soon as the next turn starts.
//
// `attachedFiles` is the file-metadata snapshot for the parent turn
// (the only one that uploads files). Stored as plain `{name, size}`
// rather than `File` so the whole `Turn` survives JSON serialization
// (localStorage). After a refresh the original `File` object is gone
// — the metadata is enough to redraw the FileAttachmentCard above the
// user bubble. Backend session reuse handles the actual data.
export interface AttachedFileMeta {
  name: string;
  size: number;
}

export interface Turn {
  question: string;
  response: AnalyzeResponse;
  kind: "parent" | "follow_up";
  stagesSnapshot?: StageState[];
  planOpsSnapshot?: string[];
  livePartialSnapshot?: string;
  attachedFiles?: AttachedFileMeta[];
}

export type AnalyzePhase =
  | { name: "idle" }
  | { name: "uploading" }
  | { name: "analyzing" }
  | { name: "follow_up" }
  | { name: "done" }
  | { name: "error"; message: string };

// ----------------------------------------------------------------------------
// /v1/analyze/stream — NDJSON event stream
// ----------------------------------------------------------------------------
//
// Each line is one JSON object. `result` (success) or `error` is the
// terminal event; everything before it is a `stage` event used to drive
// the live timeline UI. Stage names match `STAGE_ORDER` in
// `源代码/backend/app/analyze/stages.py` — keep this list in sync.

export type StageName =
  | "profile"
  | "preview_plan_req"
  | "plan_llm"
  | "execute"
  | "evidence"
  | "finalize_llm"
  | "render";

export const STAGE_ORDER: readonly StageName[] = [
  "profile",
  "preview_plan_req",
  "plan_llm",
  "execute",
  "evidence",
  "finalize_llm",
  "render",
] as const;

export const STAGE_LABELS: Record<StageName, string> = {
  profile: "解析数据并剖析字段",
  preview_plan_req: "准备规划上下文",
  plan_llm: "规划器调用（LLM）",
  execute: "执行类型化算子",
  evidence: "构造证据行",
  finalize_llm: "生成结论摘要（LLM）",
  render: "渲染 HTML 报告",
};

export interface StageEvent {
  type: "stage";
  name: StageName;
  status: "start" | "end";
  duration_s?: number;
}

export interface ResultEvent {
  type: "result";
  data: AnalyzeResponse;
  stage_timings: Record<string, unknown>;
}

export interface PartialEvent {
  // Token-level updates emitted during the LLM stages so the user sees
  // concrete progress instead of staring at a silent spinner.
  //
  //   field: "summary"        — finalize_llm streams its JSON; we
  //                             surface the accumulating `summary`
  //                             value as `delta` text.
  //   field: "finding"        — one event per closed `{title, detail}`
  //                             object inside the `findings` array.
  //                             Carried in `value`.
  //   field: "recommendation" — one event per closed string element
  //                             inside the `recommendations` array.
  //                             Carried in `text`.
  //   field: "plan_op"        — plan_llm streams ops; one event per
  //                             `"kind"` value the JSON closes,
  //                             carried in `kind`.
  type: "partial";
  field: "summary" | "plan_op" | "finding" | "recommendation";
  delta?: string;
  kind?: string;
  value?: { title: string; detail: string };
  text?: string;
}

export interface ErrorEvent {
  type: "error";
  status: number;
  detail: string;
  stage_timings: Record<string, unknown>;
}

export type StreamEvent = StageEvent | ResultEvent | PartialEvent | ErrorEvent;

export type StageStatus = "pending" | "running" | "done";

export interface StageState {
  name: StageName;
  label: string;
  status: StageStatus;
  duration_s?: number;
}

export function initialStageStates(): StageState[] {
  return STAGE_ORDER.map((name) => ({
    name,
    label: STAGE_LABELS[name],
    status: "pending",
  }));
}

export function applyStageEvent(
  current: StageState[],
  event: StageEvent,
): StageState[] {
  return current.map((s) => {
    if (s.name !== event.name) return s;
    if (event.status === "start") {
      return { ...s, status: "running" };
    }
    return { ...s, status: "done", duration_s: event.duration_s };
  });
}
