// `/history` — the 历史分析 page.
//
// This PR (#19) only stands the route up so the primary nav has
// somewhere to point. The real list / detail / filtering / delete UI
// lands in PR #21, against `/v1/sessions` which already exists in the
// backend (PR #18). The placeholder copy is intentionally Restrained —
// no skeleton, no fake data — so demoing the shell doesn't suggest a
// feature that isn't there yet.

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "历史分析 · TableTalker",
  description: "查看你过去发起的分析与追问。",
};

export default function HistoryPage() {
  return (
    <main className="mx-auto flex w-full max-w-[88ch] flex-col gap-6 px-6 py-12">
      <header className="flex flex-col gap-2">
        <h1 className="font-display text-[2rem] italic leading-tight tracking-tight">
          历史分析
        </h1>
        <p className="max-w-[58ch] text-[15px] leading-relaxed text-[--color-fg-muted]">
          这里会列出你过去发起的所有分析会话，可以继续追问、查看报告或删除。
        </p>
      </header>

      <section
        aria-label="占位"
        className="flex flex-col items-start gap-3 rounded-[--radius-md] border border-dashed border-[--color-border-strong] bg-[--color-bg-elev] p-8"
      >
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
          即将上线
        </span>
        <p className="text-sm leading-relaxed text-[--color-fg-muted]">
          列表、详情、筛选与删除会在下一次更新中接入。
          <br />
          后端 <code className="font-mono text-[12.5px]">/v1/sessions</code>{" "}
          接口已就绪。
        </p>
      </section>
    </main>
  );
}
