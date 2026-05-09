"use client";

import { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { 
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
import type { AnalyzeResponse, Turn, AnalyzePhase } from "../../lib/contract";

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? body.error ?? response.statusText;
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

export default function V2AnalyzePage() {
  const [file, setFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<AnalyzePhase>({ name: "idle" });
  const [turns, setTurns] = useState<Turn[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (disabled) return;
    const dropped = e.dataTransfer.files[0];
    if (dropped && (dropped.name.endsWith(".csv") || dropped.name.endsWith(".xlsx"))) {
      setFile(dropped);
    } else {
      toast.error("仅支持 CSV 或 Excel 格式文件");
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
    }
  };

  const resetSession = () => {
    setTurns([]);
    setFile(null);
    setQuestion("");
    setPhase({ name: "idle" });
  };

  const submitAnalysis = async () => {
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
  };

  const submitFollowUp = async () => {
    if (!parent || !followUpParentId) return;
    const trimmed = question.trim();
    if (!trimmed) return;
    setPhase({ name: "follow_up" });
    try {
      const response = await fetch("/api/follow-up", {
        method: "POST",
        headers: { "content-type": "application/json" },
        // parent_id = most recent turn's id (not the original turns[0]).
        // The backend's session store carries forward findings, cohort
        // definitions, and chart anchors from the direct parent, so a
        // second follow-up referencing "that group" means the cohort
        // named in turn 2, not turn 1.
        body: JSON.stringify({ parent_id: followUpParentId, question: trimmed }),
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
  };

  const disabled = isBusy;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 max-w-[1400px] mx-auto">
      {/* Left Column - Main Interaction Area */}
      <div className="xl:col-span-2 space-y-6">
        
        {!parent ? (
          // ================== IDLE VIEW (NO SESSION) ==================
          <>
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
              <p className="text-sm text-slate-500 mb-6">上传数据文件，提出你的分析问题，让 AI 帮你从数据中发现有价值的洞察</p>
              
              {/* Step 1 */}
              <div className="mb-6">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-indigo-100 text-indigo-600 text-xs font-bold">1</span>
                    <h3 className="font-semibold text-slate-800">上传数据文件</h3>
                  </div>
                  <div className="flex items-center gap-4 text-xs">
                    <span className="text-slate-400">已上传 {file ? '1' : '0'} 个文件</span>
                    <button onClick={() => setFile(null)} className="text-indigo-600 flex items-center gap-1 hover:text-indigo-700 transition-colors">
                      <X size={14} /> 清空
                    </button>
                  </div>
                </div>
                <p className="text-xs text-slate-400 mb-4 ml-8">支持 CSV、Excel 格式，单文件最大 200MB</p>
                
                <div className="ml-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {file ? (
                    <div className="flex items-center justify-between p-3 rounded-lg border border-indigo-200 bg-indigo-50/50">
                      <div className="flex items-center gap-3 overflow-hidden">
                        <FileSpreadsheet className="text-emerald-500 shrink-0" size={20} />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-700 truncate">{file.name}</p>
                          <p className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</p>
                        </div>
                      </div>
                      <button onClick={() => setFile(null)} className="text-slate-400 hover:text-slate-600 p-1">
                        <X size={16} />
                      </button>
                    </div>
                  ) : null}

                  {/* Upload Dropzone */}
                  <div 
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleFileDrop}
                    onClick={() => fileInputRef.current?.click()}
                    className={`flex flex-col items-center justify-center p-4 rounded-lg border-2 border-dashed transition-colors cursor-pointer min-h-[72px]
                      ${disabled ? 'border-slate-200 bg-slate-50 cursor-not-allowed' : 'border-slate-200 hover:border-indigo-400 hover:bg-indigo-50/30'}`}
                  >
                    <div className="flex items-center gap-2 text-slate-500">
                      <UploadCloud size={18} />
                      <span className="text-sm font-medium">添加文件</span>
                    </div>
                    <span className="text-xs text-slate-400 mt-1">或将文件拖到此处</span>
                    <input 
                      type="file" 
                      ref={fileInputRef} 
                      className="hidden" 
                      accept=".csv, .xlsx"
                      onChange={handleFileSelect}
                      disabled={disabled}
                    />
                  </div>
                </div>
              </div>

              {/* Step 2 */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="flex items-center justify-center w-6 h-6 rounded-full bg-indigo-100 text-indigo-600 text-xs font-bold">2</span>
                  <h3 className="font-semibold text-slate-800">提出你的问题</h3>
                </div>
                
                <div className="ml-8 relative">
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    disabled={disabled}
                    placeholder="例如：2024 年各产品类别的销售额趋势如何？哪些产品表现最好？"
                    className="w-full h-28 p-4 rounded-xl border border-slate-200 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-indigo-100 focus:border-indigo-400 outline-none resize-none transition-all disabled:opacity-60 text-sm"
                  />
                  <div className="absolute bottom-3 right-3 text-xs text-slate-400">
                    {question.length}/500
                  </div>
                </div>

                <div className="ml-8 mt-4 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs flex-wrap">
                    <span className="text-slate-500 mr-1">推荐问题：</span>
                    {["各产品线销售趋势如何？", "哪个地区贡献最大？", "高价值客户有哪些特征？", "库存周转情况如何？"].map((q) => (
                      <button 
                        key={q} 
                        onClick={() => setQuestion(q)}
                        disabled={disabled}
                        className="px-3 py-1.5 rounded-full border border-indigo-100 text-indigo-600 bg-indigo-50/50 hover:bg-indigo-100 transition-colors disabled:opacity-50"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                  
                  <button
                    onClick={submitAnalysis}
                    disabled={disabled || !file || !question.trim()}
                    className="flex items-center gap-2 bg-indigo-600 text-white px-6 py-2.5 rounded-lg font-medium text-sm hover:bg-indigo-700 focus:ring-4 focus:ring-indigo-100 transition-all disabled:opacity-50 disabled:cursor-not-allowed shrink-0 ml-4"
                  >
                    {isBusy ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        分析中...
                      </>
                    ) : (
                      <>
                        <Play size={16} fill="currentColor" />
                        开始分析
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

            {/* Static Example Mock (Visible only when idle) */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 opacity-60 grayscale-[0.5] pointer-events-none">
              <div className="flex items-center justify-between mb-6 border-b border-slate-100 pb-4">
                <div className="flex items-center gap-3">
                  <h3 className="font-bold text-slate-800 text-lg">最近分析示例</h3>
                  <span className="text-xs text-indigo-600">查看全部历史 <ChevronRight className="inline" size={14} /></span>
                </div>
              </div>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <span className="px-2.5 py-1 rounded-md bg-emerald-100 text-emerald-700 text-xs font-medium">已完成</span>
                  <h4 className="font-semibold text-slate-800">2024 年各产品类别的销售额趋势分析</h4>
                </div>
              </div>
              <div className="w-full bg-slate-50 rounded-xl border border-slate-100 h-[200px] flex items-center justify-center text-slate-400 text-sm">
                [示例图表区域]
              </div>
            </div>
          </>
        ) : (
          // ================== ACTIVE SESSION VIEW ==================
          <div className="space-y-6">
            {/* Header / Active File */}
            <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-indigo-50 rounded-lg text-indigo-600"><FileSpreadsheet size={20}/></div>
                <div>
                  <div className="text-sm font-bold text-slate-800">{file?.name}</div>
                  <div className="text-xs text-slate-500">当前分析会话正在进行中...</div>
                </div>
              </div>
              <button onClick={resetSession} className="text-sm text-indigo-600 hover:text-indigo-700 font-medium flex items-center gap-1 bg-indigo-50 px-3 py-1.5 rounded-lg transition-colors">
                <Plus size={16}/> 开启新分析
              </button>
            </div>

            {/* Conversation Turns */}
            <AnimatePresence initial={false}>
              {turns.map((turn, i) => (
                <V2TurnCard key={`${turn.response.id}-${i}`} turn={turn} index={i} />
              ))}
              
              {/* Skeleton/Loading states */}
              {(phase.name === "analyzing" || phase.name === "follow_up") && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 flex flex-col items-center justify-center min-h-[160px]"
                >
                  <div className="w-8 h-8 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-4" />
                  <span className="text-sm font-medium text-slate-700">
                    {phase.name === "analyzing" ? "正在深入分析数据，首次分析大约需要 30-60 秒..." : "正在基于上下文生成追问回答..."}
                  </span>
                  <span className="text-xs text-slate-400 mt-2">TableTalker 正在调用沙箱执行代码</span>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Follow-up Input */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 sticky bottom-6 z-10 mt-10">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">继续追问</span>
              </div>
              <div className="relative">
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  disabled={disabled || parent.is_refusal}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      submitFollowUp();
                    }
                  }}
                  placeholder={parent.is_refusal ? "本数据集已被拒答，继续追问只会得到同样的拒答说明。" : "向这份数据提问，例如：那女性顾客呢？ (⌘+Enter 发送)"}
                  className="w-full h-24 p-3 pr-24 rounded-lg border border-slate-200 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-indigo-100 focus:border-indigo-400 outline-none resize-none transition-all disabled:opacity-60 text-sm"
                />
                <div className="absolute bottom-3 right-3">
                  <button
                    onClick={submitFollowUp}
                    disabled={disabled || parent.is_refusal || !question.trim()}
                    className="flex items-center gap-1.5 bg-indigo-600 text-white px-4 py-2 rounded-md text-sm hover:bg-indigo-700 transition-all disabled:opacity-50"
                  >
                    <Send size={14} />
                    发送
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Right Column - Mocks (Static) */}
      <div className="space-y-6">
        {/* Capabilities Card */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <h3 className="font-bold text-slate-800 mb-4">TableTalker 能做什么</h3>
          <div className="space-y-4">
            <div className="flex gap-3">
              <div className="p-2 rounded-lg bg-purple-50 text-purple-600 shrink-0 h-fit"><Sparkles size={18} /></div>
              <div>
                <h4 className="text-sm font-semibold text-slate-800">自动数据剖析</h4>
                <p className="text-xs text-slate-500 mt-1">智能识别字段类型、缺失值、分布等特征</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="p-2 rounded-lg bg-blue-50 text-blue-600 shrink-0 h-fit"><CheckCircle2 size={18} /></div>
              <div>
                <h4 className="text-sm font-semibold text-slate-800">智能分析规划</h4>
                <p className="text-xs text-slate-500 mt-1">将自然语言转化为可执行的分析计划</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="p-2 rounded-lg bg-emerald-50 text-emerald-600 shrink-0 h-fit"><ShieldCheck size={18} /></div>
              <div>
                <h4 className="text-sm font-semibold text-slate-800">安全执行与验证</h4>
                <p className="text-xs text-slate-500 mt-1">沙箱执行代码，确保每个结果可复算</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="p-2 rounded-lg bg-pink-50 text-pink-600 shrink-0 h-fit"><BarChart3 size={18} /></div>
              <div>
                <h4 className="text-sm font-semibold text-slate-800">生成可视化报告</h4>
                <p className="text-xs text-slate-500 mt-1">生成交互式图表与叙事摘要的 HTML 报告</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="p-2 rounded-lg bg-indigo-50 text-indigo-600 shrink-0 h-fit"><MessageSquare size={18} /></div>
              <div>
                <h4 className="text-sm font-semibold text-slate-800">多轮追问</h4>
                <p className="text-xs text-slate-500 mt-1">基于上下文继续深入分析，支持代码消解</p>
              </div>
            </div>
          </div>
        </div>

        {/* Overview Mock */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 hidden md:block">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold text-slate-800">我的数据分析概览</h3>
            <select className="text-xs bg-slate-50 border border-slate-200 rounded-md px-2 py-1 outline-none text-slate-600">
              <option>近 7 天</option>
              <option>近 30 天</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
              <div className="text-xs text-slate-500 mb-1">分析会话</div>
              <div className="text-xl font-bold text-slate-800">12</div>
              <div className="text-[10px] text-emerald-600 mt-1 flex items-center gap-0.5">↑ 20% 较上周</div>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
              <div className="text-xs text-slate-500 mb-1">完成分析</div>
              <div className="text-xl font-bold text-slate-800">10</div>
              <div className="text-[10px] text-emerald-600 mt-1 flex items-center gap-0.5">↑ 25% 较上周</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// V2 Turn Card Component
// ---------------------------------------------------------------------------
function V2TurnCard({ turn, index }: { turn: Turn; index: number }) {
  const { response, question, kind } = turn;
  const isParent = kind === "parent";
  const [reportOpen, setReportOpen] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`bg-white rounded-xl border ${isParent ? 'border-slate-200' : 'border-indigo-100/50'} shadow-sm p-6 space-y-5`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 pb-4">
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
          <h4 className="font-semibold text-slate-800 text-lg leading-snug">{question}</h4>
        </div>
        <div className="text-xs text-slate-400 font-mono bg-slate-50 px-2 py-1 rounded border border-slate-100">
          ID: {response.id}
        </div>
      </div>

      {/* Summary */}
      <div className="text-sm text-slate-700 leading-relaxed bg-slate-50 p-4 rounded-lg border border-slate-100">
        <p className="whitespace-pre-wrap">{response.summary}</p>
      </div>

      {/* Findings */}
      {response.findings.length > 0 && (
        <div className="space-y-3">
          <h5 className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <Sparkles size={14}/> 关键发现
          </h5>
          <div className="grid gap-3">
            {response.findings.map((f, i) => (
              <div key={i} className="border border-slate-100 rounded-lg p-3.5 bg-white">
                <p className="text-sm font-semibold text-slate-800 mb-1">{f.title}</p>
                <p className="text-xs text-slate-500 leading-relaxed">{f.detail}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {response.recommendations.length > 0 && (
        <div className="space-y-3 mt-4">
          <h5 className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <Activity size={14}/> 建议
          </h5>
          <ul className="list-disc pl-5 space-y-1.5 text-sm text-slate-600">
            {response.recommendations.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Iframe Report (Charts) */}
      {!response.is_refusal && response.charts.length > 0 && (
        <div className="mt-6 pt-4 border-t border-slate-100">
          <div className="flex items-center justify-between mb-3">
            <button 
              onClick={() => setReportOpen(!reportOpen)}
              className="flex items-center gap-1 text-xs font-bold text-slate-500 hover:text-slate-800 uppercase tracking-wider transition-colors cursor-pointer"
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
                <div className={`w-full mt-3 bg-slate-50 rounded-xl overflow-hidden border border-slate-200 relative ${isParent ? 'min-h-[550px]' : 'min-h-[400px]'}`}>
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
