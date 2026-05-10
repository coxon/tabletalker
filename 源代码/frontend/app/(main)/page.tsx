"use client";

import { useState, useRef, useEffect, useLayoutEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import {
  ArrowUp,
  UploadCloud,
  FileSpreadsheet,
  X,
  Play,
  Activity,
  CheckCircle2,
  Clock,
  ExternalLink,
  Download,
  ChevronRight,
  Sparkles,
  ShieldCheck,
  BarChart3,
  MessageSquare,
  Plus,
  Send,
  Frown,
  ChevronDown
} from "lucide-react";
import type {
  AnalyzeResponse,
  Turn,
  AnalyzePhase,
  StageState,
  StreamEvent,
} from "../../lib/contract";
import { applyStageEvent, initialStageStates } from "../../lib/contract";
import { StageTimeline } from "../../components/StageTimeline";
import { ChartCanvas } from "../../components/ChartCanvas";

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? body.error ?? response.statusText;
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

export default function V2AnalyzePage() {
  const [files, setFiles] = useState<File[]>([]);
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<AnalyzePhase>({ name: "idle" });
  const [turns, setTurns] = useState<Turn[]>([]);
  // The question that's currently in-flight. claude.ai-style, we pin
  // the user's question as a chat bubble at the bottom of the thread
  // the moment they hit submit, even though the response (and the
  // resulting `Turn`) won't land until the stream finishes. When the
  // stream lands, the turn is appended to `turns` and this clears.
  const [pendingQuestion, setPendingQuestion] = useState<string>("");
  // Page-level "client has mounted" gate. We hide the entire main
  // column until both:
  //   1. mounted is true (avoids SSR/CSR hydration mismatches that come
  //      from reading `window.location` / `localStorage` during render);
  //   2. `hydrating` flips to false (the ?session=<id> resume API
  //      finished, or there was no resume to do, or localStorage
  //      restore finished).
  // The combination eliminates the hero flash between hard reload and
  // first useEffect tick.
  const [mounted, setMounted] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const [stages, setStages] = useState<StageState[]>(initialStageStates());
  // Live summary text accumulated from `partial` stream events while
  // `finalize_llm` is mid-flight. We render this under the StageTimeline
  // so the user sees the summary growing token-by-token instead of
  // staring at a silent "正在生成结论摘要" spinner for 10-15 s. Cleared
  // when the next analyze starts (and again when `result` arrives,
  // since the full TurnCard takes over from there).
  const [livePartial, setLivePartial] = useState("");
  // Op chips fed by the planner's streaming JSON — one entry per
  // `"kind": "..."` the LLM emits, in declaration order. Cleared on
  // each new analyze/follow-up. Survives past `done` so the completed
  // plan stays visible alongside the StageTimeline.
  const [planOps, setPlanOps] = useState<string[]>([]);
  // Findings + recommendations as they stream in element-by-element
  // from the finalize LLM. The backend `_FindingsArrayEmitter` /
  // `_RecommendationsArrayEmitter` push one `partial` event per
  // closed JSON brace; we accumulate them here so the SPA can fade
  // each finding/rec into the live preview block instead of having
  // them all pop in at the moment `result` lands.
  const [liveFindings, setLiveFindings] = useState<Array<{ title: string; detail: string }>>([]);
  const [liveRecommendations, setLiveRecommendations] = useState<string[]>([]);
  const stagesRef = useRef<StageState[]>(initialStageStates());
  const livePartialRef = useRef("");
  const planOpsRef = useRef<string[]>([]);
  const liveFindingsRef = useRef<Array<{ title: string; detail: string }>>([]);
  const liveRecommendationsRef = useRef<string[]>([]);
  // ID of the report currently shown in the right-side panel. `null`
  // means no panel open. Lifted to page level so the panel can be a
  // single overlay rendered once at the root, regardless of which
  // turn's button was clicked.
  const [reportPanelId, setReportPanelId] = useState<string | null>(null);
  // Time-of-day greeting in the hero. Initial value "你好" avoids
  // server/client hydration mismatch (server doesn't know the user's
  // wall clock); the real greeting fills in on mount.
  const [greeting, setGreeting] = useState("你好");
  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(
      h < 5 ? "夜深了"
      : h < 11 ? "早上好"
      : h < 13 ? "中午好"
      : h < 18 ? "下午好"
      : "晚上好"
    );
  }, []);

  // ─── localStorage persistence ──────────────────────────────────────
  // Survives a browser refresh. We persist:
  //   * `turns` — the full conversation transcript (responses + per-turn
  //     metadata: stage snapshot, plan ops, attached file meta). After
  //     refresh, follow-ups still work because the backend session is
  //     keyed by `parent_id` (the latest turn's response id), which is
  //     in the persisted turn.
  //   * `question` — whatever the user was typing when they refreshed.
  // We do NOT persist `files` (File objects don't serialize), the live
  // stream state (`stages` / `livePartial` / `planOps` / `phase`), or
  // `pendingQuestion`. Those are in-flight state; if the page reloads
  // mid-stream the request is gone anyway.
  const STORAGE_KEY = "tabletalker:session:v1";
  useEffect(() => {
    setMounted(true);
    // Path A: explicit ?session=<id> in the URL → resume from backend
    // history. This wins over localStorage; the user clicked a row in
    // the history list expecting THAT conversation, not whatever
    // happened to be in localStorage from a different chat.
    const url = new URL(window.location.href);
    const wantSession = url.searchParams.get("session");
    if (wantSession) {
      void hydrateFromHistory(wantSession);
      return;
    }
    // Path B: resume the localStorage-persisted thread (last refresh).
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        setHydrating(false);
        return;
      }
      const parsed = JSON.parse(raw) as { turns?: Turn[]; question?: string };
      if (Array.isArray(parsed.turns) && parsed.turns.length > 0) {
        setTurns(parsed.turns);
      }
      if (typeof parsed.question === "string") {
        setQuestion(parsed.question);
      }
    } catch {
      // Corrupt entry — nuke it so we don't keep failing on every load.
      try { localStorage.removeItem(STORAGE_KEY); } catch {}
    } finally {
      setHydrating(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pull the durable session detail + bind it back into the in-memory
  // SESSION_STORE on the backend, then convert the history-row turns
  // into the frontend Turn[] shape so the thread renders. Best-effort:
  // any failure here surfaces as a toast; the user can always start a
  // new conversation. The query param is wiped after either branch so
  // a refresh of the chat doesn't re-trigger the resume cycle.
  const hydrateFromHistory = async (sessionId: string) => {
    try {
      // GET detail + POST resume in parallel — neither depends on the
      // other (resume only mutates server state, detail is a pure
      // read).
      const [detailRes, resumeRes] = await Promise.all([
        fetch(`/api/sessions/${sessionId}`),
        fetch(`/api/sessions/${sessionId}/resume`, { method: "POST" }),
      ]);
      if (!detailRes.ok) {
        toast.error("无法加载历史会话", { description: `HTTP ${detailRes.status}` });
        cleanQueryParam();
        return;
      }
      if (!resumeRes.ok) {
        // 410 = workspace gone; 404 = no state JSON. Both mean we can
        // SHOW the past turns but follow-up will fail until the user
        // starts a new conversation. Surface that explicitly.
        toast.warning("会话只能查看，不能继续追问", {
          description:
            resumeRes.status === 410
              ? "这是更早部署留下的历史会话，原始数据集已不可用。"
              : "这条会话缺少续聊所需的内部状态。",
        });
      }
      const detail = (await detailRes.json()) as {
        primary_filename: string;
        turns: Array<{
          turn_index: number;
          kind: "parent" | "follow_up";
          question: string;
          response_id: string;
          is_refusal: boolean;
          summary: string;
          finding_count: number;
          chart_count: number;
        }>;
      };
      // Synthesise minimal AnalyzeResponse objects so AssistantMessage
      // renders. Findings/charts/recommendations aren't persisted in
      // session_turns (only counts), so resumed turns show summary +
      // a "完整报告" button (driven by chart_count > 0). Clicking the
      // button hits /reports/<id>.html which the disk-spilled
      // REPORT_STORE serves intact — no degradation for the report
      // viewer.
      const hydratedTurns: Turn[] = detail.turns.map((t) => ({
        question: t.question,
        kind: t.kind,
        response: {
          id: t.response_id,
          report_html_url: `/reports/${t.response_id}.html`,
          summary: t.summary,
          findings: [],
          charts:
            t.chart_count > 0
              ? Array.from({ length: t.chart_count }, (_, i) => ({
                  type: "柱状图" as const,
                  title: "",
                  html_anchor: `chart-${i}`,
                }))
              : [],
          recommendations: [],
          is_refusal: t.is_refusal,
        },
        attachedFiles:
          t.kind === "parent"
            ? [{ name: detail.primary_filename, size: 0 }]
            : undefined,
      }));
      setTurns(hydratedTurns);
      setQuestion("");
      cleanQueryParam();
    } catch (err) {
      const message = err instanceof Error ? err.message : "未知错误";
      toast.error("加载历史会话失败", { description: message });
      cleanQueryParam();
    } finally {
      setHydrating(false);
    }
  };

  const cleanQueryParam = () => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (url.searchParams.has("session")) {
      url.searchParams.delete("session");
      window.history.replaceState({}, "", url.toString());
    }
  };
  useEffect(() => {
    try {
      // Empty thread + empty question → drop the entry entirely so a
      // future refresh starts clean rather than seeing a 0-byte payload.
      if (turns.length === 0 && question === "") {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ turns, question }));
    } catch {
      // Quota exceeded / private mode — best-effort persistence, drop
      // silently. Main UX still works in-memory.
    }
  }, [turns, question]);
  // ────────────────────────────────────────────────────────────────────

  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Anchor at the just-submitted user bubble. On submit we scroll the
  // bubble to the TOP of the scroll area so the previous turn gets
  // pushed off-screen above.
  //
  // What makes the scroll land the bubble at the top even when the
  // previous turn is short: the pending bubble has a min-height of
  // ~viewport-minus-composer (see JSX). That guarantees enough
  // scrollable content below the bubble for
  // `scrollIntoView({ block: "start" })` to succeed.
  //
  // Previously the min-height was removed because it LOOKED like
  // streaming was stalling (empty area below the StageTimeline).
  // Once the real cause of that — `chat_stream` silently regressing
  // to non-streaming `chat()` on `model.asiainfo.com` — was fixed
  // in `llm.py`, per-token tokens and per-element findings fill the
  // bubble as they arrive, so the empty-area phase is now ≤ 1 s.
  //
  // `useLayoutEffect` runs synchronously after DOM commit but before
  // paint, so the viewport never flashes the pre-scroll layout.
  // `behavior: "auto"` (instant) — a smooth animation would fight
  // React's per-token re-renders during streaming.
  const pendingBubbleRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!pendingQuestion) return;
    pendingBubbleRef.current?.scrollIntoView({
      behavior: "auto",
      block: "start",
    });
  }, [pendingQuestion]);

  // Auto-follow the bottom of the pending bubble while it streams.
  // Without this, once enough findings / summary / recommendations have
  // arrived the bubble's bottom slides behind the sticky composer and
  // the user can't see new tokens until they scroll manually. We watch
  // the stream-driven state and, whenever the bubble's bottom drifts
  // past the composer's top, nudge `scrollTop` just enough to restore
  // the bubble bottom to a visible position with a small margin.
  //
  // Scroll is only applied when content has ACTUALLY overflowed the
  // safe zone — if the user scrolled up manually to re-read earlier
  // output, `overflow` is already negative and we leave them alone.
  useLayoutEffect(() => {
    if (!pendingQuestion) return;
    const bubble = pendingBubbleRef.current;
    if (!bubble) return;
    const scroller = bubble.closest("main");
    if (!scroller) return;
    const bubbleRect = bubble.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    // Composer is sticky-bottom (see JSX: `sticky bottom-0 ... pt-3 pb-4`).
    // Anything past `scrollerRect.bottom - COMPOSER_HEIGHT` is hidden
    // behind it. Height measured empirically: 2 lines of placeholder +
    // the file-picker row + the pt-3/pb-4 padding ≈ 160 px.
    const COMPOSER_HEIGHT = 176;
    const safeBottom = scrollerRect.bottom - COMPOSER_HEIGHT;
    const overflow = bubbleRect.bottom - safeBottom;
    if (overflow > 0) {
      scroller.scrollTop += overflow + 8;
    }
    // Depend on the stream-driven state. Each new finding, each chunk
    // of summary text, each stage transition nudges this re-check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion, livePartial, liveFindings.length, liveRecommendations.length, stages]);

  // Pick a suggested follow-up: drop the text into the composer AND
  // move focus there. Without the focus jump, the chip keeps focus
  // (annoying ring + Enter would re-fire onClick). RAF defers focus
  // until after React applies the state change so the caret lands at
  // the end of the freshly-written value, not the empty pre-render
  // textarea.
  const pickQuestion = (q: string) => {
    setQuestion(q);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      const len = el.value.length;
      el.setSelectionRange(len, len);
    });
  };

  const resetProgress = () => {
    const initial = initialStageStates();
    stagesRef.current = initial;
    livePartialRef.current = "";
    planOpsRef.current = [];
    liveFindingsRef.current = [];
    liveRecommendationsRef.current = [];
    setStages(initial);
    setLivePartial("");
    setPlanOps([]);
    setLiveFindings([]);
    setLiveRecommendations([]);
  };

  const applyLiveStageEvent = (event: Extract<StreamEvent, { type: "stage" }>) => {
    // Compute next from the ref directly so the ref is updated
    // SYNCHRONOUSLY when this function returns. Going through
    // `setStages(prev => ...)` defers the updater until React's
    // next render commit (React 18 batching), which means a
    // subsequent `stagesRef.current` read inside the same tick
    // (e.g. when result lands and we snapshot stages onto the
    // new Turn) sees stale state — the most recent stage event
    // gets lost from the per-turn snapshot.
    const next = applyStageEvent(stagesRef.current, event);
    stagesRef.current = next;
    setStages(next);
  };

  const appendLiveSummary = (delta: string) => {
    livePartialRef.current += delta;
    setLivePartial(livePartialRef.current);
  };

  const appendPlanOp = (kind: string) => {
    planOpsRef.current = [...planOpsRef.current, kind];
    setPlanOps(planOpsRef.current);
  };

  const appendLiveFinding = (value: { title: string; detail: string }) => {
    liveFindingsRef.current = [...liveFindingsRef.current, value];
    setLiveFindings(liveFindingsRef.current);
  };

  const appendLiveRecommendation = (text: string) => {
    liveRecommendationsRef.current = [...liveRecommendationsRef.current, text];
    setLiveRecommendations(liveRecommendationsRef.current);
  };

  const isBusy = phase.name === "uploading" || phase.name === "analyzing" || phase.name === "follow_up";
  // Original analysis drives UI-level checks: "has anything been analyzed
  // yet?", "was the first turn refused?" (if so all follow-ups are
  // refused too, per docs/refusal-policy.md). The id used for the next
  // follow-up is a SEPARATE concept — see `followUpParentId` below —
  // because /v1/follow-up needs to chain onto the most recent response
  // to carry findings / cohorts / chart anchors forward. Using turns[0]
  // for the follow-up parent_id dropped multi-turn context on the
  // second + subsequent follow-ups (CodeRabbit finding on PR #21).
  const parent = turns[0]?.response ?? null;
  const followUpParentId = turns[turns.length - 1]?.response?.id ?? null;

  // Filter + dedup helper for both drop and pick. We keep the first
  // file added under each name so a re-pick of the same file (a common
  // pattern when correcting a typo in the filename) doesn't silently
  // shadow the original entry. CSV / XLSX gating mirrors the dropzone
  // copy ("仅支持 CSV / Excel").
  const addFiles = (incoming: File[]) => {
    if (incoming.length === 0) return;
    const accepted: File[] = [];
    let rejected = 0;
    for (const f of incoming) {
      const lower = f.name.toLowerCase();
      if (!lower.endsWith(".csv") && !lower.endsWith(".xlsx") && !lower.endsWith(".xls")) {
        rejected += 1;
        continue;
      }
      accepted.push(f);
    }
    if (rejected > 0) {
      toast.error(`已忽略 ${rejected} 个非 CSV/Excel 文件`);
    }
    if (accepted.length === 0) return;
    setFiles((prev) => {
      // Dedup by (name, size, lastModified). (name, size) alone collides
      // on real-world batch exports — a folder of 10 same-size shards or
      // two `customers.csv` from different directories share both fields,
      // and the second drop would silently disappear. lastModified is
      // millisecond-precise so the chance of a true match across distinct
      // files is negligible.
      const keyOf = (f: File) => `${f.name}::${f.size}::${f.lastModified}`;
      const seen = new Set(prev.map(keyOf));
      const merged = [...prev];
      for (const f of accepted) {
        const key = keyOf(f);
        if (!seen.has(key)) {
          merged.push(f);
          seen.add(key);
        }
      }
      return merged;
    });
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (disabled) return;
    addFiles(Array.from(e.dataTransfer.files));
  };

  // ─── Full-screen drop overlay ──────────────────────────────────────
  // claude.ai pattern: as soon as the user drags any file ANYWHERE
  // over the window, the page dims and a centred "drop here" target
  // appears. Drop on it (or anywhere on the dim) lands the files in
  // the same `addFiles` we use for the +-button picker. We use a
  // dragenter/dragleave counter rather than a single boolean because
  // crossing into a child element fires `dragleave` on the parent and
  // `dragenter` on the child in the same tick — naive boolean state
  // would flicker.
  const [dragOverlay, setDragOverlay] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    let depth = 0;
    const isFileDrag = (e: DragEvent) =>
      Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const onEnter = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      depth += 1;
      if (depth === 1) setDragOverlay(true);
    };
    const onLeave = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragOverlay(false);
    };
    const onOver = (e: DragEvent) => {
      // Required so the OS treats us as a drop target.
      if (isFileDrag(e)) e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      depth = 0;
      setDragOverlay(false);
      if (isBusy) return;
      const dropped = Array.from(e.dataTransfer?.files ?? []);
      addFiles(dropped);
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
    // `addFiles` is stable enough via React closure; isBusy retriggers
    // the bind so dropped files during in-flight requests are ignored.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isBusy]);
  // ───────────────────────────────────────────────────────────────────

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(e.target.files ?? []));
    // Reset the input so picking the same filename again still fires
    // onChange (browsers suppress the event if `value` doesn't change).
    e.target.value = "";
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const resetSession = () => {
    setTurns([]);
    setFiles([]);
    setQuestion("");
    setPendingQuestion("");
    resetProgress();
    setPhase({ name: "idle" });
  };

  const submitAnalysis = async () => {
    if (files.length === 0) {
      toast.error("请选择一个 CSV/XLSX 文件");
      return;
    }
    const trimmed = question.trim();
    if (!trimmed) {
      toast.error("请输入一个问题");
      return;
    }

    setPhase({ name: "uploading" });
    resetProgress();
    setPendingQuestion(trimmed);
    setQuestion("");
    const form = new FormData();
    // Backend treats the first file as the primary table (analyzer
    // entry point); auxiliaries land under `extra_files` and the
    // planner is told it can join them on shared keys. See
    // `源代码/backend/app/api/analyze.py::analyze`.
    const [primary, ...extras] = files;
    form.append("file", primary);
    for (const extra of extras) {
      form.append("extra_files", extra);
    }
    form.append("question", trimmed);

    try {
      setPhase({ name: "analyzing" });
      const response = await fetch("/api/analyze/stream", {
        method: "POST",
        body: form,
      });
      if (!response.ok || !response.body) {
        const message = await readError(response);
        setPhase({ name: "error", message });
        toast.error("分析失败", { description: message });
        return;
      }

      // NDJSON stream reader. Each `\n`-terminated line is one event.
      // We accumulate bytes in a TextDecoder buffer and split on every
      // newline; the last fragment may be partial and stays in the
      // buffer for the next iteration. The terminal event is either
      // `result` (success) or `error` (handler-side failure).
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let parsed: AnalyzeResponse | null = null;
      let streamError: { status: number; detail: string } | null = null;

      while (true) {
        const { value, done } = await reader.read();
        if (value) {
          buffer += decoder.decode(value, { stream: !done });
          let nl: number;
          while ((nl = buffer.indexOf("\n")) !== -1) {
            const line = buffer.slice(0, nl).trim();
            buffer = buffer.slice(nl + 1);
            if (!line) continue;
            let event: StreamEvent;
            try {
              event = JSON.parse(line) as StreamEvent;
            } catch {
              // A malformed line shouldn't kill the stream — just
              // skip it. The backend always emits one JSON per line.
              continue;
            }
            if (event.type === "stage") {
              applyLiveStageEvent(event);
            } else if (event.type === "partial") {
              if (event.field === "summary" && event.delta) {
                appendLiveSummary(event.delta);
              } else if (event.field === "plan_op" && event.kind) {
                appendPlanOp(event.kind);
              } else if (event.field === "finding" && event.value) {
                appendLiveFinding(event.value);
              } else if (event.field === "recommendation" && event.text) {
                appendLiveRecommendation(event.text);
              }
            } else if (event.type === "result") {
              parsed = event.data;
            } else if (event.type === "error") {
              streamError = { status: event.status, detail: event.detail };
            }
          }
        }
        if (done) break;
      }

      if (streamError) {
        setPhase({ name: "error", message: streamError.detail });
        setPendingQuestion("");
        toast.error("分析失败", { description: streamError.detail });
        return;
      }
      if (!parsed) {
        setPhase({ name: "error", message: "stream ended without a result event" });
        setPendingQuestion("");
        toast.error("分析失败", { description: "stream ended without a result event" });
        return;
      }
      setTurns([
        {
          question: trimmed,
          response: parsed,
          kind: "parent",
          stagesSnapshot: stagesRef.current,
          planOpsSnapshot: planOpsRef.current,
          livePartialSnapshot: livePartialRef.current,
          attachedFiles: files.map((f) => ({ name: f.name, size: f.size })),
        },
      ]);
      setQuestion("");
      setPendingQuestion("");
      // Keep `livePartial` and `planOps` visible after `done` so the
      // user can scroll back through the completed StageTimeline +
      // plan-op chips. They get cleared when the *next* analyze
      // starts (see the setStages/setLivePartial reset above).
      setPhase({ name: "done" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "请求失败";
      setPhase({ name: "error", message });
      setPendingQuestion("");
      toast.error("无法连接到服务", { description: message });
    }
  };

  const submitFollowUp = async () => {
    if (!parent || !followUpParentId) return;
    const trimmed = question.trim();
    if (!trimmed) return;
    setPhase({ name: "follow_up" });
    resetProgress();
    setPendingQuestion(trimmed);
    setQuestion("");
    try {
      const response = await fetch("/api/follow-up/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        // parent_id = most recent turn's id (not the original turns[0]).
        // Backend's session store carries findings/cohorts/anchors
        // forward from the direct parent.
        body: JSON.stringify({ parent_id: followUpParentId, question: trimmed }),
      });
      if (!response.ok || !response.body) {
        const message = await readError(response);
        setPhase({ name: "error", message });
        toast.error("追问失败", { description: message });
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let parsed: AnalyzeResponse | null = null;
      let streamError: { status: number; detail: string } | null = null;

      while (true) {
        const { value, done } = await reader.read();
        if (value) {
          buffer += decoder.decode(value, { stream: !done });
          let nl: number;
          while ((nl = buffer.indexOf("\n")) !== -1) {
            const line = buffer.slice(0, nl).trim();
            buffer = buffer.slice(nl + 1);
            if (!line) continue;
            let event: StreamEvent;
            try {
              event = JSON.parse(line) as StreamEvent;
            } catch {
              continue;
            }
            if (event.type === "stage") {
              applyLiveStageEvent(event);
            } else if (event.type === "partial") {
              if (event.field === "summary" && event.delta) {
                appendLiveSummary(event.delta);
              } else if (event.field === "plan_op" && event.kind) {
                appendPlanOp(event.kind);
              } else if (event.field === "finding" && event.value) {
                appendLiveFinding(event.value);
              } else if (event.field === "recommendation" && event.text) {
                appendLiveRecommendation(event.text);
              }
            } else if (event.type === "result") {
              parsed = event.data;
            } else if (event.type === "error") {
              streamError = { status: event.status, detail: event.detail };
            }
          }
        }
        if (done) break;
      }

      if (streamError) {
        setPhase({ name: "error", message: streamError.detail });
        setPendingQuestion("");
        toast.error("追问失败", { description: streamError.detail });
        return;
      }
      if (!parsed) {
        setPhase({ name: "error", message: "stream ended without a result event" });
        setPendingQuestion("");
        toast.error("追问失败", { description: "stream ended without a result event" });
        return;
      }
      setTurns((prev) => [
        ...prev,
        {
          question: trimmed,
          response: parsed!,
          kind: "follow_up",
          stagesSnapshot: stagesRef.current,
          planOpsSnapshot: planOpsRef.current,
          livePartialSnapshot: livePartialRef.current,
        },
      ]);
      setQuestion("");
      setPendingQuestion("");
      setPhase({ name: "done" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "请求失败";
      setPhase({ name: "error", message });
      setPendingQuestion("");
      toast.error("无法连接到服务", { description: message });
    }
  };

  const disabled = isBusy;

  // Unified submit: first time goes to /v1/analyze (needs files);
  // subsequent times reuse the existing session via /v1/follow-up.
  // Special case: empty thread + no file → toast hint, do nothing
  // else. We deliberately do NOT add a synthetic turn — it just
  // clutters the thread with a "no file" message after the user
  // figures out the issue and uploads.
  const onSubmit = () => {
    if (turns.length === 0 && files.length === 0) {
      toast.info("请先上传 CSV 或 Excel 文件", {
        description: "点输入框左下角的 + 选择文件，或者把文件拖到对话框里。",
      });
      return;
    }
    if (turns.length === 0) submitAnalysis();
    else submitFollowUp();
  };

  const isEmpty = turns.length === 0 && !pendingQuestion && !isBusy;
  // Permit submit on empty thread without files — onSubmit routes that
  // to a local hint turn rather than the backend, so the user can hit
  // Enter and immediately learn why nothing happened.
  const canSubmit =
    !disabled &&
    question.trim().length > 0 &&
    (turns.length === 0
      ? true
      : !(parent?.is_refusal ?? false));

  // Pre-mount / hydrating: render the chat shell with NOTHING in the
  // middle column. Pinning to a single neutral skeleton (rather than
  // returning null) keeps the layout stable so the sidebar doesn't
  // jump when content lands. Sidebar is rendered by the layout, not
  // here, so it stays put either way.
  if (!mounted || hydrating) {
    return (
      <div className="flex flex-col min-h-[calc(100vh-8rem)] max-w-3xl mx-auto justify-center">
        <div className="flex items-center justify-center text-stone-300">
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-stone-300 animate-pulse" />
            <span className="w-1.5 h-1.5 rounded-full bg-stone-300 animate-pulse" style={{ animationDelay: "0.15s" }} />
            <span className="w-1.5 h-1.5 rounded-full bg-stone-300 animate-pulse" style={{ animationDelay: "0.3s" }} />
          </span>
        </div>
      </div>
    );
  }

  // When the report panel is open, push the chat column to the left
  // and tighten its max-width so the panel can sit beside it instead
  // of on top. Centered-auto layout is dropped in that state.
  const panelOpen = reportPanelId !== null;
  return (
    <div
      className={`flex flex-col min-h-[calc(100vh-8rem)] ${
        panelOpen ? "max-w-2xl pr-4" : "max-w-3xl mx-auto"
      } ${isEmpty ? "justify-center" : ""}`}
    >
      {/* Thread — scrolls naturally above the sticky composer below.
          Empty state: hero + suggestion chips + composer all centered
          vertically. Live state: turns + (optional) pending user
          bubble + LiveProgress fill the top, composer sticks below. */}
      <div className={`space-y-8 pb-6 ${isEmpty ? "" : "flex-1"}`}>
        {isEmpty && (
          <div className="text-center pt-10 pb-2 select-none">
            <h1 className="text-[40px] leading-tight font-serif font-medium text-stone-800 tracking-tight inline-flex items-center gap-3">
              <Sparkles className="text-indigo-500" size={32} strokeWidth={1.5} />
              {greeting}
            </h1>
            <p className="text-sm text-stone-500 mt-3">
              提一个问题，TableTalker 给你一份可复算的分析报告。
            </p>
          </div>
        )}

        <AnimatePresence initial={false}>
          {turns.map((turn, i) => (
            <ThreadTurn
              key={`${turn.response.id}-${i}`}
              turn={turn}
              index={i}
              fileChips={i === 0
                ? (files.length > 0
                    ? files.map((f) => ({ name: f.name, size: f.size }))
                    : (turn.attachedFiles ?? []))
                : []}
              isLatest={i === turns.length - 1 && !pendingQuestion}
              onOpenReport={setReportPanelId}
              onPickQuestion={pickQuestion}
            />
          ))}
        </AnimatePresence>

        {/* In-flight: pin the just-submitted question as a user bubble
            and let LiveProgress render the assistant side. When the
            stream lands the bubble + progress get replaced by a real
            ThreadTurn appended above. */}
        {pendingQuestion && (
          <div
            ref={pendingBubbleRef}
            className="space-y-3 scroll-mt-6 min-h-[calc(100vh-14rem)]"
          >
            {turns.length === 0 && files.length > 0 && (
              <FileAttachmentCard files={files} />
            )}
            <UserBubble text={pendingQuestion} />
            <LiveProgress
              stages={stages}
              inFlight={
                phase.name === "analyzing" ||
                phase.name === "uploading" ||
                phase.name === "follow_up"
              }
              planOps={planOps}
              livePartial={livePartial}
              liveFindings={liveFindings}
              liveRecommendations={liveRecommendations}
            />
          </div>
        )}
      </div>

      {/* Composer sticks to the bottom of the scroll area, like
          claude.ai. Suggestion chips show only on the empty state.
          The composer itself is the SAME card before and after the
          first turn — only the submit verb and the file-picker
          visibility change. */}
      <div className={isEmpty ? "" : "sticky bottom-0 -mx-2 px-2 pt-3 pb-4 bg-[#FBFAF7]"}>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={turns.length === 0 ? handleFileDrop : undefined}
          className={`bg-white rounded-2xl border shadow-sm transition-all overflow-hidden ${
            disabled
              ? "border-stone-200 opacity-80"
              : "border-stone-200 hover:border-stone-300 focus-within:border-stone-400 focus-within:ring-4 focus-within:ring-stone-100"
          }`}
        >
          {/* File chip strip — only shown before the first submit
              (when files are still editable). After turns exist, the
              files used by the original analyze are surfaced inline
              with the first user bubble instead. */}
          {turns.length === 0 && files.length > 0 && (
            <div className="px-4 pt-3 pb-2 flex flex-wrap items-center gap-2 border-b border-stone-100">
              {files.map((f, idx) => (
                <span
                  key={`${f.name}-${idx}`}
                  className="inline-flex items-center gap-2 max-w-full px-2.5 py-1 rounded-md bg-stone-50 border border-stone-200 text-xs text-stone-700"
                >
                  <FileSpreadsheet size={13} className="text-emerald-500 shrink-0" />
                  {idx === 0 && files.length > 1 && (
                    <span className="text-[10px] px-1 py-px rounded bg-indigo-100 text-indigo-700 font-semibold">
                      主表
                    </span>
                  )}
                  <span className="truncate max-w-[180px]" title={f.name}>
                    {f.name}
                  </span>
                  <span className="text-stone-400 text-[10px]">
                    {(f.size / 1024).toFixed(0)} KB
                  </span>
                  <button
                    onClick={() => removeFile(idx)}
                    disabled={disabled}
                    className="text-stone-400 hover:text-stone-600 disabled:opacity-50"
                    title="移除"
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={disabled || (turns.length > 0 && (parent?.is_refusal ?? false))}
            maxLength={500}
            placeholder={
              turns.length === 0
                ? files.length === 0
                  ? "想从数据里知道什么？先把文件拖进来或点 + 上传，再提一个具体问题。"
                  : "想从数据里知道什么？（Enter 发送 · Shift+Enter 换行）"
                : parent?.is_refusal
                  ? "本数据集已被拒答，继续追问只会得到同样的拒答说明。"
                  : "继续问点别的（Enter 发送 · Shift+Enter 换行）"
            }
            onKeyDown={(e) => {
              // Enter to send. Three things to skip:
              //   1. Shift+Enter — user wants a literal newline.
              //   2. nativeEvent.isComposing — we're mid-IME composition
              //      (e.g. picking a Chinese candidate). The Enter
              //      confirms the candidate, not "send the message".
              //      Some browsers also fire `keyCode === 229` during
              //      composition, kept here as a belt-and-suspenders
              //      check for older WebKit.
              //   3. Cmd/Ctrl+Enter — long-standing power-user habit;
              //      keep it working as an explicit submit.
              if (e.key !== "Enter") return;
              if (e.shiftKey) return;
              const ne = e.nativeEvent as KeyboardEvent;
              if (ne.isComposing || ne.keyCode === 229) return;
              if (!canSubmit) {
                e.preventDefault();
                return;
              }
              e.preventDefault();
              onSubmit();
            }}
            className="w-full px-5 pt-4 pb-2 bg-transparent border-none outline-none focus:outline-none focus:ring-0 resize-none text-[15px] text-stone-800 placeholder:text-stone-400 min-h-[80px] max-h-[240px]"
            rows={turns.length === 0 ? 3 : 2}
          />

          <div className="px-3 pb-3 pt-1 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              {/* File picker only on the empty state — once a session
                  has any turn, the dataset is locked (the backend
                  binds files to the session). */}
              {turns.length === 0 && (
                <>
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={disabled}
                    className="inline-flex items-center justify-center w-9 h-9 rounded-full border border-stone-200 text-stone-500 hover:text-stone-700 hover:border-stone-300 transition-colors disabled:opacity-50"
                    title="添加 CSV / Excel 文件"
                  >
                    <Plus size={16} />
                  </button>
                  <input
                    type="file"
                    ref={fileInputRef}
                    className="hidden"
                    accept=".csv, .xlsx, .xls"
                    multiple
                    onChange={handleFileSelect}
                    disabled={disabled}
                  />
                </>
              )}
              <span className="text-[11px] text-stone-400">
                {turns.length === 0
                  ? files.length === 0
                    ? "支持 CSV / Excel · 单文件 ≤ 200 MB"
                    : `${files.length} 个文件 · 第 1 个为主表`
                  : <button onClick={resetSession} className="text-indigo-600 hover:text-indigo-700 transition-colors inline-flex items-center gap-1"><Plus size={12} /> 开启新分析</button>
                }
              </span>
            </div>

            <button
              onClick={onSubmit}
              disabled={!canSubmit}
              aria-label={isBusy ? "分析中" : "发送"}
              title={isBusy ? "分析中" : "发送 (Enter)"}
              className="inline-flex items-center justify-center w-9 h-9 rounded-full bg-stone-900 text-white hover:bg-stone-800 focus:ring-4 focus:ring-stone-100 transition-all disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
            >
              {isBusy ? (
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <ArrowUp size={16} strokeWidth={2.5} />
              )}
            </button>
          </div>
        </div>
      </div>

      <ReportPanel
        reportId={reportPanelId}
        onClose={() => setReportPanelId(null)}
      />

      <FullScreenDropzone open={dragOverlay} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// UserBubble — right-aligned chat bubble for the user's question.
// claude.ai-style: light gray pill, dark text, no file chips inside
// (files render as a separate framed card above the first bubble; see
// `ThreadTurn`).
// ---------------------------------------------------------------------------
function UserBubble({ text }: { text: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-end"
    >
      <div className="max-w-[85%] bg-[#ECECE8] text-stone-800 rounded-2xl px-4 py-2.5">
        <p className="text-[14px] leading-relaxed whitespace-pre-wrap break-words">
          {text}
        </p>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// FullScreenDropzone — claude.ai-style: dim the page and show a big
// "drop here to add to chat" target as soon as a file drag enters
// the window. Drop is captured at the window level (in V2AnalyzePage's
// useEffect) so we don't need this overlay to be the actual drop
// target — it's purely visual feedback. `pointer-events-none` keeps
// the overlay from intercepting the drop event and confusing the OS.
// ---------------------------------------------------------------------------
function FullScreenDropzone({ open }: { open: boolean }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
          className="fixed inset-0 z-[60] flex items-center justify-center bg-[#FBFAF7]/90 backdrop-blur-sm pointer-events-none"
        >
          <motion.div
            initial={{ scale: 0.92, y: 6 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.96, y: 4 }}
            transition={{ duration: 0.14 }}
            className="flex flex-col items-center gap-3 select-none"
          >
            <div className="w-20 h-24 border-[2.5px] border-stone-700 rounded-md flex items-center justify-center">
              <Plus size={28} strokeWidth={2.4} className="text-stone-700" />
            </div>
            <p className="text-[15px] text-stone-700">
              拖文件到此处添加到对话
            </p>
            <p className="text-[12px] text-stone-400">
              支持 CSV / Excel · 单文件 ≤ 200 MB
            </p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}


// ---------------------------------------------------------------------------
// FileAttachmentCard — the small framed card that pins each attached
// file at the top-right of its turn (claude.ai pattern: file lives
// above the user bubble, separate from the question text).
// ---------------------------------------------------------------------------
function FileAttachmentCard({ files }: { files: { name: string; size: number }[] }) {
  if (files.length === 0) return null;
  return (
    <div className="flex justify-end gap-2 flex-wrap">
      {files.map((f, idx) => {
        const ext = f.name.split(".").pop()?.toUpperCase() ?? "FILE";
        return (
          <div
            key={`${f.name}-${idx}`}
            className="bg-white border border-stone-200 rounded-lg px-3 py-2 max-w-[200px] shadow-sm"
          >
            <div className="text-[12px] text-stone-700 font-medium leading-tight break-all line-clamp-2">
              {f.name}
            </div>
            <div className="mt-1.5 inline-flex items-center gap-1">
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-stone-100 text-stone-500">
                {ext}
              </span>
              {idx === 0 && files.length > 1 && (
                <span className="text-[10px] px-1 py-0.5 rounded bg-indigo-100 text-indigo-700 font-semibold">
                  主表
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ThreadTurn — one user/assistant pair in the chat thread.
//   1. File attachment card (right-aligned, only on the first turn).
//   2. User bubble (right-aligned, light gray pill).
//   3. Assistant message — claude.ai-style: NO card chrome, prose
//      flowing on the page background, with a tiny collapsible
//      tool-use chip and the report iframe collapsed by default.
// ---------------------------------------------------------------------------
function ThreadTurn({
  turn,
  index,
  fileChips,
  isLatest,
  onOpenReport,
  onPickQuestion,
}: {
  turn: Turn;
  index: number;
  fileChips: { name: string; size: number }[];
  isLatest: boolean;
  onOpenReport: (id: string) => void;
  onPickQuestion: (q: string) => void;
}) {
  return (
    <div className="space-y-3">
      {fileChips.length > 0 && <FileAttachmentCard files={fileChips} />}
      <UserBubble text={turn.question} />
      {turn.stagesSnapshot && turn.stagesSnapshot.length > 0 && (
        <StageTimeline
          stages={turn.stagesSnapshot}
          inFlight={false}
          planOps={turn.planOpsSnapshot ?? []}
        />
      )}
      <AssistantMessage
        turn={turn}
        index={index}
        isLatest={isLatest}
        onOpenReport={onOpenReport}
        onPickQuestion={onPickQuestion}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// LiveProgress: thin wrapper around StageTimeline that hides the timeline
// entirely when nothing has happened yet. Plan-op chips and the streaming
// summary live INSIDE StageTimeline rows now (under plan_llm / finalize_llm)
// so the page stays at one card no matter how much LLM intermediate
// content is flowing — fixes the "middle feels crowded" feedback.
// ---------------------------------------------------------------------------
function LiveProgress({
  stages,
  inFlight,
  planOps,
  livePartial,
  liveFindings,
  liveRecommendations,
}: {
  stages: StageState[];
  inFlight: boolean;
  planOps: string[];
  livePartial: string;
  liveFindings: Array<{ title: string; detail: string }>;
  liveRecommendations: string[];
}) {
  const hasContent =
    stages.some((s) => s.status !== "pending") ||
    planOps.length > 0 ||
    livePartial.length > 0 ||
    liveFindings.length > 0 ||
    liveRecommendations.length > 0;
  if (!hasContent) return null;
  // Layout mirrors AssistantMessage exactly so the streamed preview
  // and the post-result final view look identical — when the swap
  // happens (LiveProgress unmounts, ThreadTurn mounts), the user
  // shouldn't notice a transition. Each finding / recommendation
  // fades in the moment its JSON brace closes on the backend.
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4"
    >
      <StageTimeline
        stages={stages}
        inFlight={inFlight}
        planOps={planOps}
      />
      {livePartial && (
        <p className="text-[15px] text-stone-800 leading-relaxed whitespace-pre-wrap">
          {livePartial}
          {inFlight && !liveFindings.length && (
            <span
              className="inline-block w-1 h-4 ml-0.5 bg-stone-500 animate-pulse align-middle"
              aria-hidden="true"
            />
          )}
        </p>
      )}
      {liveFindings.length > 0 && (
        <div className="space-y-3">
          {liveFindings.map((f, i) => (
            <motion.div
              key={`${i}-${f.title}`}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className="space-y-1"
            >
              <p className="font-semibold text-stone-800">{f.title}</p>
              <p className="text-stone-600 text-[14px]">{f.detail}</p>
            </motion.div>
          ))}
        </div>
      )}
      {liveRecommendations.length > 0 && (
        <div>
          <p className="font-semibold text-stone-800 mb-1.5">建议</p>
          <ul className="list-disc pl-5 space-y-1 text-stone-600 text-[14px]">
            {liveRecommendations.map((r, i) => (
              <motion.li
                key={`${i}-${r.slice(0, 12)}`}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2 }}
              >
                {r}
              </motion.li>
            ))}
          </ul>
        </div>
      )}
    </motion.div>
  );
}


// ---------------------------------------------------------------------------
// AssistantMessage — claude.ai-style assistant turn. NO card chrome:
// the prose flows directly on the page background. Layout matches
// claude's HR-attrition example (image #11):
//   - 1 line "Viewed a file, ran a command >" tool-use chip (collapsible
//     timeline + per-op chips inside).
//   - Bold conclusion / summary paragraph.
//   - Findings as inline subheadings + body text (no card grid).
//   - Recommendations as a bullet list.
//   - "Open / Download report" links instead of an inline iframe by
//     default; iframe opens on click.
// ---------------------------------------------------------------------------
function AssistantMessage({
  turn,
  index: _,
  isLatest,
  onOpenReport,
  onPickQuestion,
}: {
  turn: Turn;
  index: number;
  isLatest: boolean;
  onOpenReport: (id: string) => void;
  onPickQuestion: (q: string) => void;
}) {
  const { response } = turn;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="space-y-4 text-stone-800 text-[15px] leading-relaxed"
    >
      {response.is_refusal && (
        <div className="inline-flex items-center gap-1.5 text-[12px] text-rose-700 bg-rose-50 border border-rose-100 px-2 py-1 rounded">
          <Frown size={13} /> 已拒答
        </div>
      )}

      <p className="whitespace-pre-wrap">{response.summary}</p>

      {response.findings.length > 0 && (
        <div className="space-y-3">
          {response.findings.map((f, i) => (
            <div key={i} className="space-y-1">
              <p className="font-semibold text-stone-800">{f.title}</p>
              <p className="text-stone-600 text-[14px]">{f.detail}</p>
            </div>
          ))}
        </div>
      )}

      {response.recommendations.length > 0 && (
        <div>
          <p className="font-semibold text-stone-800 mb-1.5">建议</p>
          <ul className="list-disc pl-5 space-y-1 text-stone-600 text-[14px]">
            {response.recommendations.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {!response.is_refusal && response.charts[0]?.echarts_option && (
        // First chart inline (backend caps at 1 to keep the chat
        // tight). Wrapped in a quiet card so it's clearly an artefact
        // separate from the prose. The rest of the charts live in the
        // report side-panel — "完整报告" button below opens it.
        <div className="bg-white border border-stone-200 rounded-lg p-3">
          {response.charts[0].title && (
            <div className="text-[12px] text-stone-500 mb-1.5 px-1">
              {response.charts[0].title}
            </div>
          )}
          <ChartCanvas
            optionJson={response.charts[0].echarts_option}
            className="w-full h-[300px]"
          />
        </div>
      )}

      {!response.is_refusal && response.charts.length > 0 && (
        <div className="pt-1">
          <button
            onClick={() => onOpenReport(response.id)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md bg-indigo-600 text-white text-[13px] font-medium hover:bg-indigo-700 focus:ring-4 focus:ring-indigo-100 transition-colors"
          >
            <BarChart3 size={14} />
            完整报告
          </button>
        </div>
      )}

      {/* Per-turn suggested follow-ups, only on the latest turn (the
          chips are about "what to ask next", which only makes sense
          for the conversation tail). Clicking fills the textarea so
          the user can edit before sending. */}
      {isLatest &&
        !response.is_refusal &&
        (response.suggested_questions?.length ?? 0) > 0 && (
        <div className="pt-2">
          <div className="text-[11px] text-stone-400 mb-1.5">推荐继续追问</div>
          <div className="flex flex-wrap gap-1.5">
            {response.suggested_questions!.map((q) => (
              <button
                key={q}
                onClick={() => onPickQuestion(q)}
                className="px-2.5 py-1 rounded-full border border-stone-200 bg-white text-[12px] text-stone-600 hover:text-stone-900 hover:border-stone-300 transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}


// ---------------------------------------------------------------------------
// V2 Turn Card Component
// ---------------------------------------------------------------------------
function V2TurnCard({ turn, index }: { turn: Turn; index: number }) {
  const { response, question, kind } = turn;
  const isParent = kind === "parent";
  const [reportOpen, setReportOpen] = useState(true);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`bg-white rounded-xl border ${isParent ? 'border-stone-200' : 'border-indigo-100/50'} shadow-sm p-6 space-y-5`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-stone-100 pb-4">
        <div className="flex items-center gap-3">
          {response.is_refusal ? (
            <span className="px-2.5 py-1 rounded-md text-xs font-medium bg-rose-100 text-rose-700 flex items-center gap-1">
              <Frown size={14}/> 已拒答
            </span>
          ) : (
            <span className={`px-2.5 py-1 rounded-md text-xs font-medium ${isParent ? 'bg-emerald-100 text-emerald-700' : 'bg-indigo-100 text-indigo-700'}`}>
              {isParent ? '首次提问' : `追问 #${index}`}
            </span>
          )}
          <h4 className="font-semibold text-stone-800 text-lg leading-snug">{question}</h4>
        </div>
        <div className="text-xs text-stone-400 font-mono bg-stone-50 px-2 py-1 rounded border border-stone-100">
          ID: {response.id}
        </div>
      </div>

      {/* Summary */}
      <div className="text-sm text-stone-700 leading-relaxed bg-stone-50 p-4 rounded-lg border border-stone-100">
        <p className="whitespace-pre-wrap">{response.summary}</p>
      </div>

      {/* Findings */}
      {response.findings.length > 0 && (
        <div className="space-y-3">
          <h5 className="text-xs font-bold text-stone-500 uppercase tracking-wider flex items-center gap-1.5">
            <Sparkles size={14}/> 关键发现
          </h5>
          <div className="grid gap-3">
            {response.findings.map((f, i) => (
              <div key={i} className="border border-stone-100 rounded-lg p-3.5 bg-white">
                <p className="text-sm font-semibold text-stone-800 mb-1">{f.title}</p>
                <p className="text-xs text-stone-500 leading-relaxed">{f.detail}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {response.recommendations.length > 0 && (
        <div className="space-y-3 mt-4">
          <h5 className="text-xs font-bold text-stone-500 uppercase tracking-wider flex items-center gap-1.5">
            <Activity size={14}/> 建议
          </h5>
          <ul className="list-disc pl-5 space-y-1.5 text-sm text-stone-600">
            {response.recommendations.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Iframe Report (Charts) */}
      {!response.is_refusal && response.charts.length > 0 && (
        <div className="mt-6 pt-4 border-t border-stone-100">
          <div className="flex items-center justify-between mb-3">
            <button 
              onClick={() => setReportOpen(!reportOpen)}
              className="flex items-center gap-1 text-xs font-bold text-stone-500 hover:text-stone-800 uppercase tracking-wider transition-colors cursor-pointer"
            >
              数据图表报告
              <ChevronDown size={14} className={`transition-transform duration-200 ${reportOpen ? "rotate-180" : ""}`} />
            </button>
            <div className="flex items-center gap-3">
              <a href={`/api/reports/${response.id}/download`} className="text-xs text-emerald-700 hover:text-emerald-800 flex items-center gap-1">
                下载 HTML <Download size={12}/>
              </a>
              <a href={`/reports/${response.id}.html`} target="_blank" rel="noreferrer" className="text-xs text-indigo-600 hover:text-indigo-700 flex items-center gap-1">
                新窗口打开 <ExternalLink size={12}/>
              </a>
            </div>
          </div>
          <AnimatePresence>
            {reportOpen && (
              <motion.div 
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className={`w-full mt-3 bg-stone-50 rounded-xl overflow-hidden border border-stone-200 relative ${isParent ? 'min-h-[550px]' : 'min-h-[400px]'}`}>
                  <iframe 
                    src={`/reports/${response.id}.html`}
                    className="absolute inset-0 w-full h-full border-none"
                    title={`Report ${response.id}`}
                    sandbox="allow-scripts allow-same-origin allow-popups"
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// ReportPanel — right-side slide-in panel hosting the full HTML report
// in an iframe. claude.ai-style split layout: the panel lives beside
// the chat (no dim backdrop, chat column shifts left) so the user can
// keep asking follow-ups while reading the report. Esc or the X
// button closes it.
// ---------------------------------------------------------------------------
function ReportPanel({
  reportId,
  onClose,
}: {
  reportId: string | null;
  onClose: () => void;
}) {
  const open = reportId !== null;
  const panelRef = useRef<HTMLElement | null>(null);

  // Esc to close. Bound only when the panel is open so we don't fight
  // with other keybindings on the page.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Click outside closes. Registration is deferred by one animation
  // frame so the same click that opened the panel (e.g. the "完整报告"
  // button) doesn't immediately re-close it. Uses `mousedown` so the
  // close fires before subsequent click handlers — matches how
  // popovers and dropdowns typically dismiss.
  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (panelRef.current && panelRef.current.contains(target)) return;
      onClose();
    };
    const raf = requestAnimationFrame(() => {
      document.addEventListener("mousedown", onMouseDown);
    });
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          ref={panelRef}
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ type: "spring", stiffness: 320, damping: 32 }}
          className="fixed top-0 right-0 bottom-0 z-40 w-full sm:w-[55vw] lg:w-[52vw] xl:max-w-[820px] bg-white border-l border-stone-200 shadow-xl flex flex-col"
        >
            <header className="h-14 px-4 flex items-center justify-between border-b border-stone-200 shrink-0 bg-white">
              <div className="flex items-center gap-2 text-stone-700">
                <BarChart3 size={16} className="text-indigo-500" />
                <span className="font-semibold text-[14px]">完整报告</span>
              </div>
              <div className="flex items-center gap-1">
                <a
                  href={`/reports/${reportId}.html`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center px-2 py-1 rounded-md text-stone-600 hover:text-stone-900 hover:bg-stone-100 transition-colors"
                  title="新窗口打开"
                >
                  <ExternalLink size={14} />
                </a>
                <a
                  href={`/api/reports/${reportId}/download`}
                  className="inline-flex items-center px-2 py-1 rounded-md text-stone-600 hover:text-stone-900 hover:bg-stone-100 transition-colors"
                  title="下载 HTML"
                >
                  <Download size={14} />
                </a>
                <button
                  onClick={onClose}
                  className="inline-flex items-center px-2 py-1 rounded-md text-stone-500 hover:text-stone-900 hover:bg-stone-100 transition-colors"
                  title="关闭 (Esc)"
                  type="button"
                >
                  <X size={16} />
                </button>
              </div>
            </header>
            <div className="flex-1 min-h-0 overflow-hidden bg-stone-50">
              {reportId && (
                <iframe
                  key={reportId}
                  src={`/reports/${reportId}.html`}
                  className="w-full h-full border-none block"
                  title={`Report ${reportId}`}
                  sandbox="allow-scripts allow-same-origin allow-popups"
                />
              )}
            </div>
          </motion.aside>
      )}
    </AnimatePresence>
  );
}
