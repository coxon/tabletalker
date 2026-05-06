# evaluation/ · 评测集与评测脚本

> 主办方强制要求：UI 必须支持上传隐藏评测集 → 跑分 → 输出 results.jsonl + metrics.json。

## 目录文件

| 文件 | 说明 |
|---|---|
| `sample_eval.jsonl` | 公开评测样例（10 条），评委可用作格式参考；UI 上传同格式即可 |
| `README.md` | 本文件 |

## 评测集格式

每行一个 JSON 对象：

```jsonl
{"id": "q001", "question": "Q1 华南销售为什么环比下滑 12%？", "session_id": "s1"}
{"id": "q002", "question": "再按 BU 看，哪 3 个 BU 拖累最大？", "session_id": "s1"}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 全局唯一题目 ID |
| `question` | ✅ | 自然语言问题 |
| `session_id` | ⏳ 可选 | 同一 session 的多条题视为多轮对话；不同 session 互相独立 |
| `ground_truth` | ⏳ 可选 | 标准答案，用于自动评分（可选）；未提供则只评完成率/图表率 |

## 评测产物（自动生成）

跑完后系统输出 2 个文件，可直接在 UI 下载：

### `results.jsonl`（每条问题的答案）

```jsonl
{"id": "q001", "question": "...", "answer": "...", "has_chart": true, "latency_seconds": 2.3, "success": true, "citations": {...}}
```

### `metrics.json`（综合指标）

```json
{
  "total": 10,
  "task_completion_rate": 0.95,
  "answer_accuracy": 0.87,
  "chart_generation_rate": 0.94,
  "multi_turn_consistency": 0.93,
  "data_provenance_accuracy": 0.95,
  "avg_latency_seconds": 5.6
}
```

## 评测使用方法

### 方式 A：通过 UI（评委推荐）

1. 浏览器访问 http://<deploy-host>:8080/Table-Talker.html
2. 左侧栏 → 🧪 **批量评测**
3. 点击 "⤴ 上传新评测集" → 选择 jsonl
4. **自动开跑**，进度条 + 当前问题实时显示
5. 跑完点 "⤓ results.jsonl" 和 "⤓ metrics.json" 下载

### 方式 B：通过命令行（开发自测）

```bash
# 一键自测脚本
bash backend-skeleton/tools/test_eval.sh

# 或手动
curl -F "file=@evaluation/sample_eval.jsonl" http://localhost:8000/api/eval/run
# 拿到 task_id 后
curl -N http://localhost:8000/api/eval/stream/<task_id>
curl http://localhost:8000/api/eval/download/<task_id>/results -o results.jsonl
curl http://localhost:8000/api/eval/download/<task_id>/metrics -o metrics.json
```

## 评分维度（与主办方约定）

| 指标 | 权重提示 | 计算方式 |
|---|---|---|
| 任务完成率 | 高 | 没报错 + 有答案 / 总数 |
| 答案正确率 | 高 | 含 ground_truth 时按精确/模糊匹配；无则 LLM-as-judge |
| 图表生成率 | 中 | 该出图的问题里出了图的比例 |
| 多轮一致性 | 中 | 多轮场景里前后矛盾的反向指标 |
| 引用准确率 | 高 | 报告中标注的"数据集+列+SQL"是否对得上 |
| 平均耗时 | 低 | 主办方表示性能权重低 |
