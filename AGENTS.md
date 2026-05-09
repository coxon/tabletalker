# AGENTS.md — TableTalker

TableTalker 是一个结构化数据智能分析 Agent：接收 CSV / Excel 文件和自然语言问题，
产出交互式 HTML 报告，并支持追问。

## 项目规则

1. **提交目录必须保留。** 按组委会要求，仓库根目录必须包含：
   `src/`、`架构文档/`、`运行脚本/`、`演示视频/`、`自测报告/`。
   `docs/` 和 `knowledge-base/` 是工程补充目录；测试在 `src/backend/tests/`。

2. **自测报告文件名不可改。** `自测报告/latest_evaluation_metrics.md`
   必须存在于仓库根目录下的这个精确路径。数字必须来自真实评测运行，
   不要手填虚高分。

3. **宁可拒答，不要幻觉。** 如果结论无法从上传数据复算，报告必须说明原因。
   相关逻辑见 `docs/refusal-policy.md`，测试主要在
   `src/backend/tests/test_analyze_api.py` 和
   `src/backend/tests/test_followup_api.py`。

4. **提交契约冻结。** `/v1/analyze` 和 `/v1/follow-up` 的响应结构以
   `docs/submission-contract.md` 为准，字段名和类型不要漂移。

5. **默认分支规则。** 组委会脚本按 `default > master > main` 顺序拉取。
   准备送测的分支必须成为仓库默认分支。

## 重要指针

`README.md` · `PRODUCT.md` · `knowledge-base/product-capabilities.md` ·
`docs/architecture.md` · `docs/submission-contract.md` ·
`docs/scoring-map.md` · `docs/refusal-policy.md` ·
`docs/session-state.md` · `架构文档/design_doc.md` ·
`自测报告/latest_evaluation_metrics.md` · `.env.example`
