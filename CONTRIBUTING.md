# 贡献指南 · Contributing

> Table-Talker 团队协作规范。
> 当前规模 4 人 + 7 天冲刺，规则**轻但要遵守**。

---

## 一、分支策略

```
main                     ← 主分支，永远可部署
└─ feat/<short-name>      ← 新功能分支
└─ fix/<short-name>       ← bug 修复
└─ chore/<short-name>     ← 文档 / 配置 / 重构
└─ docs/<short-name>      ← 纯文档变更
```

例：
- `feat/graphrag-index`
- `fix/eval-progress-stuck`
- `docs/changelog-v1`

---

## 二、Commit Message 规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```
<type>: <短描述>

[可选正文]
[可选 footer]
```

`<type>`：

| type | 用途 | 例 |
|---|---|---|
| `feat` | 新功能 | `feat: 接入 GraphRAG 索引` |
| `fix` | bug 修复 | `fix: SSE 解析 \r\n\r\n 兼容` |
| `docs` | 文档 | `docs: 更新 PRD 第 10 章` |
| `chore` | 配置/构建 | `chore: 升级 fastapi 到 0.115` |
| `refactor` | 重构 | `refactor: 抽离 LLM Adapter` |
| `test` | 测试 | `test: 加 step_router 单元测试` |
| `style` | 格式（不影响逻辑）| `style: ruff 格式化` |
| `perf` | 性能优化 | `perf: 缓存 schema 加载` |

**禁止**：
- `update`（不明确）
- `wip`（合并到 main 时）
- 中英混杂（保持一种语言）

---

## 三、代码风格

### Python
- **格式化**：[ruff](https://github.com/astral-sh/ruff)（替代 black + isort + flake8）
- **类型注解**：核心模块尽量加 type hints
- **命名**：snake_case；常量 UPPER_SNAKE
- **文档字符串**：公开函数加 docstring，简明描述参数和返回值

```python
async def step_ttl(question: str, mode: str = "semantic") -> dict | list:
    """TTL 推理：业务术语 → 字段映射。

    Args:
        question: 用户原始问题
        mode: "entities" 返回命中的术语；"semantic" 返回字段映射 dict

    Returns:
        匹配到的实体或语义补全字典
    """
```

### JSX / 前端
- 缩进：2 空格
- inline style 用对象（驼峰）
- 组件名 PascalCase
- 函数名 camelCase

---

## 四、Pull Request 流程

```
1. 从 main 拉新分支
2. 改代码 + 自测
3. git commit -m "feat: ..."
4. git push -u origin feat/xxx
5. 在 GitAI 创建 PR → 选 reviewer
6. 至少 1 人 review + CI 绿 → 合并
7. 合并后删除分支
```

### PR 描述模板

```markdown
## 改动了什么
- ...

## 为什么
- 解决了 issue #xx
- 或：评委反馈 / 新需求

## 怎么验证
- [ ] 跑 pytest 通过
- [ ] 浏览器手测 X 流程
- [ ] 截图见下

## 风险
- ...
```

---

## 五、本地开发

### 首次 setup

```bash
# 后端
cd backend-skeleton
bash install.sh   # 自动建 venv + 装依赖（含国内镜像 fallback）

# 前端
# 不需要构建，直接 python3 -m http.server 8080 in design-source/

# 一键起所有
cp .env.example .env
# 编辑 .env 填 LLM_API_KEY
bash start.sh
```

### 跑测试

```bash
cd backend-skeleton
source .venv/bin/activate
pytest tests/ -v
```

### Lint

```bash
ruff check .
ruff format .
```

### 联调

参考 [README.md](./README.md) 第 1 章 "一键启动"。

---

## 六、敏感信息红线（重要）

❌ **绝对不要 commit**：
- `.env` 文件（含 API Key）
- 公司 / 客户私有数据
- Token / 密码 / 证书
- 生产数据库 dump

✅ **要 commit**：
- `.env.example`（占位符）
- 公开数据集（≤ 10MB）
- 合成 mock 数据

提交前必检：
```bash
git status -s | grep -E "\.env$|\.venv|secret"
```

如果命中任何一项，**停下来排查**。

---

## 七、Bug / Issue 上报

### Bug 模板

```markdown
**现象**
（一句话）

**复现步骤**
1. ...
2. ...

**期望**
...

**实际**
...

**环境**
- OS: macOS 14
- Python: 3.12
- 浏览器: Chrome 134
- MOCK_MODE: true / false

**日志**
...（贴 backend.log 或 Console 错误）
```

---

## 八、团队联络

| 角色 | 姓名 | 频道 |
|---|---|---|
| 队长 | 张扬（zhangyang）| 飞书 |
| 算法 | [TODO] | |
| 后端 | [TODO] | |
| 前端 + 视频 | 巧玲（zhangql）| 飞书 |
| 部署 + 数据 | [TODO] | |

紧急联络见 [推送到-GitAI.md](./推送到-GitAI.md) 第 7 章。

---

## 九、决赛冻结期（5/9-5/10）规则

- **5/9 12:00 起** main 分支只接受 `fix:` 类型 commit
- **5/10 09:00 起** 全队冻结代码，只调试 + 录视频
- **5/10 17:00 起** 不再 push，专心提交表单

---

> Made with 🧪 by Table-Talker Team · 2026
