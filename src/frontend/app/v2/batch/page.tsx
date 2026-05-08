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
  Info,
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

export default function V2BatchPage() {
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
    <div className="max-w-[1200px] mx-auto space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-800">批量处理</h2>
        <p className="text-sm text-slate-500 mt-1">上传 manifest 和数据文件，一次性运行多个分析任务并导出 xlsx 结果。</p>
      </div>

      {/* Manifest Format Info */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg bg-blue-50 text-blue-600 shrink-0">
            <Info size={18} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-800 mb-2">Manifest 格式说明</h3>
            <div className="text-sm text-slate-600 leading-relaxed space-y-1.5">
              <p>Manifest 文件为 JSONL 或 CSV 格式，每行描述一个评测任务。</p>
              <p className="font-mono text-xs text-slate-500 bg-slate-50 px-3 py-2 rounded-lg border border-slate-100">
                {`{"file": "sales.csv", "question": "哪个月销售额最高？"}`}
              </p>
              <p>
                字段：<code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded">file</code>（数据文件名）、
                <code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded">question</code>（分析问题）。
                可选：<code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded">extra_files</code>、
                <code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded">sampling_rate</code>。
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Upload Area */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {/* Manifest Upload */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">Manifest 文件</h3>
          <input
            ref={manifestRef}
            type="file"
            accept=".jsonl,.csv"
            onChange={handleManifestChange}
            disabled={isBusy}
            className="sr-only"
          />
          {manifest ? (
            <div className="flex items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50/50 px-4 py-3">
              <FileText size={18} className="shrink-0 text-indigo-600" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-700">
                {manifest.name}
              </span>
              <span className="text-xs text-slate-400">
                {(manifest.size / 1024).toFixed(1)} KB
              </span>
              <button
                type="button"
                onClick={() => setManifest(null)}
                disabled={isBusy}
                className="rounded p-1 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => manifestRef.current?.click()}
              disabled={isBusy}
              className="flex w-full min-h-[120px] flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 bg-slate-50/50 px-4 py-6 text-center transition hover:border-indigo-400 hover:bg-indigo-50/30 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Upload size={24} strokeWidth={1.4} className="text-slate-400" />
              <span className="text-sm text-slate-600 font-medium">选择 .jsonl 或 .csv manifest</span>
              <span className="text-xs text-slate-400">点击或拖拽文件到此处</span>
            </button>
          )}
        </div>

        {/* Data Files Upload */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">数据文件</h3>
            {dataFiles.length > 0 && (
              <span className="text-xs text-slate-400">{dataFiles.length} 个文件</span>
            )}
          </div>
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
            <div className="flex flex-col gap-2">
              <div className="max-h-[200px] overflow-auto flex flex-col gap-1.5">
                {dataFiles.map((f) => (
                  <div
                    key={f.name}
                    className="flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2"
                  >
                    <FileSpreadsheet size={14} className="shrink-0 text-emerald-500" />
                    <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{f.name}</span>
                    <span className="text-xs text-slate-400">{(f.size / 1024).toFixed(1)} KB</span>
                    <button
                      type="button"
                      onClick={() => removeFile(f.name)}
                      disabled={isBusy}
                      className="rounded p-0.5 text-slate-400 hover:text-slate-600 transition-colors"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={() => filesRef.current?.click()}
                disabled={isBusy}
                className="self-start text-xs font-medium text-indigo-600 hover:text-indigo-700 transition-colors mt-1"
              >
                + 添加更多文件
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => filesRef.current?.click()}
              disabled={isBusy}
              className="flex w-full min-h-[120px] flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 bg-slate-50/50 px-4 py-6 text-center transition hover:border-indigo-400 hover:bg-indigo-50/30 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FileSpreadsheet size={24} strokeWidth={1.4} className="text-slate-400" />
              <span className="text-sm text-slate-600 font-medium">选择 .csv 或 .xlsx 数据文件（可多选）</span>
              <span className="text-xs text-slate-400">点击或拖拽文件到此处</span>
            </button>
          )}
        </div>
      </div>

      {/* Submit & Status */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 flex items-center gap-4">
        <button
          type="button"
          disabled={isBusy || !manifest || dataFiles.length === 0}
          onClick={submit}
          className="flex items-center gap-2 bg-indigo-600 text-white px-6 py-2.5 rounded-lg font-medium text-sm hover:bg-indigo-700 focus:ring-4 focus:ring-indigo-100 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isBusy ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              评测中…
            </>
          ) : (
            <>
              <Upload size={16} />
              开始批量评测
            </>
          )}
        </button>

        {phase.name === "done" ? (
          <div className="flex items-center gap-2 text-sm text-emerald-600 bg-emerald-50 px-4 py-2 rounded-lg border border-emerald-100">
            <CheckCircle2 size={16} />
            <span>
              {phase.tasks} 个任务完成
              {phase.errors > 0 ? `，${phase.errors} 个错误` : ""}
            </span>
            <Download size={14} className="text-emerald-400 ml-1" />
          </div>
        ) : null}

        {phase.name === "error" ? (
          <div className="flex items-center gap-2 text-sm text-rose-600 bg-rose-50 px-4 py-2 rounded-lg border border-rose-100">
            <AlertCircle size={16} />
            <span>{phase.message}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
