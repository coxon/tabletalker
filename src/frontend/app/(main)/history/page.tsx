"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import {
  Search,
  Filter,
  ChevronDown,
  ExternalLink,
  Download,
  Trash2,
  FileSpreadsheet,
  BarChart3,
  MessageSquare,
  Loader2,
  Frown,
  Clock,
  TrendingUp,
  CheckCircle2,
} from "lucide-react";

import type {
  SessionListOut,
  SessionSummaryOut,
  SessionDetailOut,
  SessionStatsOut,
} from "@/lib/sessions";

type StatusFilter = "all" | "completed" | "refused";

interface ApiErrorBody {
  detail?: string;
  error?: string;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    return body.detail ?? body.error ?? response.statusText;
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

function formatTime(epoch: number): string {
  const date = new Date(epoch * 1000);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} 小时前`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay} 天前`;
  return date.toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
}

export default function V2HistoryPage() {
  const [items, setItems] = useState<SessionSummaryOut[]>([]);
  const [stats, setStats] = useState<SessionStatsOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const fetchSessions = useCallback(async (q: string, status: StatusFilter) => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (status !== "all") params.set("status", status);
    const qs = params.toString();
    try {
      const response = await fetch(`/api/sessions${qs ? `?${qs}` : ""}`);
      if (!response.ok) {
        const message = await readError(response);
        setError(message);
        return;
      }
      const data = (await response.json()) as SessionListOut;
      setItems(data.items);
      setStats(data.stats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions(query, statusFilter);
  }, [fetchSessions, statusFilter]);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchSessions(query, statusFilter);
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [query, fetchSessions, statusFilter]);

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        const response = await fetch(`/api/sessions/${id}`, {
          method: "DELETE",
        });
        if (response.status === 204 || response.ok) {
          setItems((prev) => prev.filter((item) => item.id !== id));
          if (expandedId === id) setExpandedId(null);
          if (stats) {
            setStats({ ...stats, total: Math.max(0, stats.total - 1) });
          }
          toast.success("已删除");
        } else {
          const message = await readError(response);
          toast.error("删除失败", { description: message });
        }
      } catch (err) {
        toast.error("删除失败", {
          description: err instanceof Error ? err.message : "请求失败",
        });
      }
    },
    [expandedId, stats],
  );

  return (
    <div className="max-w-[1200px] mx-auto space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-800">历史分析</h2>
        <p className="text-sm text-slate-500 mt-1">查看过去发起的所有分析会话，可以查看报告或删除。</p>
      </div>

      {/* Stats Cards */}
      {stats ? <V2StatsCards stats={stats} /> : null}

      {/* Search & Filter Bar */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索标题或文件名…"
            className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm placeholder:text-slate-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 focus:border-indigo-400 outline-none transition-all"
          />
        </div>
        <div className="flex items-center gap-1.5">
          <Filter size={14} className="text-slate-400" />
          {(["all", "completed", "refused"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setStatusFilter(f)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                statusFilter === f
                  ? "bg-indigo-600 text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {f === "all" ? "全部" : f === "completed" ? "已完成" : "已拒答"}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={20} className="animate-spin text-slate-400" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-center text-sm text-rose-600">
          {error}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-16 text-center bg-white rounded-xl border border-slate-200 shadow-sm">
          <Clock size={28} className="text-slate-400" />
          <p className="text-sm text-slate-500">
            {query || statusFilter !== "all"
              ? "没有匹配的分析记录"
              : "还没有分析记录，去首页开始第一次分析吧"}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <AnimatePresence initial={false}>
            {items.map((item) => (
              <V2SessionRow
                key={item.id}
                item={item}
                expanded={expandedId === item.id}
                onToggle={() =>
                  setExpandedId(expandedId === item.id ? null : item.id)
                }
                onDelete={() => handleDelete(item.id)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats Cards
// ---------------------------------------------------------------------------
function V2StatsCards({ stats }: { stats: SessionStatsOut }) {
  const cards = [
    { label: "总分析", value: stats.total, icon: BarChart3, color: "bg-indigo-50 text-indigo-600" },
    { label: "本周", value: stats.this_week, icon: TrendingUp, color: "bg-emerald-50 text-emerald-600" },
    { label: "可追问", value: stats.continuable, icon: CheckCircle2, color: "bg-blue-50 text-blue-600" },
  ];

  return (
    <div className="grid grid-cols-3 gap-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white shadow-sm p-4"
        >
          <div className={`p-2 rounded-lg ${card.color}`}>
            <card.icon size={18} />
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-800">{card.value}</p>
            <p className="text-xs text-slate-500">{card.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Session Row
// ---------------------------------------------------------------------------
interface V2SessionRowProps {
  item: SessionSummaryOut;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
}

function V2SessionRow({ item, expanded, onToggle, onDelete }: V2SessionRowProps) {
  return (
    <motion.div
      layout
      className="rounded-xl border border-slate-200 bg-white shadow-sm transition-colors hover:border-slate-300"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-5 py-4 text-left"
      >
        <ChevronDown
          size={14}
          className={`shrink-0 text-slate-400 transition-transform duration-200 ${
            expanded ? "rotate-0" : "-rotate-90"
          }`}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-800">{item.title}</p>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <FileSpreadsheet size={12} />
              {item.primary_filename}
            </span>
            <span>·</span>
            <span>{formatTime(item.updated_at)}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {item.follow_up_count > 0 ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-xs font-medium">
              <MessageSquare size={12} />
              {item.follow_up_count}
            </span>
          ) : null}
          {item.chart_count > 0 ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-xs font-medium">
              <BarChart3 size={12} />
              {item.chart_count}
            </span>
          ) : null}
          {item.is_refusal ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 text-xs font-medium">
              <Frown size={12} />
              拒答
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-medium">
              <CheckCircle2 size={12} />
              完成
            </span>
          )}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
            className="overflow-hidden"
          >
            <V2SessionDetailPanel id={item.id} onDelete={onDelete} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Session Detail Panel
// ---------------------------------------------------------------------------
function V2SessionDetailPanel({
  id,
  onDelete,
}: {
  id: string;
  onDelete: () => void;
}) {
  const [detail, setDetail] = useState<SessionDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(`/api/sessions/${id}`);
        if (!response.ok) return;
        const data = (await response.json()) as SessionDetailOut;
        if (!cancelled) setDetail(data);
      } catch {
        // silent
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center border-t border-slate-100 px-4 py-8">
        <Loader2 size={16} className="animate-spin text-slate-400" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="border-t border-slate-100 px-4 py-6 text-center text-sm text-slate-400">
        无法加载详情
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 border-t border-slate-100 px-5 py-4">
      {detail.turns.map((turn) => (
        <div
          key={turn.turn_index}
          className="rounded-lg border border-slate-100 bg-slate-50 p-4"
        >
          <div className="mb-2 flex items-center gap-2">
            <span className={`px-2 py-0.5 rounded text-[11px] font-medium ${
              turn.kind === "parent" ? "bg-emerald-100 text-emerald-700" : "bg-indigo-100 text-indigo-700"
            }`}>
              {turn.kind === "parent" ? "首次提问" : `追问 #${turn.turn_index}`}
            </span>
            {turn.is_refusal ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-rose-100 text-rose-700 text-[11px] font-medium">
                <Frown size={10} />
                拒答
              </span>
            ) : null}
          </div>
          <p className="text-sm font-semibold text-slate-800">{turn.question}</p>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            {turn.summary}
          </p>
          <div className="mt-3 flex items-center gap-3">
            <a
              href={`/reports/${turn.response_id}.html`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
            >
              <ExternalLink size={12} />
              查看报告
            </a>
            <a
              href={`/api/reports/${turn.response_id}/download`}
              className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-800 transition-colors"
            >
              <Download size={12} />
              下载 HTML
            </a>
            <span className="text-xs text-slate-400">
              {turn.finding_count} 发现 · {turn.chart_count} 图表
            </span>
          </div>
        </div>
      ))}

      <div className="flex items-center justify-between pt-2 border-t border-slate-100">
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <span className="flex items-center gap-1">
            <FileSpreadsheet size={12} />
            {detail.primary_filename}
            {detail.extra_filenames.length > 0
              ? ` +${detail.extra_filenames.length}`
              : ""}
          </span>
          {detail.sampling_rate != null ? (
            <span>采样 {(detail.sampling_rate * 100).toFixed(0)}%</span>
          ) : null}
        </div>
        {confirmDelete ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-rose-600">确认删除？</span>
            <button
              type="button"
              className="text-xs px-2.5 py-1 rounded-md bg-rose-600 text-white hover:bg-rose-700 transition-colors"
              onClick={() => {
                onDelete();
                setConfirmDelete(false);
              }}
            >
              删除
            </button>
            <button
              type="button"
              className="text-xs px-2.5 py-1 rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
              onClick={() => setConfirmDelete(false)}
            >
              取消
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="text-xs px-2.5 py-1 rounded-md border border-slate-200 text-slate-400 hover:text-rose-600 hover:border-rose-200 transition-colors flex items-center gap-1"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 size={12} />
            删除
          </button>
        )}
      </div>
    </div>
  );
}
