"use client";

// Minimal cmd+K. The app has exactly two non-trivial actions: theme
// switch + start-fresh. The palette also doubles as the place where
// "新分析" lives so we don't add a kebab button to the header that
// would clutter the chrome.

import { Command } from "cmdk";
import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sun, Moon, RotateCcw } from "lucide-react";

interface PaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResetSession: () => void;
}

export function Palette({ open, onOpenChange, onResetSession }: PaletteProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
      if (event.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
          className="fixed inset-0 z-50 grid place-items-start bg-[--color-bg]/40 px-4 pt-[18vh] backdrop-blur-sm"
          onClick={() => onOpenChange(false)}
        >
          <motion.div
            initial={{ opacity: 0, y: -12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.99 }}
            transition={{ duration: 0.18, ease: [0.32, 0.72, 0, 1] }}
            className="mx-auto w-full max-w-md overflow-hidden rounded-[--radius-md] border border-[--color-border-strong] bg-[--color-bg-elev] shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <Command label="命令面板" className="flex flex-col">
              <Command.Input
                placeholder="搜索命令…"
                className="border-b border-[--color-border] bg-transparent px-4 py-3 text-sm placeholder:text-[--color-fg-faint] focus:outline-none"
              />
              <Command.List className="max-h-[320px] overflow-y-auto p-1.5">
                <Command.Empty className="px-3 py-6 text-center text-sm text-[--color-fg-faint]">
                  没有匹配的命令
                </Command.Empty>
                <Command.Group heading="会话" className="text-xs text-[--color-fg-faint] [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                  <Command.Item
                    value="reset 新分析 重置 重新上传"
                    onSelect={() => {
                      onResetSession();
                      onOpenChange(false);
                    }}
                    className="flex items-center gap-2 rounded-[--radius-sm] px-2.5 py-2 text-sm text-[--color-fg] aria-selected:bg-[--color-bg-sunken]"
                  >
                    <RotateCcw size={14} />
                    新分析（丢弃当前会话）
                  </Command.Item>
                </Command.Group>
                <Command.Group heading="外观" className="text-xs text-[--color-fg-faint] [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                  <Command.Item
                    value="theme light 浅色"
                    onSelect={() => {
                      window.__tabletalker_theme?.set("light");
                      onOpenChange(false);
                    }}
                    className="flex items-center gap-2 rounded-[--radius-sm] px-2.5 py-2 text-sm text-[--color-fg] aria-selected:bg-[--color-bg-sunken]"
                  >
                    <Sun size={14} />
                    浅色模式
                  </Command.Item>
                  <Command.Item
                    value="theme dark 深色"
                    onSelect={() => {
                      window.__tabletalker_theme?.set("dark");
                      onOpenChange(false);
                    }}
                    className="flex items-center gap-2 rounded-[--radius-sm] px-2.5 py-2 text-sm text-[--color-fg] aria-selected:bg-[--color-bg-sunken]"
                  >
                    <Moon size={14} />
                    深色模式
                  </Command.Item>
                </Command.Group>
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
