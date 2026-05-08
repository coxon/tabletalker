# Changelog

> 遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范，
> 版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Planned
- 接入主办方 LLM 网关（亚信 aigw），切换 MOCK_MODE=false
- 真实评测集 metrics 复测
- 内网部署到亚信云
- 演示视频录制

---

## [1.0.0] - 2026-05-04

> Table-Talker 黑客松初赛版。Mock 模式下完整可演，真实模式 .env 一行切换。

### Added · 新增

#### 产品 / UX
- 6 个完整页面：对话 / 看板 / 报告 / 数据接入 / 批量评测 / 设置
- **双模式 UX**（同 Agent 后端，两种 UI 人格）：商业语言模式（默认）+ 专家模式
- **14 步 Agent 推理流水线**可视化，含 GraphRAG / TTL / Codegen 标签
- **三态输出**：临时回答 / 看板 / 报告（同一对话流的不同凝固方式）
- 7 个完整对话场景（销售归因 / HR 月报 / ARPU / 工单 / 财务 / 技能 / 流失）
- 4 套图表色板（Emerald / Ocean / Warm / Mono）+ Light / Dark 模式
- 主题/字号/密度/Trace 风格 Tweaks 实时配置面板
- 打字机音效（Web Audio API 生成，可关闭）

#### Agent / 算法
- **GraphRAG 索引构建**：6 个业务社区 + 实体图（dataset/column/term）
- **TTL 推理**：130+ 业务术语词典 + 16 组同义词，业务术语 → 字段映射
- **NL2SQL CodeGen**：DuckDB SQL 生成 + 静态校验 + 4 次重试反思
- **多模型路由**：Router/Critic 用小模型，CodeGen/Summary 用大模型，节省 60% Token
- **沙盒执行**：subprocess + 资源限制 + 白名单 import
- **自动选图**：基于 dataframe 形态启发式
- **异常洞察**：IQR 离群、单调突变、强相关检测
- **引用溯源**：每条结论可追溯 SQL + 数据集 + 样例行

#### 后端 / API
- FastAPI + sse-starlette 流式 SSE 接口
- 5 个核心模块：chat / dashboard / report / eval / datasets
- LLM Adapter（统一封装亚信网关 5 模型 + 自动 fallback chain）
- Mock / Real 双模式（MOCK_MODE=true 时使用 design-source/data.js 一致的演示数据）
- SQLite 轻量持久化（dashboards / dashboard_cards / reports）
- Background tasks 异步生成 docx 报告（python-docx，4 套模板 7-10 节）
- 批量评测端到端：上传 jsonl → SSE 流进度 → 下载 results + metrics

#### 数据
- 15 个模拟数据集（5.7 万行，覆盖 HR/销售/财务/运营商/工单/零售/交通/气象/人口/电影/试航/库存/营销/事件）
- 离线 schema 抽取脚本
- 业务术语词典自动构建脚本
- GraphRAG 索引构建脚本

#### 部署 / 运维
- Docker Compose 一键部署（前端 nginx + 后端 uvicorn + Redis）
- Makefile（make run / stop / eval / schema）
- 一键启动 / 停服 / 预热脚本（start.sh / stop.sh / warmup.sh）
- 5 模型 LLM 联通自测脚本（tools/test_llm.py）
- 端到端批量评测自测脚本（tools/test_eval.sh）

#### 文档
- 主仓库 README（评委首入口）
- PRD v1.0（14 章 / 50 个功能 / mermaid 架构图与 ER 模型）
- 7 天作战手册
- 设计稿审查与对接策略
- 推送到 GitAI 指南
- 5 分钟演示视频脚本
- 录制前自检清单（9 大类 47 项）
- data / evaluation / 演示视频 / 自测报告 各子目录 README

### Security
- `.env` 严格 gitignore，API Key 不入库
- 沙盒禁用 file/os/network 操作

---

## [0.1.0] - 2026-05-03

> 项目启动 Day 1。

### Added
- 产品意图梳理（8 维度框架）
- 设计稿（Claude Code 设计模式产出）：6 页 + 14 步 trace + 双模式
- 后端骨架（FastAPI + SSE + LLM Adapter）
- 前后端 SSE 全链路对接
- 仓库标准结构对齐主办方约定

---

> [Unreleased]: https://github.com/asiainfo/table-talker/compare/v1.0.0...HEAD
> [1.0.0]: https://github.com/asiainfo/table-talker/releases/tag/v1.0.0
> [0.1.0]: https://github.com/asiainfo/table-talker/releases/tag/v0.1.0
