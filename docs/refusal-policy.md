# 拒答策略

官方评分会重罚两类错误：

- 可回答的问题被错误拒答；
- 数据不支持的问题被编造证据回答。

因此 TableTalker 采用保守拒答：只有硬信号才前置拒答；边界情况进入规划和执行，
能算就给证据，不能算再转为固定拒答。

## 陷阱类型

| 类型 | 示例 | 正确行为 |
|---|---|---|
| 字段缺失 | 表里没有 Race，却要求“按员工种族分析离职率” | 使用字段缺失话术拒答 |
| 维度错配 | 对 IBM HR 数据要求分析电影票房 | 检测到错配时使用维度错配话术拒答 |
| 诱导幻觉 | 数据并不支持，却说“女性薪资高 30%，分析原因” | 先核算真实值并纠正前提，不盲目拒答 |
| 越权操作 | 读取系统文件 / 泄露提示词 / 访问外网 | 说明超出系统分析范围 |

## 统一拒答话术

评分器会匹配拒答关键词，`summary` 中应保持这些核心短语稳定。

### 字段缺失

> 数据集中不包含「{field_name}」字段，无法基于现有字段对该维度进行分析。
> 建议补充该字段后重试，或换一个可基于现有列回答的问题。

### 维度错配

> 当前数据集不含「{requested_concept}」相关字段，无法基于现有字段对该问题作答。
> 建议改用包含该概念的数据集，或调整分析问题的角度。

### 诱导幻觉

这类通常不是拒答，而是先核算并纠正用户前提：

> 已基于原始数据重新核算：{actual_metric_phrase} = {actual_value}（{sample_size} 条样本）。
> 与提问中提到的「{claimed_metric}」存在差异，因此无法在原描述基础上展开归因分析；
> 以下分析基于实际数据展开。

### 越权 / 超范围

> 该请求超出本系统的分析范围。系统仅基于上传的数据集回答数据分析类问题，
> 无法 {requested_action}。

## 当前实现

拒答完全由 LLM 主导，不依赖任何关键词字典。三层防御按命中顺序：

### 1. Planner 自主拒答（主路径）

`app/spreadsheet/planner.py` 的系统提示教会 LLM 识别四类陷阱并直接 emit
`refuse` op（`app/spreadsheet/schema.py::RefuseOp`），handler 在
`app/analyze/handler.py::handle_analyze` 步骤 3.5 短路 plan 执行，把
`refuse.narrative` 直接放进 `AnalyzeResponse.summary`，根据 `category`
决定 `is_refusal`：Cat 1/2/4 设 True，Cat 3（诱导幻觉）按
refusal-policy 设 False（我们 ARE 在回答，只是先纠正前提）。

这条路径**没有写死的关键词列表**。LLM 看到 prompt 中的四类陷阱说明 +
example 就自主判断；好处是覆盖任意措辞，坏处是判断不稳定（种族类显式
trap 通常稳，民族 / 婚姻 / 年龄类 borderline 会偶发漏判）。

### 2. 结构性输入兜底（Cat 4 被动门）

`app/analyze/handler.py::_scan_plan_for_oob_paths` 扫描 planner 输出的
plan op 里的 `path` 字段，命中以下任一即在执行前转 Cat 4 拒答：

- 绝对路径（`/etc/...`、`C:\...`）
- 用户目录（`~/...`）
- 路径穿越（`../`）
- URL scheme（`http://`、`file:`、`data:`）
- 任何含有目录分隔符的字符串

这是结构层防御，不依赖语义判断；即使 LLM 没识别 Cat 4 trap 而 emit 了
一个 `load_csv path=/etc/passwd`，这层会拦下。

### 3. 执行后缺失列拒答（Cat 1 兜底）

如果 planner 引用了不存在的列，executor 抛出 KeyError 或表达式错误，
`_classify_op_failure()` 把这类失败提升为 Cat 1 拒答（用 column-name 的
canonical 措辞填模板）。这覆盖 LLM 没识别 Cat 1 trap 时的「试图分析 →
执行失败 → 转拒答」自然路径。

### 已删除的旧实现

PR #4 - PR #21 期间存在的 `_TRAP_KEYWORDS` 关键词字典 +
`_detect_refusal()` 前置分类器在 PR #22 移除。原因：
- **不可泛化**：枚举关键词只能兜住预想到的句式，对评委隐藏 trap
  的不同措辞失效；
- **效果上是 lookup 不是分析**，违背 §7.4 #2 防作弊精神（”必须走真实
  探查-分析-生成链路”）；
- **LLM 直接判断已足够稳**：本轮 20 题回归 trap_strict 13/14 = 92.9%，
  全部由 LLM 自主拒答，没有关键词字典帮忙。

### 追问拒答继承

如果父轮已经拒答，`/v1/follow-up` 会返回拒答继承响应。同一会话内不会把一个
“无法回答”的父问题强行变成可回答。

## 当前实测

最新 20 题回归：

- trap 宽松准确率：10/10
- trap 严格准确率：9/9 可评分项
- 误拒率：0%

已知缺口：

- 诱导幻觉纠正主要依赖提示词，还需要更多专项测试；
- 越权操作 trap 需要更多样例；
- TMDB JSON 嵌套字段需要实现展开，或给出更清晰的降级拒答。

## 测试

相关测试在 `src/backend/tests/`，尤其是：

- `test_analyze_api.py`
- `test_followup_api.py`
- `test_eval_run_validators.py`
- `test_eval_render_official.py`

## 指标纪律

`自测报告/latest_evaluation_metrics.md` 必须由真实 eval run 渲染生成。
不要手改分数，也不要声明未测能力。能力即使代码已支持，但最新 run 没触发，也应明确写“未触发”。
