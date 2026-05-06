"use client";

// One-line topbar. Left: wordmark + subtitle. Right: backend health pill
// + ⌘K hint. No nav, no avatar — single-screen app. The wordmark uses
// Newsreader italic to give the brand a single distinctive type
// gesture (emil §Typography, "type does the heavy lifting").

import { useEffect, useState } from "react";
import { CommandIcon, Sun, Moon } from "lucide-react";

interface TopBarProps {
  backendOnline: boolean;
  backendLabel: string;
  onOpenPalette: () => void;
}

export function TopBar({ backendOnline, backendLabel, onOpenPalette }: TopBarProps) {
  // Render theme toggle only after mount — avoids a hydration mismatch
  // (the server can't know what `data-theme` ended up at).
  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    setMounted(true);
    const api = window.__tabletalker_theme;
    if (api) setTheme(api.get());
  }, []);

  const toggleTheme = () => {
    const api = window.__tabletalker_theme;
    if (!api) return;
    api.toggle();
    setTheme(api.get());
  };

  return (
    <header className="sticky top-0 z-30 border-b border-[--color-border] bg-[--color-bg]/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-[88ch] items-center justify-between px-6 py-3.5">
        <div className="flex items-baseline gap-3">
          <span className="font-display text-[1.35rem] leading-none italic">
            TableTalker
          </span>
          <span className="hidden text-xs text-[--color-fg-faint] sm:inline">
            数据分析助手 · 赛题 4
          </span>
        </div>
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
            <span>{backendOnline ? "后端就绪" : "后端不可达"}</span>
          </span>
          {mounted ? (
            <button
              type="button"
              className="btn p-2!"
              aria-label={theme === "dark" ? "切换为浅色模式" : "切换为深色模式"}
              onClick={toggleTheme}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          ) : null}
          <button
            type="button"
            className="btn hidden sm:inline-flex"
            onClick={onOpenPalette}
            aria-label="打开命令面板"
          >
            <CommandIcon size={14} />
            <span className="text-xs text-[--color-fg-muted]">K</span>
          </button>
        </div>
      </div>
    </header>
  );
}
