export interface SessionStatsOut {
  total: number;
  this_week: number;
  continuable: number;
}

export interface SessionSummaryOut {
  id: string;
  title: string;
  primary_filename: string;
  extra_filenames: string[];
  created_at: number;
  updated_at: number;
  status: "completed" | "refused";
  is_refusal: boolean;
  follow_up_count: number;
  chart_count: number;
  finding_count: number;
}

export interface SessionTurnOut {
  turn_index: number;
  kind: "parent" | "follow_up";
  question: string;
  response_id: string;
  is_refusal: boolean;
  summary: string;
  finding_count: number;
  chart_count: number;
  created_at: number;
}

export interface SessionDetailOut {
  id: string;
  title: string;
  primary_filename: string;
  extra_filenames: string[];
  created_at: number;
  updated_at: number;
  status: "completed" | "refused";
  is_refusal: boolean;
  chart_count: number;
  finding_count: number;
  report_html_url: string;
  sampling_rate: number | null;
  sampling_note: string | null;
  turns: SessionTurnOut[];
}

export interface SessionListOut {
  stats: SessionStatsOut;
  items: SessionSummaryOut[];
}
