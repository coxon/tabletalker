"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import {
  Search,
  Filter,
  ChevronDown,
  ExternalLink,
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

export default function HistoryPage() {
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
    <main className="mx-auto flex w-full max-w-[88ch] flex-col gap-6 px-6 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="font-display text-[2rem] italic leading-tight tracking-tight">
          历史分析
        </h1>
        <p className="max-w-[58ch] text-[15px] leading-relaxed text-[--color-fg-muted]">
          查看过去发起的所有分析会话，可以查看报告或删除。
        </p>
      </header>

      {stats ? <StatsCards stats={stats} /> : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[--color-fg-faint]"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索标题或文件名…"
            className="w-full rounded-[--radius-md] border border-[--color-border-strong] bg-[--color-bg-elev] py-2 pl-9 pr-3 text-sm placeholder:text-[--color-fg-faint]"
          />
        </div>
        <div className="flex items-center gap-1.5">
          <Filter size={14} className="text-[--color-fg-faint]" />
          {(["all", "completed", "refused"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setStatusFilter(f)}
              className={`rounded-[--radius-sm] px-2.5 py-1 text-[13px] font-medium transition ${
                statusFilter === f
                  ? "bg-[--color-fg] text-[--color-bg]"
                  : "text-[--color-fg-muted] hover:text-[--color-fg]"
              }`}
            >
              {f === "all" ? "全部" : f === "completed" ? "已完成" : "已拒答"}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={20} className="animate-spin text-[--color-fg-faint]" />
        </div>
      ) : error ? (
        <div className="rounded-[--radius-md] border border-[--color-danger-soft] bg-[--color-danger-soft] p-6 text-center text-sm text-[--color-danger]">
          {error}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-16 text-center">
          <Clock size={28} className="text-[--color-fg-faint]" />
          <p className="text-sm text-[--color-fg-muted]">
            {query || statusFilter !== "all"
              ? "没有匹配的分析记录"
              : "还没有分析记录，去首页开始第一次分析吧"}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <AnimatePresence initial={false}>
            {items.map((item) => (
              <SessionRow
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
    </main>
  );
}

function StatsCards({ stats }: { stats: SessionStatsOut }) {
  const cards = [
    {
      label: "总分析",
      value: stats.total,
      icon: BarChart3,
    },
    {
      label: "本周",
      value: stats.this_week,
      icon: TrendingUp,
    },
    {
      label: "可追问",
      value: stats.continuable,
      icon: CheckCircle2,
    },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className="flex items-center gap-3 rounded-[--radius-md] border border-[--color-border] bg-[--color-bg-elev] p-4"
        >
          <card.icon size={18} className="text-[--color-fg-faint]" />
          <div>
            <p className="nums text-xl font-semibold leading-none">
              {card.value}
            </p>
            <p className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
              {card.label}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

interface SessionRowProps {
  item: SessionSummaryOut;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
}

function SessionRow({ item, expanded, onToggle, onDelete }: SessionRowProps) {
  return (
    <motion.div
      layout
      className="rounded-[--radius-md] border border-[--color-border] bg-[--color-bg-elev] transition-colors hover:border-[--color-border-strong]"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <ChevronDown
          size={14}
          className={`shrink-0 text-[--color-fg-faint] transition ${
            expanded ? "rotate-0" : "-rotate-90"
          }`}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{item.title}</p>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[--color-fg-faint]">
            <span className="flex items-center gap-1">
              <FileSpreadsheet size={11} />
              {item.primary_filename}
            </span>
            <span className="nums">{formatTime(item.updated_at)}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {item.follow_up_count > 0 ? (
            <span className="chip nums">
              <MessageSquare size={11} />
              {item.follow_up_count}
            </span>
          ) : null}
          {item.chart_count > 0 ? (
            <span className="chip nums">
              <BarChart3 size={11} />
              {item.chart_count}
            </span>
          ) : null}
          {item.is_refusal ? (
            <span className="chip chip-warn">
              <Frown size={11} />
              拒答
            </span>
          ) : (
            <span className="chip">
              <CheckCircle2 size={11} />
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
            <SessionDetailPanel id={item.id} onDelete={onDelete} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.div>
  );
}

function SessionDetailPanel({
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
      <div className="flex items-center justify-center border-t border-[--color-border] px-4 py-8">
        <Loader2
          size={16}
          className="animate-spin text-[--color-fg-faint]"
        />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="border-t border-[--color-border] px-4 py-6 text-center text-sm text-[--color-fg-faint]">
        无法加载详情
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 border-t border-[--color-border] px-4 py-4">
      {detail.turns.map((turn) => (
        <div
          key={turn.turn_index}
          className="rounded-[--radius-sm] border border-[--color-border] bg-[--color-bg-sunken] p-3"
        >
          <div className="mb-1 flex items-center gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
              {turn.kind === "parent" ? "首次提问" : `追问 #${turn.turn_index}`}
            </span>
            {turn.is_refusal ? (
              <span className="chip chip-warn text-[10px]">
                <Frown size={10} />
                拒答
              </span>
            ) : null}
          </div>
          <p className="text-sm font-medium">{turn.question}</p>
          <p className="mt-1 text-[13px] leading-relaxed text-[--color-fg-muted]">
            {turn.summary}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <a
              href={`/reports/${turn.response_id}.html`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[12px] font-medium text-[--color-fg-muted] hover:text-[--color-fg]"
            >
              <ExternalLink size={11} />
              查看报告
            </a>
            <span className="nums text-[11px] text-[--color-fg-faint]">
              {turn.finding_count} 发现 · {turn.chart_count} 图表
            </span>
          </div>
        </div>
      ))}

      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3 text-[12px] text-[--color-fg-faint]">
          <span className="nums">
            {detail.primary_filename}
            {detail.extra_filenames.length > 0
              ? ` +${detail.extra_filenames.length}`
              : ""}
          </span>
          {detail.sampling_rate != null ? (
            <span className="nums">
              采样 {(detail.sampling_rate * 100).toFixed(0)}%
            </span>
          ) : null}
        </div>
        {confirmDelete ? (
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[--color-danger]">确认删除？</span>
            <button
              type="button"
              className="btn text-[12px]! py-1! px-2! text-[--color-danger]"
              onClick={() => {
                onDelete();
                setConfirmDelete(false);
              }}
            >
              删除
            </button>
            <button
              type="button"
              className="btn text-[12px]! py-1! px-2!"
              onClick={() => setConfirmDelete(false)}
            >
              取消
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="btn text-[12px]! py-1! px-2! text-[--color-fg-faint] hover:text-[--color-danger]"
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
