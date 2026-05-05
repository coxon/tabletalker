"use client";

// Top-level client island that owns the conversation. Single component
// because state is shallow (~5 fields) and a Context layer would just
// be ceremony. Refresh = reset = matches the backend's TTL'd session.

import { forwardRef, useCallback, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";

import type {
  AnalyzePhase,
  AnalyzeResponse,
  Turn,
} from "../lib/contract";
import { Composer, type ComposerHandle } from "./Composer";
import { Dropzone } from "./Dropzone";
import { Palette } from "./Palette";
import { SkeletonTurn } from "./SkeletonTurn";
import { TopBar } from "./TopBar";
import { TurnCard } from "./TurnCard";

interface AnalyzeShellProps {
  backendOnline: boolean;
  backendLabel: string;
}

interface ApiErrorBody {
  detail?: string;
  error?: string;
}

async function readError(response: Response): Promise<string> {
  // Backend returns either FastAPI's `{ detail: ... }` or our proxy's
  // `{ error: ... }`. Status text is the last fallback so a malformed
  // body never silently swallows the cause.
  try {
    const body = (await response.json()) as ApiErrorBody;
    return body.detail ?? body.error ?? response.statusText;
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

export function AnalyzeShell({ backendOnline, backendLabel }: AnalyzeShellProps) {
  const [file, setFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<AnalyzePhase>({ name: "idle" });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const composerRef = useRef<ComposerHandle>(null);

  const parent = turns[0]?.response ?? null;
  const isBusy =
    phase.name === "uploading" ||
    phase.name === "analyzing" ||
    phase.name === "follow_up";

  const resetSession = useCallback(() => {
    setTurns([]);
    setFile(null);
    setQuestion("");
    setPhase({ name: "idle" });
    setTimeout(() => composerRef.current?.focus(), 30);
  }, []);

  const submitParent = useCallback(async () => {
    if (!file) {
      toast.error("请选择一个 CSV/XLSX 文件");
      return;
    }
    const trimmed = question.trim();
    if (!trimmed) {
      toast.error("请输入一个问题");
      return;
    }
    setPhase({ name: "uploading" });
    const form = new FormData();
    form.append("file", file);
    form.append("question", trimmed);

    try {
      // Flip to "analyzing" once the bytes are in flight; we can't
      // tell precisely when the server starts processing, so this is
      // best-effort UX framing.
      setPhase({ name: "analyzing" });
      const response = await fetch("/api/analyze", { method: "POST", body: form });
      if (!response.ok) {
        const message = await readError(response);
        setPhase({ name: "error", message });
        toast.error("分析失败", { description: message });
        return;
      }
      const parsed = (await response.json()) as AnalyzeResponse;
      setTurns([{ question: trimmed, response: parsed, kind: "parent" }]);
      setQuestion("");
      setPhase({ name: "done" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "请求失败";
      setPhase({ name: "error", message });
      toast.error("无法连接到服务", { description: message });
    }
  }, [file, question]);

  const submitFollowUp = useCallback(async () => {
    if (!parent) return;
    const trimmed = question.trim();
    if (!trimmed) return;
    setPhase({ name: "follow_up" });
    try {
      const response = await fetch("/api/follow-up", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ parent_id: parent.id, question: trimmed }),
      });
      if (!response.ok) {
        const message = await readError(response);
        setPhase({ name: "error", message });
        toast.error("追问失败", { description: message });
        return;
      }
      const parsed = (await response.json()) as AnalyzeResponse;
      setTurns((prev) => [
        ...prev,
        { question: trimmed, response: parsed, kind: "follow_up" },
      ]);
      setQuestion("");
      setPhase({ name: "done" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "请求失败";
      setPhase({ name: "error", message });
      toast.error("无法连接到服务", { description: message });
    }
  }, [parent, question]);

  return (
    <>
      <TopBar
        backendOnline={backendOnline}
        backendLabel={backendLabel}
        onOpenPalette={() => setPaletteOpen(true)}
      />
      <main className="mx-auto flex w-full max-w-[88ch] flex-col gap-8 px-6 py-10">
        {parent ? null : <Hero />}

        <AnimatePresence initial={false}>
          {turns.map((turn, index) => (
            <TurnCard key={`${turn.response.id}-${index}`} turn={turn} index={index} />
          ))}
          {phase.name === "analyzing" ? (
            <motion.div
              key="skeleton-parent"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              <SkeletonTurn label="正在分析（首次约 30–60 秒）…" />
            </motion.div>
          ) : null}
          {phase.name === "follow_up" ? (
            <motion.div
              key="skeleton-followup"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              <SkeletonTurn label="正在生成追问回答…" />
            </motion.div>
          ) : null}
        </AnimatePresence>

        {parent ? (
          <FollowUpZone
            ref={composerRef}
            question={question}
            onChange={setQuestion}
            onSubmit={submitFollowUp}
            disabled={isBusy}
            busy={phase.name === "follow_up"}
            parentRefused={parent.is_refusal}
          />
        ) : (
          <ParentZone
            ref={composerRef}
            file={file}
            question={question}
            onFileChange={setFile}
            onQuestionChange={setQuestion}
            onSubmit={submitParent}
            disabled={isBusy}
            busy={phase.name === "uploading" || phase.name === "analyzing"}
            phase={phase}
          />
        )}
      </main>
      <Palette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onResetSession={resetSession}
      />
    </>
  );
}

function Hero() {
  return (
    <section className="flex flex-col gap-3 pb-2">
      <h1 className="font-display text-[2.5rem] italic leading-[1.05] tracking-tight">
        提问你的表格。
      </h1>
      <p className="max-w-[58ch] text-[15px] leading-relaxed text-[--color-fg-muted]">
        上传 CSV 或 Excel，TableTalker 会调用规划器对每一条结论生成可复现的证据，
        并把图表、要点、追问入口收进同一份报告。
      </p>
    </section>
  );
}

interface ParentZoneProps {
  file: File | null;
  question: string;
  onFileChange: (file: File | null) => void;
  onQuestionChange: (q: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  busy: boolean;
  phase: AnalyzePhase;
}

const ParentZone = forwardRef<ComposerHandle, ParentZoneProps>(function ParentZone(
  props,
  ref,
) {
  return (
    <section
      aria-label="上传与提问"
      className="grid grid-cols-1 gap-5 md:grid-cols-[minmax(0,1.05fr)_minmax(0,1.4fr)]"
    >
      <Dropzone
        file={props.file}
        onFile={props.onFileChange}
        disabled={props.disabled}
      />
      <div className="flex flex-col gap-2">
        <Composer
          ref={ref}
          value={props.question}
          onChange={props.onQuestionChange}
          onSubmit={props.onSubmit}
          placeholder="例如：哪个年龄段的客户消费金额最高？"
          disabled={props.disabled}
          busy={props.busy}
          busyLabel={
            props.phase.name === "uploading" ? "上传中…" : "分析中…"
          }
          ctaLabel="开始分析"
          helperHint={
            props.file
              ? `${props.file.name} · ⌘+Enter 提交`
              : "先选择一个文件，⌘+Enter 提交"
          }
        />
      </div>
    </section>
  );
});

interface FollowUpZoneProps {
  question: string;
  onChange: (q: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  busy: boolean;
  parentRefused: boolean;
}

const FollowUpZone = forwardRef<ComposerHandle, FollowUpZoneProps>(function FollowUpZone(
  props,
  ref,
) {
  return (
    <section
      aria-label="追问"
      className="rounded-[--radius-md] border border-[--color-border] bg-[--color-bg-elev] p-4"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
          追问
        </span>
      </div>
      <Composer
        ref={ref}
        value={props.question}
        onChange={props.onChange}
        onSubmit={props.onSubmit}
        placeholder={
          props.parentRefused
            ? "本数据集已被拒答，继续追问只会得到同样的拒答说明。"
            : "继续向同一份数据提问，例如：那女性顾客呢？"
        }
        disabled={props.disabled}
        busy={props.busy}
        busyLabel="处理中…"
        ctaLabel="提交追问"
        helperHint="⌘+Enter 提交 · ⌘+K 开新分析"
      />
    </section>
  );
});
