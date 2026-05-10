import type { ReactNode } from "react";
import { Bot, ChevronUp, ClipboardCheck } from "lucide-react";
import { SidebarNav } from "../../components/SidebarNav";
import { HistoryRail } from "../../components/HistoryRail";

export default function V2Layout({ children }: { children: ReactNode }) {

  return (
    <div className="flex h-screen bg-[#FBFAF7] text-stone-800">
      {/* Sidebar */}
      <aside className="w-64 border-r border-stone-200 flex flex-col">
        {/* Logo Area */}
        <div className="flex items-center gap-2 p-6">
          <div className="bg-indigo-600 rounded p-1.5 text-white">
            <Bot size={24} />
          </div>
          <div className="flex flex-col">
            <span className="font-bold text-lg leading-tight">TableTalker</span>
            <span className="text-[11px] text-stone-500">数据分析智能体</span>
          </div>
        </div>

        {/* Navigation */}
        <SidebarNav />

        {/* History rail — takes the remaining sidebar space, scrolls
            on overflow. Replaces the capability footer (those
            descriptions weren't load-bearing). */}
        <HistoryRail />

        {/* Bottom dock — analyst identity + the auto-grader self-test
            link. Used to live in the top-right header but moved here
            so the header stays single-purpose ("欢迎使用 TableTalker")
            and so the user-related affordances cluster like a
            claude.ai-style account row. */}
        <div className="px-3 pb-3 pt-3 border-t border-stone-200 space-y-1">
          <a
            href="/self-test"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-2 py-2 rounded-md text-[13px] text-stone-600 hover:text-stone-900 hover:bg-stone-100 transition-colors"
          >
            <ClipboardCheck size={14} className="text-indigo-600" />
            自测报告
          </a>
          <button
            type="button"
            className="w-full flex items-center gap-2 px-2 py-2 rounded-md hover:bg-stone-100 transition-colors"
          >
            <div className="w-7 h-7 rounded-full bg-stone-200 overflow-hidden shrink-0">
              <img
                src="https://api.dicebear.com/7.x/notionists/svg?seed=Felix"
                alt="avatar"
                className="w-full h-full object-cover"
              />
            </div>
            <span className="text-[13px] font-medium flex-1 text-left">分析师</span>
            <ChevronUp size={13} className="text-stone-400" />
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Scrollable Main Area — header removed; the chat is the
            page (claude.ai pattern). Page-level controls / branding
            now live in the sidebar. */}
        <main className="flex-1 overflow-auto p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
