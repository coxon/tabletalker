"use client";

import { useEffect, useState } from "react";
import { Frown, History, MessageSquare } from "lucide-react";
import type { SessionListOut, SessionSummaryOut } from "../lib/sessions";

/**
 * Sidebar history rail — top N recent sessions inline in the left
 * column. Clicking a row navigates to `/?session=<id>` so the
 * existing main-page hydration effect picks up the resume flow.
 *
 * The middle column (the chat thread) stays put. Without this
 * component the user had to leave the chat to /history just to
 * remember which conversation to resume; collapsing the list into
 * the sidebar mirrors claude.ai's chat list and removes that round
 * trip.
 *
 * Polls the underlying /api/sessions endpoint on mount only —
 * mid-session updates land via a hard reload (the "新会话" button
 * already does this); a websocket / event-source for live updates
 * isn't worth the complexity for the demo.
 */
// All sessions live here now (rail is scrollable since /history was
// removed). Cap at a sane upper bound to avoid pulling the entire
// table on every layout mount; 100 is more than enough for the demo.
const ITEM_LIMIT = 100;

export function HistoryRail() {
  const [items, setItems] = useState<SessionSummaryOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/api/sessions?limit=${ITEM_LIMIT}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = (await response.json()) as SessionListOut;
        if (!cancelled) setItems(body.items.slice(0, ITEM_LIMIT));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "未知错误");
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const onPick = (id: string) => {
    // Hard navigate — same pattern as "新会话". The main page's mount
    // effect handles `?session=<id>` and runs the resume API call.
    try {
      window.localStorage.removeItem("tabletalker:session:v1");
    } catch {}
    window.location.assign(`/?session=${encodeURIComponent(id)}`);
  };

  return (
    <div className="px-4 pt-6 pb-4 flex-1 min-h-0 overflow-y-auto">
      <div className="text-[12px] font-semibold text-stone-500 flex items-center gap-1.5 mb-2 px-3">
        <History size={13} />
        历史会话
      </div>

      {items === null && error === null && (
        <div className="text-[12px] text-stone-400 py-2 px-3">加载中...</div>
      )}

      {error !== null && (
        <div className="text-[12px] text-rose-500 py-2 px-3">加载失败</div>
      )}

      {items !== null && items.length === 0 && (
        <div className="text-[12px] text-stone-400 py-2 px-3 flex items-center gap-1.5">
          <MessageSquare size={12} />
          还没有会话
        </div>
      )}

      {items !== null && items.length > 0 && (
        <ul className="space-y-px">
          {items.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onPick(s.id)}
                className="w-full text-left px-3 py-1.5 rounded-md hover:bg-stone-100 transition-colors group flex items-center gap-1.5"
                title={`${s.title} · ${s.primary_filename}${s.follow_up_count > 0 ? ` · +${s.follow_up_count} 轮追问` : ""}`}
              >
                {s.is_refusal && (
                  <Frown size={11} className="text-rose-400 shrink-0" />
                )}
                <span className="text-[13px] text-stone-700 truncate flex-1 min-w-0 group-hover:text-stone-900">
                  {s.title}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
