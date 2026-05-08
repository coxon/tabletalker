"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Search,
  FileText,
  ExternalLink,
  Download,
  Loader2,
  Eye,
  X,
  BarChart3,
  Lightbulb,
  FileSpreadsheet,
  Clock,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import type {
  SessionListOut,
  SessionSummaryOut,
  SessionDetailOut,
} from "@/lib/sessions";

interface ReportEntry {
  sessionId: string;
  sessionTitle: string;
  primaryFilename: string;
  turnIndex: number;
  kind: "parent" | "follow_up";
  question: string;
  responseId: string;
  summary: string;
  findingCount: number;
  chartCount: number;
  createdAt: number;
  isRefusal: boolean;
}

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

export default function V2ReportsPage() {
  const [reports, setReports] = useState<ReportEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [previewId, setPreviewId] = useState<string | null>(null);

  const fetchReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const sessRes = await fetch("/api/sessions");
      if (!sessRes.ok) {
        setError(await readError(sessRes));
        return;
      }
      const sessList = (await sessRes.json()) as SessionListOut;

      const entries: ReportEntry[] = [];
      const detailPromises = sessList.items.map(async (item: SessionSummaryOut) => {
        try {
          const detRes = await fetch(`/api/sessions/${item.id}`);
          if (!detRes.ok) return;
          const detail = (await detRes.json()) as SessionDetailOut;
          for (const turn of detail.turns) {
            entries.push({
              sessionId: item.id,
              sessionTitle: item.title,
              primaryFilename: item.primary_filename,
              turnIndex: turn.turn_index,
              kind: turn.kind,
              question: turn.question,
              responseId: turn.response_id,
              summary: turn.summary,
              findingCount: turn.finding_count,
              chartCount: turn.chart_count,
              createdAt: turn.created_at,
              isRefusal: turn.is_refusal,
            });
          }
        } catch {
          // skip failed detail loads
        }
      });

      await Promise.all(detailPromises);
      entries.sort((a, b) => b.createdAt - a.createdAt);
      setReports(entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReports();
  }, [fetchReports]);

  const filtered = query.trim()
    ? reports.filter(
        (r) =>
          r.sessionTitle.toLowerCase().includes(query.toLowerCase()) ||
          r.question.toLowerCase().includes(query.toLowerCase()) ||
          r.primaryFilename.toLowerCase().includes(query.toLowerCase()),
      )
    : reports;

  return (
    <div className="max-w-[1200px] mx-auto space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-800">报告中心</h2>
        <p className="text-sm text-slate-500 mt-1">集中查看所有分析会话生成的 HTML 报告。</p>
      </div>

      {/* Stats */}
      {!loading && !error && (
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-indigo-50 text-indigo-600">
              <FileText size={18} />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-800">{reports.length}</p>
              <p className="text-xs text-slate-500">总报告数</p>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-emerald-50 text-emerald-600">
              <BarChart3 size={18} />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-800">{reports.reduce((s, r) => s + r.chartCount, 0)}</p>
              <p className="text-xs text-slate-500">总图表数</p>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-50 text-amber-600">
              <Lightbulb size={18} />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-800">{reports.reduce((s, r) => s + r.findingCount, 0)}</p>
              <p className="text-xs text-slate-500">总发现数</p>
            </div>
          </div>
        </div>
      )}

      {/* Search Bar */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div className="relative">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索报告标题、问题或文件名…"
            className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm placeholder:text-slate-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 focus:border-indigo-400 outline-none transition-all"
          />
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
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-16 bg-white rounded-xl border border-slate-200 shadow-sm text-center">
          <FileText size={28} className="text-slate-400" />
          <p className="text-sm text-slate-500">
            {query ? "没有匹配的报告" : "还没有生成过报告"}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/50">
                <th className="text-left py-3 px-5 text-xs font-bold text-slate-500 uppercase tracking-wider">报告</th>
                <th className="text-left py-3 px-4 text-xs font-bold text-slate-500 uppercase tracking-wider">数据文件</th>
                <th className="text-center py-3 px-3 text-xs font-bold text-slate-500 uppercase tracking-wider">发现</th>
                <th className="text-center py-3 px-3 text-xs font-bold text-slate-500 uppercase tracking-wider">图表</th>
                <th className="text-left py-3 px-4 text-xs font-bold text-slate-500 uppercase tracking-wider">时间</th>
                <th className="text-center py-3 px-4 text-xs font-bold text-slate-500 uppercase tracking-wider">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {filtered.map((report) => (
                <tr key={`${report.responseId}-${report.turnIndex}`} className="hover:bg-slate-50/50 transition-colors">
                  <td className="py-3.5 px-5">
                    <div className="flex items-start gap-3">
                      <div className={`p-1.5 rounded shrink-0 ${
                        report.kind === "parent"
                          ? "bg-emerald-50 text-emerald-600"
                          : "bg-indigo-50 text-indigo-600"
                      }`}>
                        <FileText size={14} />
                      </div>
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-800 truncate max-w-[300px]">{report.question}</p>
                        <p className="text-xs text-slate-400 mt-0.5 truncate max-w-[300px]">
                          {report.sessionTitle}
                          {report.kind === "follow_up" ? ` · 追问 #${report.turnIndex}` : ""}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="py-3.5 px-4">
                    <span className="inline-flex items-center gap-1 text-xs text-slate-600">
                      <FileSpreadsheet size={12} className="text-slate-400" />
                      {report.primaryFilename}
                    </span>
                  </td>
                  <td className="py-3.5 px-3 text-center">
                    <span className="inline-flex items-center justify-center min-w-[28px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 text-xs font-medium">
                      {report.findingCount}
                    </span>
                  </td>
                  <td className="py-3.5 px-3 text-center">
                    <span className="inline-flex items-center justify-center min-w-[28px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-xs font-medium">
                      {report.chartCount}
                    </span>
                  </td>
                  <td className="py-3.5 px-4">
                    <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                      <Clock size={12} />
                      {formatTime(report.createdAt)}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-center">
                    <div className="flex items-center justify-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => setPreviewId(report.responseId)}
                        className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700 bg-indigo-50 px-2.5 py-1 rounded-md transition-colors"
                      >
                        <Eye size={12} />
                        预览
                      </button>
                      <a
                        href={`/reports/${report.responseId}.html`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-700 bg-slate-100 px-2.5 py-1 rounded-md transition-colors"
                      >
                        <ExternalLink size={12} />
                        新窗口
                      </a>
                      <a
                        href={`/api/reports/${report.responseId}/download`}
                        className="flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-800 bg-emerald-50 px-2.5 py-1 rounded-md transition-colors"
                      >
                        <Download size={12} />
                        下载
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Preview Modal */}
      <AnimatePresence>
        {previewId && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            onClick={() => setPreviewId(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="relative w-[90vw] h-[85vh] bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-200"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                  <FileText size={16} className="text-indigo-600" />
                  报告预览
                  <span className="font-mono text-xs text-slate-400">{previewId}</span>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={`/reports/${previewId}.html`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700 bg-white border border-indigo-200 px-3 py-1.5 rounded-md transition-colors"
                  >
                    <ExternalLink size={12} />
                    新窗口打开
                  </a>
                  <a
                    href={`/api/reports/${previewId}/download`}
                    className="flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-800 bg-white border border-emerald-200 px-3 py-1.5 rounded-md transition-colors"
                  >
                    <Download size={12} />
                    下载 HTML
                  </a>
                  <button
                    type="button"
                    onClick={() => setPreviewId(null)}
                    className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                  >
                    <X size={18} />
                  </button>
                </div>
              </div>
              <iframe
                src={`/reports/${previewId}.html`}
                className="w-full h-[calc(100%-52px)]"
                title="Report Preview"
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
