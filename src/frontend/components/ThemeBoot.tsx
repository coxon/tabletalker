"use client";

// Sets `data-theme` on <html> as early as possible to avoid a
// light-mode flash for users who prefer dark. Two stages:
//   1. An inline script that runs before React hydrates (the
//      "boot script"), reading `localStorage` then the system `prefers-color-scheme`.
//   2. A React effect that updates the attribute when the user toggles
//      from the command palette.
//
// We expose `setTheme` on `window.__tabletalker_theme` so the command
// palette doesn't need to import this file (avoids a hydration cycle).

import { useEffect } from "react";

const BOOT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem('tabletalker:theme');
    var theme = stored || (
      window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    );
    document.documentElement.setAttribute('data-theme', theme);
  } catch (_) {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();
`;

declare global {
  interface Window {
    __tabletalker_theme?: {
      get: () => "light" | "dark";
      set: (next: "light" | "dark") => void;
      toggle: () => void;
    };
  }
}

export function ThemeBoot() {
  useEffect(() => {
    const get = (): "light" | "dark" => {
      const v = document.documentElement.getAttribute("data-theme");
      return v === "dark" ? "dark" : "light";
    };
    const set = (next: "light" | "dark") => {
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem("tabletalker:theme", next);
      } catch {
        // localStorage can throw in private mode; fall through silently —
        // the attribute is already set so the UI is correct.
      }
    };
    window.__tabletalker_theme = {
      get,
      set,
      toggle: () => set(get() === "dark" ? "light" : "dark"),
    };
  }, []);

  return (
    <script
      // Inline script runs on first paint; setting innerHTML is the
      // standard Next idiom for this — it doesn't bypass any framework
      // safety because the content is a string literal.
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: BOOT_SCRIPT }}
    />
  );
}
