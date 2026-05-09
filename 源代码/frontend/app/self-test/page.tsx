"use client";

import { useEffect, useState } from "react";
import { ClipboardCheck, Download, FileText, FileSpreadsheet, Loader2, RefreshCw } from "lucide-react";

interface LoadState {
  html: string | null;
  error: string | null;
  loading: boolean;
}

export default function SelfTestPage() {
  const [state, setState] = useState<LoadState>({ html: null, error: null, loading: true });

  const load = async () => {
    setState({ html: null, error: null, loading: true });
    try {
      const res = await fetch("/api/self-test/report.html", {
        signal: AbortSignal.timeout(8000),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        setState({
          html: null,
          error: `加载失败：HTTP ${res.status}${detail ? ` · ${detail.slice(0, 120)}` : ""}`,
          loading: false,
        });
        return;
      }
      const html = await res.text();
      setState({ html, error: null, loading: false });
    } catch (err) {
      setState({
        html: null,
        error: err instanceof Error ? err.message : String(err),
        loading: false,
      });
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="min-h-screen bg-[#F8F9FB] text-slate-800 py-8 sm:py-12 px-4 sm:px-8">
      <div className="max-w-[1100px] mx-auto space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
              <ClipboardCheck size={24} className="text-indigo-600" />
              TableTalker 自测报告
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              评测指标自动渲染自仓库内的{" "}
              <code className="px-1.5 py-0.5 rounded bg-slate-100 text-xs">
                自测报告/latest_evaluation_metrics.md
              </code>
              ；下方按钮可下载原始数据，用于离线复现。
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={state.loading}
            className="flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-700 bg-indigo-50 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 shrink-0"
          >
            <RefreshCw size={16} className={state.loading ? "animate-spin" : ""} />
            重新加载
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <a
            href="/api/self-test/report.md"
            download
            className="flex items-center gap-3 px-4 py-3 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 hover:border-slate-300 transition-colors group"
          >
            <div className="p-2 rounded-lg bg-indigo-50 text-indigo-600 group-hover:bg-indigo-100">
              <FileText size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-800">下载 Markdown</div>
              <div className="text-xs text-slate-500">latest_evaluation_metrics.md</div>
            </div>
            <Download size={16} className="text-slate-400" />
          </a>
          <a
            href="/api/self-test/cases.jsonl"
            download
            className="flex items-center gap-3 px-4 py-3 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 hover:border-slate-300 transition-colors group"
          >
            <div className="p-2 rounded-lg bg-emerald-50 text-emerald-600 group-hover:bg-emerald-100">
              <FileText size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-800">下载 JSONL</div>
              <div className="text-xs text-slate-500">每行一个用例 · 含主分析 / 追问 / 陷阱</div>
            </div>
            <Download size={16} className="text-slate-400" />
          </a>
          <a
            href="/api/self-test/cases.xlsx"
            download
            className="flex items-center gap-3 px-4 py-3 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 hover:border-slate-300 transition-colors group"
          >
            <div className="p-2 rounded-lg bg-amber-50 text-amber-600 group-hover:bg-amber-100">
              <FileSpreadsheet size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-800">下载 Excel</div>
              <div className="text-xs text-slate-500">Summary + Cases 双表 · 含状态码</div>
            </div>
            <Download size={16} className="text-slate-400" />
          </a>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 sm:p-8">
          {state.loading ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-500">
              <Loader2 size={28} className="animate-spin mb-3" />
              <p className="text-sm">正在加载自测报告…</p>
            </div>
          ) : state.error ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
              <div className="font-semibold mb-1">无法加载自测报告</div>
              <div className="font-mono text-xs">{state.error}</div>
            </div>
          ) : (
            <article
              className="self-test-md prose prose-slate max-w-none"
              // The HTML is generated by the backend's `markdown` library
              // from a file the team controls (`自测报告/latest_evaluation_metrics.md`).
              // It is NOT user-supplied content, so the standard React
              // dangerouslySetInnerHTML caveat (XSS via attacker-controlled
              // input) does not apply here.
              dangerouslySetInnerHTML={{ __html: state.html || "" }}
            />
          )}
        </div>

        <p className="text-xs text-slate-400 text-center">
          自测报告由 <code className="bg-slate-100 px-1 py-0.5 rounded">eval/render_official_metrics.py</code>
          从 <code className="bg-slate-100 px-1 py-0.5 rounded">summary.json</code>
          机械导出，所有得分均按既定阈值计算，未做人工调整。
        </p>
      </div>
    </div>
  );
}
