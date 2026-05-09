# 提交契约

官方赛题 4 §5.1 规定了每次分析响应的 JSON 结构。本文件记录当前后端必须返回的字段和语义。
契约一旦实现，不允许静默改字段名或类型。

## 1. 评测相关接口

```text
POST /v1/analyze                 主分析，multipart/form-data
POST /v1/follow-up               追问，application/json
GET  /reports/{id}.html          HTML 报告
GET  /api/reports/{id}/download  前端下载代理，返回 attachment HTML
```

辅助接口：

```text
POST   /v1/batch                 批量评测
GET    /v1/sessions              历史列表
GET    /v1/sessions/{id}          历史详情
DELETE /v1/sessions/{id}          删除历史
GET    /health                   健康检查
GET    /version                  版本信息
```

## 2. 响应结构

```json
{
  "id": "eval_analysis_a3f12b8c",
  "report_html_url": "https://your-domain.com/reports/eval_analysis_a3f12b8c.html",
  "summary": "针对顾客购物行为数据，从年龄、季节、促销三个维度交叉分析，识别出 55+ 客群为高价值但订阅率偏低的客群...",
  "findings": [
    {
      "title": "55 岁以上顾客客单价显著高于年轻客群",
      "detail": "55+ 客群平均客单价 59.31，较 18-34 岁组高 15.8%。",
      "evidence": [
        {
          "dataset": "顾客购物行为分析",
          "table": "customer_shopping_behavior.csv",
          "columns": ["Age", "Purchase Amount (USD)"],
          "filters": "Age >= 55",
          "aggregation": "mean(Purchase Amount (USD))",
          "value": 59.31,
          "row_count": 847
        }
      ]
    }
  ],
  "charts": [
    {"type": "柱状图", "title": "各年龄段平均客单价", "html_anchor": "#chart-age-bar"}
  ],
  "recommendations": [
    "针对 55+ 客群推出长期会员订阅福利，提升订阅转化。"
  ],
  "is_refusal": false,
  "confidence": 0.88
}
```

## 3. 字段说明

| 字段 | 类型 | 要求 |
|---|---|---|
| `id` | string | 首轮为 `eval_analysis_*`，追问为 `eval_follow_*` |
| `report_html_url` | string | 可访问的 HTML 报告 URL |
| `summary` | string | 中文摘要，开门见山，不写模板套话 |
| `findings` | array | 关键发现；非拒答时至少 1 条 |
| `recommendations` | array | 基于关键发现的业务建议 |
| `is_refusal` | boolean | 是否拒答 |
| `confidence` | number | 0-1，可选观测字段 |

### `finding` 关键发现

| 字段 | 类型 | 要求 |
|---|---|---|
| `title` | string | 简短标题 |
| `detail` | string | 包含实际数字和解释 |
| `evidence` | array | 每条关键发现至少 1 条证据 |

### `evidence` 证据

| 字段 | 类型 | 要求 |
|---|---|---|
| `dataset` | string | 数据集名，尽量与官方目录名一致 |
| `table` | string | 文件名，多表数据集必须明确 |
| `columns` | array | 原始字段名，保留空格、括号、大小写 |
| `filters` | string | 可复现过滤条件 |
| `aggregation` | string | 聚合表达式，如 `mean(...)` / `count(*)` |
| `value` | number/string | typed-op 执行得到的真实结果，不能推断 |
| `row_count` | int/null | 参与计算的样本数 |
| `sampling_rate` | number/null | 如采样，必须披露 |

## 4. 图表

`charts[].html_anchor` 必须能在 HTML 中找到对应 `<div id="...">`。
当前实现内联 ECharts 运行时，不依赖 CDN。

官方枚举包含：柱状图、折线图、饼图、散点图、热力图、箱线图。
当前回归观测到：柱状图、折线图、饼图、散点图。

## 5. 追问

追问请求体：

```json
{
  "parent_id": "eval_analysis_xxx",
  "question": "刚才提到的高价值客群中，他们最偏好的类别是什么？"
}
```

追问响应结构与主分析相同，但 `id` 是新的 follow-up id。
父轮报告 URL 继续可访问，追问会生成自己的报告 URL。

## 6. 拒答

拒答时：

- `is_refusal=true`
- `summary` 使用 `docs/refusal-policy.md` 中的固定中文话术
- `findings` / `charts` 可为空
- 仍生成 HTML 报告，避免 `report_html_url` 断链

## 7. 版本

当前契约对应官方 README v1.0（2026-04-28）。
