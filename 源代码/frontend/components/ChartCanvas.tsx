"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";

/**
 * Inline ECharts canvas — used by AssistantMessage to render the
 * primary chart of a turn directly in the chat thread instead of
 * forcing the user into the report side-panel.
 *
 * Only the first chart per turn ships an `echarts_option` from the
 * backend (see `源代码/backend/app/report/render.py`); subsequent
 * charts stay accessible via the "完整报告" button. Keeping it to
 * one chart matches the claude.ai "single hero artefact" pattern.
 *
 * Lifecycle:
 *   - Init the chart on mount, dispose on unmount.
 *   - Re-apply option only when the JSON string actually changes
 *     (referential equality is enough — the parent always passes
 *     the same response object until a new turn appears).
 *   - ResizeObserver tracks container resize (sidebar collapse /
 *     window resize) and forwards to ECharts; without it the chart
 *     would render at the initial width forever.
 */
export function ChartCanvas({
  optionJson,
  className = "w-full h-[320px]",
}: {
  optionJson: string;
  className?: string;
}) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const chart = echarts.init(el);
    chartRef.current = chart;
    const resizer = new ResizeObserver(() => chart.resize());
    resizer.observe(el);
    return () => {
      resizer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !optionJson) return;
    try {
      const option = JSON.parse(optionJson) as echarts.EChartsCoreOption;
      chart.setOption(option, /* notMerge */ true);
    } catch (err) {
      // Bad JSON shouldn't crash the chat — log and bail. The full
      // report iframe is still reachable from the "完整报告" button.
      console.error("ChartCanvas: invalid echarts_option", err);
    }
  }, [optionJson]);

  return <div ref={elRef} className={className} />;
}
