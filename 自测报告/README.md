# 自测报告/ · 评测报告与 metrics

> 主办方强制要求：包含 `metrics` 评估文件，关键指标举例：正确率、拒答率、引用精确度等。

## 文件清单

| 文件 | 状态 | 说明 |
|---|---|---|
| `metrics` | ⏳ 待生成 | 跑公开评测集后输出（**必选**）|
| `metrics.json` | ⏳ 待生成 | JSON 格式，与 `metrics` 同源 |
| `self_test_report.md` | ⏳ 待生成 | 自测报告正文（含错例分析、优化前后对比）|
| `self_test_report.pdf` | ⏳ 待生成 | PDF 版本 |
| `README.md` | ✅ | 本文件 |

## 生成步骤（5/9 前完成）

```bash
# 1. 切到真实模式（依赖网关）
sed -i '' 's/MOCK_MODE=true/MOCK_MODE=false/' .env

# 2. 拷贝主办方公开评测集到 evaluation/public_eval.jsonl

# 3. 跑评测
make eval
# 或直接：bash backend-skeleton/tools/test_eval.sh evaluation/public_eval.jsonl

# 4. metrics 输出到 自测报告/metrics 和 metrics.json
```

## 报告章节建议

参考 [`架构文档/Table-Talker-PRD-v1.0.md`](../架构文档/Table-Talker-PRD-v1.0.md) 第 4 章 KPI：

1. **执行摘要**：核心指标 + 一句话总结
2. **指标速查表**（与 metrics.json 对齐）
3. **错例分类**（schema 错 / SQL 错 / 答案抽取错 / 图表错）
4. **优化前后对比**（baseline vs. final）
5. **多模型对比**（qwen vs deepseek vs MiniMax 等）
6. **附录：详细数据**

## 关键指标说明

| 指标 | 定义 | 目标 |
|---|---|---|
| `task_completion_rate` | 没报错 + 有答案 / 总数 | ≥ 0.95 |
| `answer_accuracy` | 答案正确率（精确匹配 / LLM-as-judge）| ≥ 0.85 |
| `chart_generation_rate` | 该出图的问题里出了图的比例 | ≥ 0.90 |
| `multi_turn_consistency` | 多轮场景前后一致性 | ≥ 0.85 |
| `data_provenance_accuracy` | 引用溯源准确率 | ≥ 0.95 |
| `avg_latency_seconds` | 平均耗时 | < 8s |
