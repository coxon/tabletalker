# 会话状态与追问

一个 session 由一次父轮 `/v1/analyze` 和零到多次 `/v1/follow-up` 组成。
追问通过 `parent_id` 关联父轮，并复用父轮 workspace、findings、cohorts、
chart anchors、上传文件和采样信息。

## 双层存储

TableTalker 使用两个互补存储层。

| 层 | 代码 | 用途 | 生命周期 |
|---|---|---|---|
| 内存热层 | `app/session/store.py` | 追问实时执行；持有父轮 workspace 和上传文件 | TTL + LRU，默认 24h |
| SQLite 历史索引 | `app/persistence/sessions.py`, `app/api/sessions.py` | 历史列表、搜索、统计、详情、删除 | 跨后端重启保留 |

SQLite recorder 是旁路能力。如果它写入失败，分析响应仍应返回给用户；历史记录可能少一行，
但核心分析不能因为历史索引失败而失败。

## 内存 Session 内容

当前 `Session` dataclass 保存：

- 父轮 id；
- workspace 目录；
- 主文件名和辅助 `extra_filenames`；
- dataset label；
- 原始问题；
- 累积 findings；
- 父轮 summary；
- 抽取出的 cohorts；
- chart anchors；
- 是否拒答；
- sampling rate / sampling note；
- turn 列表；
- 创建和最后使用时间；
- 每个 session 独立的追问锁。

追问锁保证同一父轮的并发追问不会分配到同一个 `eval_follow_<suffix>_qN` id。

## 追问 Prompt 组装

`app/session/prompt.py` 会给 planner 渲染 system prelude，包含：

- 父轮问题；
- 已建立的 findings；
- 从 evidence filters 抽取的命名 cohorts；
- 已渲染图表 anchors；
- 新追问问题。

planner 可以复用之前的过滤条件，也可以在此基础上新增分组或聚合，不必从零重建上下文。

## 多文件追问

父轮会把辅助文件名保存到 session。`/v1/follow-up` 会把这些文件名传回
`AnalyzeRequest.extra_filenames`，因此 TMDB movies + credits 的父轮不会在追问时退化成单文件。

## 拒答父轮

如果父轮已拒答，追问返回拒答继承报告，沿用父轮拒答理由。没有新增数据时，
同一会话内不应把不可回答问题变成可回答。

## 持久历史 API

`/v1/sessions` 返回列表和统计；`/v1/sessions/{id}` 返回 turn 详情；
`DELETE /v1/sessions/{id}` 删除持久历史记录，但不会打断正在进行的内存热会话。

前端历史页读取 SQLite 索引，而不是扫描内存 store。

## 当前实测

最新 20 题回归（其中 18 个 case 有追问轮）：

- 追问成功率：17 / 18 = 94.4%
- 会话继承率：17 / 18 = 94.4%

剩余 1 个失败属于传输 / 超时类问题，不是会话状态丢失。后续 PR #22 回归
已回到 18/18 = 100%，`docs/roadmap.md` 有更新。
