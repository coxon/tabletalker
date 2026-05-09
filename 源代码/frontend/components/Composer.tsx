"use client";

// Question textarea + submit. ⌘+Enter / Ctrl+Enter submits — the
// non-stretchy keyboard path power users expect from any chat-style
// product (Linear, Slack, Discord). Plain Enter inserts newline (the
// question is sometimes 2-3 sentences for follow-ups).

import {
  forwardRef,
  useImperativeHandle,
  useRef,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { ArrowRight, Loader2 } from "lucide-react";

export interface ComposerHandle {
  focus: () => void;
}

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  disabled?: boolean;
  busy?: boolean;
  busyLabel?: string;
  ctaLabel: string;
  helperHint?: string;
}

export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  props,
  ref,
) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({
    focus: () => taRef.current?.focus(),
  }));

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (props.disabled || props.busy) return;
    if (!props.value.trim()) return;
    props.onSubmit();
  };

  const handleKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (props.disabled || props.busy) return;
      if (!props.value.trim()) return;
      props.onSubmit();
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-2"
      aria-busy={props.busy ? "true" : "false"}
    >
      <textarea
        ref={taRef}
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        onKeyDown={handleKey}
        placeholder={props.placeholder}
        rows={3}
        disabled={props.disabled}
        className="resize-y rounded-[--radius-md] border border-[--color-border-strong] bg-[--color-bg-elev] px-3.5 py-2.5 text-[15px] leading-relaxed placeholder:text-[--color-fg-faint] disabled:opacity-60"
      />
      <div className="flex items-center justify-between gap-3">
        <p className="nums text-xs text-[--color-fg-faint]">
          {props.helperHint ?? "⌘+Enter 提交"}
        </p>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={props.disabled || props.busy || !props.value.trim()}
        >
          {props.busy ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              <span>{props.busyLabel ?? "处理中…"}</span>
            </>
          ) : (
            <>
              <span>{props.ctaLabel}</span>
              <ArrowRight size={14} />
            </>
          )}
        </button>
      </div>
    </form>
  );
});
