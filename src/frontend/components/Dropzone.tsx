"use client";

// Drop-zone for the empty state. Two responsibilities:
//   1. Visible rectangle that doubles as the file picker click target.
//   2. Page-wide drag overlay so the user can drop anywhere — without
//      that, the rectangle's hit area becomes a fiddly tax on the
//      first-five-seconds goal stated in the brief.
//
// File validation is intentionally permissive (extension-only). The
// backend re-validates with a real magic-byte sniff; we keep client
// checks light so we don't reject valid files for theatrical reasons.

import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { FileSpreadsheet, FilePlus2 } from "lucide-react";

const ACCEPT = ".csv,.xlsx";

interface DropzoneProps {
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
}

function fileMatchesAccept(name: string): boolean {
  const lowered = name.toLowerCase();
  return lowered.endsWith(".csv") || lowered.endsWith(".xlsx");
}

export function Dropzone({ file, onFile, disabled }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [draggingPage, setDraggingPage] = useState(false);
  const [dragOverDropzone, setDragOverDropzone] = useState(false);

  // Window-level dragenter/leave counter. We use a ref counter rather
  // than a boolean because dragenter fires for nested elements too;
  // without the counter the overlay flickers as the cursor crosses
  // child boundaries.
  const enterCount = useRef(0);

  useEffect(() => {
    // When the dropzone goes disabled mid-drag (e.g. analysis kicks
    // off while the user still has a drag in flight), tear down any
    // visible drag UI so the screen doesn't get stuck in the overlay
    // state with no way to dismiss it.
    if (disabled) {
      enterCount.current = 0;
      setDraggingPage(false);
      setDragOverDropzone(false);
      return;
    }
    const onEnter = (event: globalThis.DragEvent) => {
      // Only react to file drags, never to text/element drags.
      if (!event.dataTransfer?.types.includes("Files")) return;
      enterCount.current += 1;
      setDraggingPage(true);
    };
    const onLeave = (event: globalThis.DragEvent) => {
      if (!event.dataTransfer?.types.includes("Files")) return;
      enterCount.current = Math.max(0, enterCount.current - 1);
      if (enterCount.current === 0) setDraggingPage(false);
    };
    const onDrop = () => {
      enterCount.current = 0;
      setDraggingPage(false);
    };
    const onOver = (event: globalThis.DragEvent) => {
      // Required to make the page a valid drop target.
      if (event.dataTransfer?.types.includes("Files")) event.preventDefault();
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    window.addEventListener("dragover", onOver);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("dragover", onOver);
    };
  }, [disabled]);

  const handlePageDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (disabled) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped && fileMatchesAccept(dropped.name)) {
      onFile(dropped);
    }
  };

  const handleZoneDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragOverDropzone(false);
    if (disabled) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped && fileMatchesAccept(dropped.name)) {
      onFile(dropped);
    }
  };

  const handlePicked = (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0];
    if (picked && fileMatchesAccept(picked.name)) {
      onFile(picked);
    } else if (picked) {
      onFile(null);
    }
    // Clear the native value so re-picking the same file emits change
    // again. Without this the user can't re-select after we've reset
    // file state (e.g. failed analysis → "try the same file again").
    event.target.value = "";
  };

  return (
    <>
      {/* Page-wide overlay — only renders while a file drag is active.
          The actual drop handler fires when the user releases over any
          part of the document. AnimatePresence keeps the exit fade
          alive after `draggingPage` flips back to false. */}
      <AnimatePresence>
        {draggingPage ? (
          <motion.div
            key="page-drop-overlay"
            // Atmospheric blur so the underlying page recedes; the
            // dashed border draws the eye to "you can drop here".
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.32, 0.72, 0, 1] }}
            className="fixed inset-3 z-40 rounded-[14px] border-2 border-dashed border-[--color-accent] bg-[--color-accent-soft]/60 backdrop-blur-sm"
            onDrop={handlePageDrop}
            onDragOver={(event) => event.preventDefault()}
          >
            <div className="absolute inset-0 grid place-items-center">
              <p className="font-display text-2xl italic text-[--color-fg]">
                松开以载入数据
              </p>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <label
        htmlFor="dropzone-input"
        // The dropzone rectangle is its own drop target so dropping
        // *into* it works even when the page-overlay isn't visible
        // (e.g. user toggled accept then re-dropped).
        onDragEnter={disabled ? undefined : () => setDragOverDropzone(true)}
        onDragLeave={disabled ? undefined : () => setDragOverDropzone(false)}
        onDragOver={disabled ? undefined : (event) => event.preventDefault()}
        onDrop={disabled ? undefined : handleZoneDrop}
        className={[
          "group relative flex h-full min-h-[220px] flex-col items-center justify-center gap-2 rounded-[--radius-md] border border-dashed px-6 py-8 text-center transition",
          dragOverDropzone
            ? "border-[--color-accent] bg-[--color-accent-soft]"
            : "border-[--color-border-strong] bg-[--color-bg-elev] hover:border-[--color-fg-faint]",
          disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          id="dropzone-input"
          type="file"
          accept={ACCEPT}
          onChange={handlePicked}
          disabled={disabled}
          className="sr-only"
        />
        {file ? (
          <>
            <FileSpreadsheet
              size={28}
              strokeWidth={1.4}
              className="text-[--color-accent]"
            />
            <p className="text-sm font-medium">{file.name}</p>
            <p className="nums text-xs text-[--color-fg-faint]">
              {(file.size / 1024).toFixed(1)} KB · 点击或拖入新文件以替换
            </p>
          </>
        ) : (
          <>
            <FilePlus2
              size={28}
              strokeWidth={1.4}
              className="text-[--color-fg-faint] transition group-hover:text-[--color-fg-muted]"
            />
            <p className="text-sm font-medium">把 .csv 或 .xlsx 拖到这里</p>
            <p className="text-xs text-[--color-fg-faint]">
              或点击选择文件
            </p>
          </>
        )}
      </label>
    </>
  );
}
