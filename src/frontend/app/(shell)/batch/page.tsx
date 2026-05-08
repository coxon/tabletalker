"use client";

import { useCallback, useRef, useState, type ChangeEvent } from "react";
import { toast } from "sonner";
import {
  Upload,
  FileText,
  FileSpreadsheet,
  X,
  Loader2,
  Download,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

function batchEndpoint(): string {
  if (typeof window === "undefined") return "/api/batch";
  const backendPort = window.location.port === "3000" ? "8000" : window.location.port;
  return `${window.location.protocol}//${window.location.hostname}:${backendPort}/v1/batch`;
}

type Phase =
  | { name: "idle" }
  | { name: "submitting" }
  | { name: "done"; tasks: number; errors: number }
  | { name: "error"; message: string };

export default function BatchPage() {
  const [manifest, setManifest] = useState<File | null>(null);
  const [dataFiles, setDataFiles] = useState<File[]>([]);
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const manifestRef = useRef<HTMLInputElement>(null);
  const filesRef = useRef<HTMLInputElement>(null);

  const isBusy = phase.name === "submitting";

  const handleManifestChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setManifest(file);
    e.target.value = "";
  };

  const handleFilesChange = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length > 0) {
      setDataFiles((prev) => {
        const names = new Set(prev.map((f) => f.name));
        const deduped = picked.filter((f) => !names.has(f.name));
        return [...prev, ...deduped];
      });
    }
    e.target.value = "";
  };

  const removeFile = (name: string) => {
    setDataFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const submit = useCallback(async () => {
    if (!manifest) {
      toast.error("请上传 manifest 文件");
      return;
    }
    if (dataFiles.length === 0) {
      toast.error("请上传至少一个数据文件");
      return;
    }

    setPhase({ name: "submitting" });

    const form = new FormData();
    form.append("manifest", manifest);
    for (const file of dataFiles) {
      form.append("files", file);
    }

    try {
      const response = await fetch(`${batchEndpoint()}`, {
        method: "POST",
        body: form,
      });

      if (!response.ok) {
        let message: string;
        try {
          const body = (await response.json()) as {
            detail?: string;
            error?: string;
          };
          message = body.detail ?? body.error ?? response.statusText;
        } catch {
          message = response.statusText || `HTTP ${response.status}`;
        }
        setPhase({ name: "error", message });
        toast.error("批量评测失败", { description: message });
        return;
      }

      const tasks = parseInt(
        response.headers.get("x-batch-tasks") ?? "0",
        10,
      );
      const errors = parseInt(
        response.headers.get("x-batch-errors") ?? "0",
        10,
      );

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "tabletalker-batch-results.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      setPhase({ name: "done", tasks, errors });
      toast.success("批量评测完成", {
        description: `${tasks} 个任务，${errors} 个错误`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "请求失败";
      setPhase({ name: "error", message });
      toast.error("批量评测失败", { description: message });
    }
  }, [manifest, dataFiles]);

  return (
    <main className="mx-auto flex w-full max-w-[88ch] flex-col gap-6 px-6 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="font-display text-[2rem] italic leading-tight tracking-tight">
          批量评测
        </h1>
        <p className="max-w-[58ch] text-[15px] leading-relaxed text-[--color-fg-muted]">
          上传 manifest 和数据文件，一次性运行多个分析任务并导出 xlsx 结果。
        </p>
      </header>

      <section className="rounded-[--radius-md] border border-[--color-border] bg-[--color-bg-elev] p-5">
        <h2 className="mb-3 text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
          Manifest 格式说明
        </h2>
        <div className="text-[13px] leading-relaxed text-[--color-fg-muted]">
          <p>
            Manifest 文件为 JSONL 或 CSV 格式，每行描述一个评测任务。
          </p>
          <p className="mt-1.5 font-mono text-[12px] text-[--color-fg-faint]">
            {`{"file": "sales.csv", "question": "哪个月销售额最高？"}`}
          </p>
          <p className="mt-1.5">
            字段：<code className="font-mono text-[12px]">file</code>（数据文件名）、
            <code className="font-mono text-[12px]">question</code>（分析问题）。
            可选：<code className="font-mono text-[12px]">extra_files</code>、
            <code className="font-mono text-[12px]">sampling_rate</code>。
          </p>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <section className="flex flex-col gap-3">
          <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
            Manifest 文件
          </h2>
          <input
            ref={manifestRef}
            type="file"
            accept=".jsonl,.csv"
            onChange={handleManifestChange}
            disabled={isBusy}
            className="sr-only"
          />
          {manifest ? (
            <div className="flex items-center gap-2 rounded-[--radius-md] border border-[--color-border] bg-[--color-bg-sunken] px-3 py-2.5">
              <FileText size={16} className="shrink-0 text-[--color-accent]" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">
                {manifest.name}
              </span>
              <span className="nums text-xs text-[--color-fg-faint]">
                {(manifest.size / 1024).toFixed(1)} KB
              </span>
              <button
                type="button"
                onClick={() => setManifest(null)}
                disabled={isBusy}
                className="rounded p-0.5 text-[--color-fg-faint] hover:text-[--color-fg]"
              >
                <X size={14} />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => manifestRef.current?.click()}
              disabled={isBusy}
              className="flex min-h-[100px] flex-col items-center justify-center gap-1.5 rounded-[--radius-md] border border-dashed border-[--color-border-strong] bg-[--color-bg-elev] px-4 py-6 text-center transition hover:border-[--color-fg-faint]"
            >
              <Upload
                size={22}
                strokeWidth={1.4}
                className="text-[--color-fg-faint]"
              />
              <span className="text-sm">选择 .jsonl 或 .csv manifest</span>
            </button>
          )}
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-[--color-fg-faint]">
            数据文件
          </h2>
          <input
            ref={filesRef}
            type="file"
            accept=".csv,.xlsx"
            multiple
            onChange={handleFilesChange}
            disabled={isBusy}
            className="sr-only"
          />
          {dataFiles.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              {dataFiles.map((f) => (
                <div
                  key={f.name}
                  className="flex items-center gap-2 rounded-[--radius-sm] border border-[--color-border] bg-[--color-bg-sunken] px-3 py-1.5"
                >
                  <FileSpreadsheet
                    size={14}
                    className="shrink-0 text-[--color-accent]"
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px]">
                    {f.name}
                  </span>
                  <span className="nums text-[11px] text-[--color-fg-faint]">
                    {(f.size / 1024).toFixed(1)} KB
                  </span>
                  <button
                    type="button"
                    onClick={() => removeFile(f.name)}
                    disabled={isBusy}
                    className="rounded p-0.5 text-[--color-fg-faint] hover:text-[--color-fg]"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => filesRef.current?.click()}
                disabled={isBusy}
                className="self-start text-[12px] font-medium text-[--color-fg-muted] hover:text-[--color-fg]"
              >
                + 添加更多文件
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => filesRef.current?.click()}
              disabled={isBusy}
              className="flex min-h-[100px] flex-col items-center justify-center gap-1.5 rounded-[--radius-md] border border-dashed border-[--color-border-strong] bg-[--color-bg-elev] px-4 py-6 text-center transition hover:border-[--color-fg-faint]"
            >
              <FileSpreadsheet
                size={22}
                strokeWidth={1.4}
                className="text-[--color-fg-faint]"
              />
              <span className="text-sm">选择 .csv 或 .xlsx 数据文件（可多选）</span>
            </button>
          )}
        </section>
      </div>

      <div className="flex items-center gap-4">
        <button
          type="button"
          className="btn btn-primary"
          disabled={isBusy || !manifest || dataFiles.length === 0}
          onClick={submit}
        >
          {isBusy ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              <span>评测中…</span>
            </>
          ) : (
            <>
              <Upload size={14} />
              <span>开始批量评测</span>
            </>
          )}
        </button>

        {phase.name === "done" ? (
          <div className="flex items-center gap-2 text-sm text-[--color-accent]">
            <CheckCircle2 size={16} />
            <span className="nums">
              {phase.tasks} 个任务完成
              {phase.errors > 0 ? `，${phase.errors} 个错误` : ""}
            </span>
            <Download size={14} className="text-[--color-fg-faint]" />
          </div>
        ) : null}

        {phase.name === "error" ? (
          <div className="flex items-center gap-2 text-sm text-[--color-danger]">
            <AlertCircle size={16} />
            <span>{phase.message}</span>
          </div>
        ) : null}
      </div>
    </main>
  );
}
