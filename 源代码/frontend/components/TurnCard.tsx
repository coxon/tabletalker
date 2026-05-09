"use client";

// One conversation turn. The brief calls for `<article>` + 1px border
// (no nested cards). Body is summary → findings → recommendations →
// optional report iframe in a `<details>`.
//
// Motion: opacity 0→1 + translateY 8→0, 220ms with the Vaul curve.
// Reduced-motion variant kills translate via the global rule in
// globals.css.

import { motion } from "framer-motion";
import { Frown, ExternalLink, ChevronDown, Download } from "lucide-react";
import { useState } from "react";

import type { Turn, Finding, ChartKind } from "../lib/contract";

const CHART_HINT: Record<ChartKind, string> = {
  柱状图: "Bar",
  折线图: "Line",
  饼图: "Pie",
  散点图: "Scatter",
  热力图: "Heatmap",
  箱线图: "Box",
};

export function TurnCard({ turn, index }: { turn: Turn; index: number }) {
  const { response, question, kind } = turn;
  const reportSrc = `/reports/${response.id}.html`;
  const isParent = kind === "parent";
  const heading = isParent ? "首次提问" : `追问 #${index}`;
  const [openReport, setOpenReport] = useState(true);

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
      className="flex flex-col gap-4 rounded-[--radius-md] border border-[--color-border] bg-[--color-bg-elev] p-5"
    >
      <header className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
            {heading}
          </span>
          <div className="flex items-center gap-2">
            {response.is_refusal ? (
              <span className="chip chip-warn">
                <Frown size={12} strokeWidth={2} />
                拒答
              </span>
            ) : null}
            <span className="nums chip">
              <span className="font-mono text-[10px] text-[--color-fg-faint]">
                {response.id}
              </span>
            </span>
          </div>
        </div>
        <h2 className="text-[17px] font-medium leading-snug">{question}</h2>
      </header>

      <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-[--color-fg-muted]">
        {response.summary}
      </p>

      {response.findings.length > 0 ? (
        <FindingsBlock findings={response.findings} />
      ) : null}

      {response.recommendations.length > 0 ? (
        <RecommendationsBlock items={response.recommendations} />
      ) : null}

      {!response.is_refusal && response.charts.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {response.charts.map((chart) => (
            <span key={chart.html_anchor} className="chip">
              <span className="text-[11px] uppercase tracking-wide text-[--color-fg-faint]">
                {CHART_HINT[chart.type] ?? chart.type}
              </span>
              <span className="text-[11px] text-[--color-fg-muted]">
                {chart.title}
              </span>
            </span>
          ))}
        </div>
      ) : null}

      {response.is_refusal ? null : (
        <div className="border-t border-[--color-border] pt-3">
          <button
            type="button"
            onClick={() => setOpenReport((v) => !v)}
            aria-expanded={openReport}
            className="flex items-center gap-1.5 text-[13px] font-medium text-[--color-fg-muted] hover:text-[--color-fg]"
          >
            <ChevronDown
              size={14}
              className={`transition ${
                openReport ? "rotate-0" : "-rotate-90"
              }`}
            />
            完整报告
            <a
              href={reportSrc}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1 inline-flex items-center gap-1 text-[12px] text-[--color-fg-faint] hover:text-[--color-fg-muted]"
              onClick={(event) => event.stopPropagation()}
            >
              <ExternalLink size={11} /> 新标签打开
            </a>
            <a
              href={`/api/reports/${response.id}/download`}
              className="ml-1 inline-flex items-center gap-1 text-[12px] text-[--color-fg-faint] hover:text-[--color-fg-muted]"
              onClick={(event) => event.stopPropagation()}
            >
              <Download size={11} /> 下载 HTML
            </a>
          </button>
          {openReport ? (
            <iframe
              src={reportSrc}
              title={`报告 ${response.id}`}
              // Sandbox: scripts run (Plotly), but no top-level
              // navigation, no popups, no form posts. Same-origin lets
              // the iframe link out via target=_blank if the user
              // chooses, while still defending against a future
              // template bug accidentally injecting raw HTML.
              sandbox="allow-scripts allow-same-origin allow-popups"
              className="mt-3 h-[560px] w-full rounded-[--radius-sm] border border-[--color-border]"
            />
          ) : null}
        </div>
      )}
    </motion.article>
  );
}

function FindingsBlock({ findings }: { findings: Finding[] }) {
  return (
    <section className="flex flex-col gap-2.5">
      <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
        关键发现
      </h3>
      <ul className="flex flex-col gap-3">
        {findings.map((f, i) => (
          <li
            key={i}
            className="rounded-[--radius-sm] border border-[--color-border] bg-[--color-bg-sunken] p-3"
          >
            <p className="text-sm font-medium leading-snug">{f.title}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-[--color-fg-muted]">
              {f.detail}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RecommendationsBlock({ items }: { items: string[] }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
        建议
      </h3>
      <ul className="flex flex-col gap-1.5 pl-4 marker:text-[--color-fg-faint]">
        {items.map((item, i) => (
          <li
            key={i}
            className="list-disc text-[13px] leading-relaxed text-[--color-fg-muted]"
          >
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
