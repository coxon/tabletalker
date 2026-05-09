# eval 评测目录

本目录保存 TableTalker 的端到端评测脚本、用例和运行产物。

## 常用命令

```bash
make eval              # 生成合成数据，运行 cases.yaml，写入指标
make eval-datasets     # 只重建 eval/datasets/*.csv
make eval-run          # 连接已经运行的 :8000 后端重新评测
```

## 部分重跑（resume）

整轮 cases-20 在 aigw + reasoning 下要 90+ 分钟。一轮跑完后，少数 case 可能因
**LLM 网关瞬时 502 / 连接 0** 拿不到 200 状态，但代码本身没问题——这种用 resume
模式只补跑失败的 case，不必整轮重来：

```bash
uv run --project 源代码/backend python eval/run.py \
  --cases eval/cases-20.yaml \
  --resume eval/runs/<run-id>
```

行为：

- 读 `<run-id>/*.json`，**保留所有 stage 全部 200 的 case**；
- 重跑任意 stage（main / followup / trap）非 200 的 case；
- 写回原 run dir，更新 `summary.json`。

边界：resume 只看 HTTP 状态码，**不重跑"业务判断错"的 case**（比如 trap=200 但
拒答决策错），那需要修代码或改 prompt 而不是重试。回归后用
`render_official_metrics.py --run <run-id>` 重新生成自测报告即可。

## 目录内容

- `build_datasets.py`：生成 15 个确定性的合成 CSV 数据集。
- `cases.yaml`：15 个合成用例，每个用例可包含主问题、追问、trap。
- `cases-20.yaml`：当前提交回归集，15 个合成用例 + 5 个官方公开数据集。
  其中 TMDB 用 `extra_files` 触发多文件上传，`15_world_gdp` 用
  `primary_file: 15_world_gdp.xlsx` 触发 Excel 冒烟路径。
- `run.py`：向后端发送请求，写入 `runs/<timestamp>/`，并计算聚合指标。
- `render_official_metrics.py`：把 run summary 渲染成官方 9 节自测报告。
- `datasets/`：生成的合成 CSV；`15_world_gdp.xlsx` 是为 Excel 冒烟保留的
  同源副本。
- `datasets-official/`：官方公开数据集的标准化文件名副本或样本。
- `runs/`：每轮评测产物。

## 最新提交回归

最新自测报告来自：

```bash
uv run python eval/run.py \
  --backend http://127.0.0.1:8000 \
  --cases eval/cases-20.yaml \
  --data-dir /private/tmp/tabletalker-eval20-official-copy-data \
  --out eval/runs/eval20-official-20260508-223200

uv run python eval/render_official_metrics.py \
  --run eval/runs/eval20-official-20260508-223200 \
  --commit dcbfb2a \
  --out 自测报告/latest_evaluation_metrics.md
```

该数据目录包含 15 个合成数据集和 5 个官方公开数据集。TMDB 使用 movies
主文件和 credits 辅助文件；`15_world_gdp` 在下一轮会使用 Excel 副本；
电信客户流失使用完整 100k 行官方 CSV。

## 诚实原则

`自测报告/latest_evaluation_metrics.md` 中的数字必须来自真实 run。代码支持但
没有在本轮触发的能力，应在报告中写明“未触发”，不要手工改成“是”。
