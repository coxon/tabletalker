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
}

export interface AnalyzeResponse {
  id: string;
  report_html_url: string;
  summary: string;
  findings: Finding[];
  charts: Chart[];
  recommendations: string[];
  is_refusal: boolean;
  confidence?: number | null;
}

// Discriminated union the page uses to render the conversation. Each
// turn is the raw response plus the question that produced it.
export interface Turn {
  question: string;
  response: AnalyzeResponse;
  kind: "parent" | "follow_up";
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

export interface ErrorEvent {
  type: "error";
  status: number;
  detail: string;
  stage_timings: Record<string, unknown>;
}

export type StreamEvent = StageEvent | ResultEvent | ErrorEvent;

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
