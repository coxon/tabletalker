"use client";

import { usePathname } from "next/navigation";
import {
  Layers,
  PieChart,
  Plus,
} from "lucide-react";

// `新会话` deliberately does a hard navigation (not Next.js soft routing)
// so that clicking it always wipes the in-page React state — turns,
// pendingQuestion, files, livePartial, etc. — and lands on a fresh
// chat page even when the user is already on "/". Soft `<Link>` would
// just no-op in that case.
//
// History gets its own dedicated rail (HistoryRail) below the nav so
// users see their recent sessions without leaving the chat. The full
// list lives at /history but isn't a primary nav entry anymore.
const NAV_ITEMS = [
  { href: "/", icon: Plus, label: "新会话", desc: "开始一段新对话", reload: true },
  { href: "/batch", icon: Layers, label: "批量处理", desc: "多文件批量分析" },
  { href: "/reports", icon: PieChart, label: "报告中心", desc: "查看生成报告" },
];

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav className="px-4 space-y-1">
      {NAV_ITEMS.map((item) => {
        // Exact match or strict child path (`/reports` must not match
        // `/reports-archive`). CodeRabbit finding on PR #21: bare
        // `pathname.startsWith(item.href)` false-matched same-prefix
        // siblings — e.g. a future `/reports-snapshot` route would
        // light the `/reports` nav item.
        const isActive =
          !item.reload && (
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href + "/"))
          );

        const cls = `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
          isActive
            ? "bg-indigo-600 text-white font-medium"
            : "text-stone-600 hover:bg-stone-100"
        }`;

        const inner = (
          <>
            <item.icon size={18} />
            {item.label}
            <span
              className={`ml-auto text-[10px] ${
                isActive ? "opacity-70" : "text-stone-400"
              }`}
            >
              {item.desc}
            </span>
          </>
        );

        // 新会话 forces a hard navigation so React state on `/` resets.
        if (item.reload) {
          return (
            <button
              key={item.href}
              type="button"
              onClick={() => {
                // Wipe persisted thread so the page mounts truly empty.
                // Without this, the localStorage useEffect in page.tsx
                // re-hydrates the previous turns immediately after the
                // hard reload, defeating "new chat".
                try {
                  window.localStorage.removeItem("tabletalker:session:v1");
                } catch {}
                window.location.assign(item.href);
              }}
              className={cls + " w-full text-left"}
            >
              {inner}
            </button>
          );
        }

        return (
          <a key={item.href} href={item.href} className={cls}>
            {inner}
          </a>
        );
      })}
    </nav>
  );
}
