# Submission contract

The official problem statement (赛题4 §5.1) defines the JSON shape every
analysis response must take. This document records that shape verbatim,
field by field, and ties each field to the module that owns its
content.

The contract is **frozen** — once a downstream PR implements it, no
silent changes. Any field rename or type change goes through a roadmap
entry and a PR that updates this file first.

## 1. Endpoint

```
POST /spreadsheet/analyze        # standard analysis (single turn)
POST /spreadsheet/follow-up      # follow-up; same shape + parent_id
GET  /reports/{id}.html          # the rendered report referenced by report_html_url
```

Request bodies are `multipart/form-data` for analyze (file + question),
`application/json` for follow-up (`{ parent_id, question }`).

## 2. Response shape

```json
{
  "id": "eval_analysis_a3f12b8c",
  "report_html_url": "https://your-domain.com/reports/eval_analysis_a3f12b8c.html",
  "summary": "针对顾客购物行为数据,从年龄、季节、促销三个维度交叉分析,识别出 55+ 客群为高价值但订阅率偏低的客群...",
  "findings": [
    {
      "title": "55 岁以上顾客客单价显著高于年轻客群",
      "detail": "55+ 客群平均客单价 ¥59.31,较 18-34 岁组高 15.8%",
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
    { "type": "柱状图", "title": "各年龄段平均客单价", "html_anchor": "#chart-age-bar" },
    { "type": "热力图", "title": "类别 × 季节销售热度", "html_anchor": "#chart-cat-season-heatmap" },
    { "type": "箱线图", "title": "促销 vs 非促销客单价分布", "html_anchor": "#chart-discount-box" }
  ],
  "recommendations": [
    "针对 55+ 客群推出长期会员订阅福利,提升订阅转化",
    "Winter 季节加大男装类目库存与广告投放"
  ],
  "is_refusal": false,
  "confidence": 0.88
}
```

## 3. Field-by-field

### `id` (string, required)

A stable identifier we generate per request. Format:
`eval_analysis_<8-hex>` for first-turn requests,
`eval_follow_<parent-suffix>_q<n>` for follow-ups. Used as the basename
for the rendered HTML file.

Owner: `app/analyze/handler.py` (PR #4).

### `report_html_url` (string, required)

Absolute URL to the rendered report. Built from `APP_PUBLIC_URL` env
(see `.env.example`) plus `/reports/{id}.html`. The report must:

- Render correctly **with no live network calls** (Plotly bundled
  inline, no remote CDNs the eval network might block).
- Stay accessible for the duration of the eval window — see the
  submission gate in `roadmap.md`.

Owner: `app/report/render.py` (PR #5).

### `summary` (string, 300–500 chars Chinese)

Plain-text narrative. Opens with the **single most important finding**
(per organizer §7.2 雷 5 — no boilerplate openings). Followed by 2–3
sentences of supporting context. No markdown.

Owner: planner's `finish` step (PR #4).

### `findings` (array, ≥1 entry, **every entry has ≥1 evidence**)

Each entry:

| Field | Type | Notes |
|---|---|---|
| `title` | string | One-line headline. ≤30 Chinese chars preferred. |
| `detail` | string | One paragraph, includes the actual numbers. |
| `evidence` | array of evidence | At least one. More is better (organizer §7.3). |

#### Evidence sub-schema

| Field | Type | Notes |
|---|---|---|
| `dataset` | string | Must equal the directory name under `data/public_datasets/` exactly. |
| `table` | string | The CSV/XLSX filename. Required when the dataset has multiple tables. |
| `columns` | array of string | **Verbatim** from the file header — including spaces, parentheses, mixed languages. |
| `filters` | string | SQL-WHERE-style or pandas-style. Must be reproducible: `Age >= 55` not `年龄≥55`. |
| `aggregation` | string | Function call form: `mean(Purchase Amount (USD))`, `count(*)`, `sum(amount)`. |
| `value` | number / string | The aggregation's actual result, captured from the sandbox run. **Never inferred.** |
| `row_count` | int (optional) | Post-filter row count. Required for any sampled analysis. |

Auto-grader replays `(dataset, table, filters, aggregation)` and
compares `value` and `row_count`. Mismatch → that finding scored 0.

Owner: `app/evidence/build.py` (PR #4).

### `charts` (array, ≥3 distinct types when not refusing)

Each entry:

| Field | Type | Notes |
|---|---|---|
| `type` | string | Chinese chart-type label (`柱状图`/`折线图`/`饼图`/`散点图`/`热力图`/`箱线图`). |
| `title` | string | Plain text, no markdown. |
| `html_anchor` | string | Fragment id present in the rendered HTML, e.g. `#chart-age-bar`. |

The HTML report must contain a corresponding `<div id="chart-age-bar">`
(without the `#`). The renderer asserts this match before responding.

Owner: `app/report/charts.py` (PR #5).

### `recommendations` (array of string)

Action-oriented business suggestions, each grounded in one of the
findings above. Plain Chinese sentences. Empty when refusing.

Owner: planner's `finish` step (PR #4).

### `is_refusal` (boolean, required)

`true` only when the system declined to analyze. When `true`:

- `findings` may be empty.
- `charts` may be empty.
- `summary` carries the canonical refusal narrative — see
  [`refusal-policy.md`](refusal-policy.md) for the exact phrasing.
- `recommendations` is empty.

False refusals (refusing a question we could have answered) are scored
as wrong answers — the grading rule is asymmetric: refusing a real
question is scored **worse than answering it badly**.

### `confidence` (number, optional, 0–1)

Optional signal of self-assessed confidence. Organizer §7.3 says this
field is not graded — we emit it for our own observability but never
key on it.

## 4. Follow-up specifics

A follow-up request carries `parent_id`. Its response uses the **same
shape**, but:

- `id` is the new follow-up id (`eval_follow_*`), not the parent's.
- `findings` should reference the parent's named cohorts where the
  user used pronouns ("they" → "the 55+ cohort identified in the
  parent analysis"). Cohort propagation is the session store's job.
- A new HTML report is rendered for the follow-up; the parent's report
  remains accessible at its own URL.

## 5. Refusal payload

```json
{
  "id": "eval_trap_b9c45d12",
  "report_html_url": "https://your-domain.com/reports/eval_trap_b9c45d12.html",
  "summary": "数据集中不包含「Race」字段,无法基于现有字段对种族维度进行流失率分析。建议补充该字段后重试。",
  "findings": [],
  "charts": [],
  "recommendations": [],
  "is_refusal": true,
  "confidence": 1.0
}
```

The HTML report still exists for refused requests — it shows the same
narrative as `summary` plus a small panel describing what data **was**
available, so the user can adjust their question.

## 6. Versioning

This contract is **v1**, tied to organizer 赛题4 README.md v1.0
(2026-04-28).

If the organizer publishes a v1.1 of the spec we update this file in
the same PR that changes the implementation, never separately.
