import type { ReactNode } from "react";
import Link from "next/link";
import { Bot, ClipboardCheck, ExternalLink } from "lucide-react";
import { SidebarNav } from "../../components/SidebarNav";

// The backend probe logic can be moved here or reused. For simplicity, we just
// keep the UI skeleton first.
const BACKEND_URL = process.env.BACKEND_URL ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");
const TIMEOUT_MS = 3000;

async function fetchBackendVersion() {
  if (!BACKEND_URL) return null;
  try {
    const response = await fetch(`${BACKEND_URL}/version`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return null;
    const parsed: any = await response.json();
    return parsed;
  } catch {
    return null;
  }
}

export default async function V2Layout({ children }: { children: ReactNode }) {
  const backend = await fetchBackendVersion();
  const backendOnline = Boolean(backend);

  return (
    <div className="flex h-screen bg-[#F8F9FB] text-slate-800">
      {/* Sidebar */}
      <aside className="w-64 border-r border-slate-200 bg-white flex flex-col">
        {/* Logo Area */}
        <div className="flex items-center gap-2 p-6">
          <div className="bg-indigo-600 rounded p-1.5 text-white">
            <Bot size={24} />
          </div>
          <div className="flex flex-col">
            <span className="font-bold text-lg leading-tight">TableTalker</span>
            <span className="text-[11px] text-slate-500">数据分析智能体</span>
          </div>
        </div>

        {/* Navigation */}
        <SidebarNav />

        {/* Bottom Fast Start */}
        <div className="p-4 m-4 bg-indigo-50 rounded-xl border border-indigo-100">
          <div className="text-indigo-600 mb-2"><Bot size={20} /></div>
          <h4 className="font-semibold text-sm mb-1">快速开始</h4>
          <p className="text-xs text-slate-500 mb-3 leading-relaxed">
            上传数据并提出你的问题，TableTalker 将自动完成分析并生成可验证的报告。
          </p>
          {/* "使用指南" 按钮位已移除 — 原控件是死链接 (CodeRabbit
               finding on PR #21). 使用文档先挂到 README，上线后再考虑
               是否独立 /help 页。 */}
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Header */}
        <header className="h-16 flex items-center justify-between px-8 bg-white border-b border-slate-200 shrink-0">
          <h1 className="text-xl font-bold flex items-center gap-2">
            欢迎使用 <span className="text-indigo-600">TableTalker</span>
          </h1>
          
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 px-3 py-1.5 rounded-full border border-slate-200">
              服务状态 
              <span className="flex items-center gap-1 font-medium text-emerald-600">
                <span className="relative flex h-2 w-2">
                  {backendOnline && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>}
                  <span className={`relative inline-flex rounded-full h-2 w-2 ${backendOnline ? 'bg-emerald-500' : 'bg-rose-500'}`}></span>
                </span>
                {backendOnline ? '健康' : '离线'}
              </span>
            </div>
            
            <a href="/self-test" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-indigo-700 bg-indigo-50 border border-indigo-200 px-3 py-1.5 rounded-md hover:bg-indigo-100 transition-colors font-medium">
              <ClipboardCheck size={14} />
              自测报告
            </a>

            <a href="/docs" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-slate-600 bg-white border border-slate-200 px-3 py-1.5 rounded-md hover:bg-slate-50 transition-colors">
              <ExternalLink size={14} />
              API 文档
            </a>
            
            <div className="flex items-center gap-2 border-l border-slate-200 pl-4">
              <div className="w-8 h-8 rounded-full bg-slate-200 overflow-hidden">
                <img src="https://api.dicebear.com/7.x/notionists/svg?seed=Felix" alt="avatar" className="w-full h-full object-cover" />
              </div>
              <span className="text-sm font-medium">分析师 ⌄</span>
            </div>
          </div>
        </header>

        {/* Scrollable Main Area */}
        <main className="flex-1 overflow-auto p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
