"use client";

// Sticky top chrome shared by every page in the `(shell)` route group.
// Three things, left to right:
//
//   1. Wordmark + subtitle. Newsreader italic on "TableTalker" stays the
//      single distinctive type gesture (emil §Typography). Subtitle
//      collapses below `sm` so the bar still fits a phone.
//
//   2. Primary nav. Two tabs ("提问分析", "历史分析"). Active tab is
//      derived from `usePathname()` rather than driven by props so we
//      stay in lockstep with the URL on browser back/forward — no
//      "active=true while route already swapped" jank. The link uses
//      Next's `<Link>` (prefetch on hover) so swaps feel instant.
//
//   3. Backend pill + theme toggle. The backend probe is owned by the
//      server-rendered shell layout above us; we just receive the
//      booleaned health here so the pill paints once on first paint.
//
// The cmd+K command palette button used to live here. It moved out
// because (a) the Palette is currently only mounted on /analyze, so a
// button on /history would be a dead lure, and (b) the keyboard hotkey
// itself still works globally via Palette's own listener — no
// discoverability button needed at this size.

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sun, Moon } from "lucide-react";

interface TopBarProps {
  backendOnline: boolean;
  backendLabel: string;
}

interface NavItem {
  href: string;
  label: string;
}

// Two tabs — kept inline (rather than imported from a config file)
// because we want a code-search hit to land on something obvious when
// someone wonders "where do I add a third tab?". The order here is the
// render order; the active state is derived from the URL.
const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: "提问分析" },
  { href: "/history", label: "历史分析" },
] as const;

function isActive(pathname: string, href: string): boolean {
  // `/` matches only itself — `startsWith` would let it claim every
  // route. Other tabs match prefix so `/history/<id>` (a future detail
  // page) keeps "历史分析" highlighted.
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function TopBar({ backendOnline, backendLabel }: TopBarProps) {
  // Render theme toggle only after mount — avoids a hydration mismatch
  // (the server can't know what `data-theme` ended up at).
  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    setMounted(true);
    const api = window.__tabletalker_theme;
    if (api) setTheme(api.get());
  }, []);

  const pathname = usePathname() ?? "/";

  const toggleTheme = () => {
    const api = window.__tabletalker_theme;
    if (!api) return;
    api.toggle();
    setTheme(api.get());
  };

  return (
    <header className="sticky top-0 z-30 border-b border-[--color-border] bg-[--color-bg]/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-[88ch] items-center justify-between gap-4 px-6 py-3.5">
        <div className="flex items-baseline gap-3">
          <Link
            href="/"
            className="font-display text-[1.35rem] leading-none italic"
            aria-label="TableTalker · 回到提问分析"
          >
            TableTalker
          </Link>
          <span className="hidden text-xs text-[--color-fg-faint] sm:inline">
            数据分析助手 · 赛题 4
          </span>
        </div>

        <nav
          aria-label="主导航"
          className="flex items-center gap-0.5 rounded-[--radius-sm] border border-[--color-border] bg-[--color-bg-elev] p-0.5"
        >
          {NAV_ITEMS.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                // Active uses the same `btn-primary` token chord as the
                // primary CTA so brand-weight is consistent across the
                // app; idle is plain text on the elevated panel
                // background. Underline avoidance is deliberate — the
                // pill background is the indicator.
                className={
                  active
                    ? "rounded-[calc(var(--radius-sm)-2px)] bg-[--color-fg] px-3 py-1.5 text-[13px] font-medium text-[--color-bg] transition-colors"
                    : "rounded-[calc(var(--radius-sm)-2px)] px-3 py-1.5 text-[13px] font-medium text-[--color-fg-muted] transition-colors hover:text-[--color-fg]"
                }
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          <span
            className="chip nums"
            title={backendLabel}
            // Animated dot — opacity-pulses when offline so a degraded
            // backend visually nags. Stays static when online; we
            // deliberately don't animate ready states (emil "motion has
            // meaning").
          >
            <span
              aria-hidden
              className={`inline-block size-1.5 rounded-full ${
                backendOnline
                  ? "bg-[--color-accent]"
                  : "bg-[--color-danger] animate-pulse"
              }`}
            />
            <span className="hidden sm:inline">
              {backendOnline ? "后端就绪" : "后端不可达"}
            </span>
          </span>
          {mounted ? (
            <button
              type="button"
              className="btn p-2!"
              aria-label={
                theme === "dark" ? "切换为浅色模式" : "切换为深色模式"
              }
              onClick={toggleTheme}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
