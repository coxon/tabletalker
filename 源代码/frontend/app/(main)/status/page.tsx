"use client";

import { useEffect, useState } from "react";
import {
  Server,
  Monitor,
  CheckCircle2,
  XCircle,
  Loader2,
  Cpu,
  Clock,
  Globe,
  Package,
  RefreshCw,
} from "lucide-react";

interface BackendInfo {
  name: string;
  version: string;
}

interface HealthInfo {
  ok: boolean;
}

interface StatusCheck {
  label: string;
  status: "ok" | "error" | "loading";
  detail?: string;
}

function backendBase(): string {
  if (typeof window === "undefined") return "http://localhost:8000";
  const backendPort = window.location.port === "3000" ? "8000" : window.location.port;
  return `${window.location.protocol}//${window.location.hostname}:${backendPort}`;
}

export default function V2StatusPage() {
  const [backendVersion, setBackendVersion] = useState<BackendInfo | null>(null);
  const [backendHealth, setBackendHealth] = useState<HealthInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const runChecks = async () => {
    setLoading(true);
    const base = backendBase();

    // Check /version
    try {
      const res = await fetch(`${base}/version`, { signal: AbortSignal.timeout(5000) });
      if (res.ok) {
        const data = await res.json();
        setBackendVersion(data);
      } else {
        setBackendVersion(null);
      }
    } catch {
      setBackendVersion(null);
    }

    // Check /health
    try {
      const res = await fetch(`${base}/health`, { signal: AbortSignal.timeout(5000) });
      if (res.ok) {
        const data = await res.json();
        setBackendHealth(data);
      } else {
        setBackendHealth(null);
      }
    } catch {
      setBackendHealth(null);
    }

    setLastChecked(new Date());
    setLoading(false);
  };

  useEffect(() => {
    runChecks();
  }, []);

  const checks: StatusCheck[] = [
    {
      label: "前端服务 (Next.js)",
      status: "ok",
      detail: `运行中 · ${typeof window !== "undefined" ? window.location.origin : ""}`,
    },
    {
      label: "后端 API 服务 (FastAPI)",
      status: loading ? "loading" : backendHealth?.ok ? "ok" : "error",
      detail: loading
        ? "检查中..."
        : backendHealth?.ok
          ? `健康 · ${backendBase()}`
          : `无法连接 · ${backendBase()}`,
    },
    {
      label: "后端版本",
      status: loading ? "loading" : backendVersion ? "ok" : "error",
      detail: loading
        ? "检查中..."
        : backendVersion
          ? `${backendVersion.name} v${backendVersion.version}`
          : "无法获取版本信息",
    },
    {
      label: "报告服务",
      status: loading ? "loading" : backendHealth?.ok ? "ok" : "error",
      detail: loading
        ? "检查中..."
        : backendHealth?.ok
          ? "在线 · 报告通过后端内存存储提供"
          : "不可用",
    },
  ];

  return (
    <div className="max-w-[1200px] mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800">系统状态</h2>
          <p className="text-sm text-slate-500 mt-1">查看前后端服务的运行状态与健康信息。</p>
        </div>
        <button
          onClick={runChecks}
          disabled={loading}
          className="flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-700 bg-indigo-50 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50"
        >
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          刷新状态
        </button>
      </div>

      {/* Overall Status Banner */}
      <div className={`rounded-xl border shadow-sm p-6 flex items-center gap-4 ${
        loading
          ? "bg-slate-50 border-slate-200"
          : backendHealth?.ok
            ? "bg-emerald-50 border-emerald-200"
            : "bg-rose-50 border-rose-200"
      }`}>
        <div className={`p-3 rounded-full ${
          loading
            ? "bg-slate-200 text-slate-500"
            : backendHealth?.ok
              ? "bg-emerald-200 text-emerald-700"
              : "bg-rose-200 text-rose-700"
        }`}>
          {loading ? (
            <Loader2 size={24} className="animate-spin" />
          ) : backendHealth?.ok ? (
            <CheckCircle2 size={24} />
          ) : (
            <XCircle size={24} />
          )}
        </div>
        <div>
          <h3 className={`text-lg font-bold ${
            loading ? "text-slate-700" : backendHealth?.ok ? "text-emerald-800" : "text-rose-800"
          }`}>
            {loading ? "正在检查系统状态..." : backendHealth?.ok ? "所有服务运行正常" : "部分服务异常"}
          </h3>
          <p className="text-sm text-slate-500 mt-0.5">
            {lastChecked
              ? `上次检查: ${lastChecked.toLocaleTimeString("zh-CN")}`
              : "正在执行首次检查"}
          </p>
        </div>
      </div>

      {/* Service Check Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {checks.map((check) => (
          <div key={check.label} className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 flex items-start gap-4">
            <div className={`p-2 rounded-lg shrink-0 ${
              check.status === "ok"
                ? "bg-emerald-50 text-emerald-600"
                : check.status === "error"
                  ? "bg-rose-50 text-rose-600"
                  : "bg-slate-100 text-slate-400"
            }`}>
              {check.status === "ok" ? (
                <CheckCircle2 size={20} />
              ) : check.status === "error" ? (
                <XCircle size={20} />
              ) : (
                <Loader2 size={20} className="animate-spin" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <h4 className="text-sm font-semibold text-slate-800">{check.label}</h4>
              <p className="text-xs text-slate-500 mt-1 truncate">{check.detail}</p>
            </div>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${
              check.status === "ok"
                ? "bg-emerald-100 text-emerald-700"
                : check.status === "error"
                  ? "bg-rose-100 text-rose-700"
                  : "bg-slate-100 text-slate-500"
            }`}>
              {check.status === "ok" ? "正常" : check.status === "error" ? "异常" : "检查中"}
            </span>
          </div>
        ))}
      </div>

      {/* System Info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Frontend Info */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <div className="flex items-center gap-2 mb-4">
            <Monitor size={18} className="text-indigo-600" />
            <h3 className="font-bold text-slate-800">前端服务</h3>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Package size={14} /> 框架</span>
              <span className="font-medium text-slate-700">Next.js (React)</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Globe size={14} /> 地址</span>
              <span className="font-mono text-xs text-slate-700">{typeof window !== "undefined" ? window.location.origin : "-"}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Cpu size={14} /> 运行环境</span>
              <span className="font-medium text-slate-700">{process.env.NODE_ENV || "development"}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Clock size={14} /> 状态</span>
              <span className="inline-flex items-center gap-1 text-emerald-600 font-medium">
                <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                运行中
              </span>
            </div>
          </div>
        </div>

        {/* Backend Info */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <div className="flex items-center gap-2 mb-4">
            <Server size={18} className="text-indigo-600" />
            <h3 className="font-bold text-slate-800">后端服务</h3>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Package size={14} /> 框架</span>
              <span className="font-medium text-slate-700">FastAPI (Python)</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Globe size={14} /> 地址</span>
              <span className="font-mono text-xs text-slate-700">{backendBase()}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Package size={14} /> 版本</span>
              <span className="font-medium text-slate-700">
                {backendVersion ? `v${backendVersion.version}` : loading ? "..." : "未知"}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 flex items-center gap-2"><Clock size={14} /> 状态</span>
              {loading ? (
                <span className="inline-flex items-center gap-1 text-slate-400 font-medium">
                  <Loader2 size={14} className="animate-spin" /> 检查中
                </span>
              ) : backendHealth?.ok ? (
                <span className="inline-flex items-center gap-1 text-emerald-600 font-medium">
                  <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                  运行中
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-rose-600 font-medium">
                  <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                  离线
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* API Endpoints */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
        <h3 className="font-bold text-slate-800 mb-4">API 端点一览</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100">
                <th className="text-left py-2 pr-4 text-xs font-bold text-slate-500 uppercase tracking-wider">端点</th>
                <th className="text-left py-2 pr-4 text-xs font-bold text-slate-500 uppercase tracking-wider">方法</th>
                <th className="text-left py-2 text-xs font-bold text-slate-500 uppercase tracking-wider">描述</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {[
                { path: "/v1/analyze", method: "POST", desc: "上传文件与问题，生成分析报告" },
                { path: "/v1/follow-up", method: "POST", desc: "对已有会话进行追问" },
                { path: "/v1/batch", method: "POST", desc: "批量评测，返回 xlsx 结果" },
                { path: "/v1/sessions", method: "GET", desc: "查询历史会话列表" },
                { path: "/v1/sessions/:id", method: "GET", desc: "查询会话详情" },
                { path: "/v1/sessions/:id", method: "DELETE", desc: "删除指定会话" },
                { path: "/reports/:id.html", method: "GET", desc: "获取渲染后的 HTML 报告" },
                { path: "/health", method: "GET", desc: "健康探针" },
                { path: "/version", method: "GET", desc: "版本信息" },
              ].map((ep) => (
                <tr key={`${ep.method}-${ep.path}`}>
                  <td className="py-2.5 pr-4 font-mono text-xs text-slate-700">{ep.path}</td>
                  <td className="py-2.5 pr-4">
                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                      ep.method === "GET" ? "bg-blue-100 text-blue-700"
                        : ep.method === "POST" ? "bg-emerald-100 text-emerald-700"
                        : "bg-rose-100 text-rose-700"
                    }`}>
                      {ep.method}
                    </span>
                  </td>
                  <td className="py-2.5 text-slate-600">{ep.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
