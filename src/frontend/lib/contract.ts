// Mirror of src/backend/app/analyze/schema.py (the frozen submission
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
