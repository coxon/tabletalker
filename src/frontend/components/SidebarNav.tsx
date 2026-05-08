"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  History,
  Layers,
  PieChart,
  Activity,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/v2", icon: Home, label: "首页", desc: "数据分析" },
  { href: "/v2/history", icon: History, label: "历史记录", desc: "查看所有会话" },
  { href: "/v2/batch", icon: Layers, label: "批量处理", desc: "多文件批量分析" },
  { href: "/v2/reports", icon: PieChart, label: "报告中心", desc: "查看生成报告" },
  { href: "/v2/status", icon: Activity, label: "系统状态", desc: "服务健康与版本" },
];

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav className="flex-1 px-4 space-y-1">
      {NAV_ITEMS.map((item) => {
        const isActive =
          item.href === "/v2"
            ? pathname === "/v2"
            : pathname.startsWith(item.href);

        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
              isActive
                ? "bg-indigo-600 text-white font-medium"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            <item.icon size={18} />
            {item.label}
            <span
              className={`ml-auto text-[10px] ${
                isActive ? "opacity-70" : "text-slate-400"
              }`}
            >
              {item.desc}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
