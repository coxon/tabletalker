import type { Metadata } from "next";
import type { ReactNode } from "react";

import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { Newsreader } from "next/font/google";

import { Toaster } from "../components/Toaster";
import { ThemeBoot } from "../components/ThemeBoot";

import "./globals.css";

// Display = Newsreader italic per the brief — used sparingly: wordmark,
// the "拒答" callout, the empty-state hero clause. Loaded with `italic`
// only because that's the only weight we render.
const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["500"],
  style: ["italic"],
  variable: "--font-newsreader",
  display: "swap",
});

export const metadata: Metadata = {
  title: "TableTalker · 数据分析助手",
  description:
    "上传 CSV 或 XLSX 文件并提问，TableTalker 会生成可复现的分析报告。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="zh-CN"
      className={`${GeistSans.variable} ${GeistMono.variable} ${newsreader.variable}`}
      // The `data-theme` attribute is set client-side by ThemeBoot on
      // first paint to match either the persisted preference or the
      // system setting. We deliberately set nothing on the server so a
      // rehydration mismatch can't flash the wrong theme.
      suppressHydrationWarning
    >
      <body className="antialiased">
        <ThemeBoot />
        {children}
        <Toaster />
      </body>
    </html>
  );
}
