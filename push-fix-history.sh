#!/bin/bash
# 修复方案：基于上游 history 重新建 commit
# 因为本地 git history 来自亚信内网，与 coxon/main 无共同祖先
# 这个脚本：在临时目录 clone fork → 拷贝本地文件 → commit → push → 发 PR

set -e

UPSTREAM_OWNER="coxon"
UPSTREAM_REPO="tabletalker"
MY_USER=$(gh api user --jq .login)
MY_FORK="${MY_USER}/${UPSTREAM_REPO}"
MY_BRANCH="qiaoling/v1.5"

LOCAL_DIR="/Users/zhangql/cc/黑松客比赛asiainfo"
TMP_DIR="/tmp/tabletalker-pr-$$"

echo "============================================="
echo "  修复 history 不相关问题"
echo "  用户：$MY_USER"
echo "  fork：$MY_FORK"
echo "============================================="

# 1. clone 你的 fork 到临时目录（带上游 history）
echo ""
echo "[1/5] clone fork 到临时目录..."
gh repo clone "$MY_FORK" "$TMP_DIR"
cd "$TMP_DIR"

# 同步上游最新（确保和 coxon/main 一致）
git remote add upstream "https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}.git" 2>/dev/null || true
git fetch upstream
git checkout main
git reset --hard upstream/main 2>/dev/null || git reset --hard origin/main 2>/dev/null || echo "  （主分支可能为空，继续）"

# 2. 切到新分支
echo ""
echo "[2/5] 创建分支 $MY_BRANCH（基于上游 main）..."
git checkout -B "$MY_BRANCH"

# 3. 复制本地工作目录的全部文件（除 .git / .env / 缓存等）
echo ""
echo "[3/5] 同步本地文件到临时目录..."
rsync -av \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='.run' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='node_modules' \
  --exclude='*.lock' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='backend-skeleton/__pycache__' \
  "$LOCAL_DIR/" "./"

echo ""
echo "  同步后变更："
git status --short | head -20
TOTAL=$(git status --short | wc -l)
echo "  共 $TOTAL 个文件变更"

# 4. commit + push
echo ""
echo "[4/5] commit 并推送到 fork..."
git add -A
git commit -m "feat(v1.5): 决赛冲刺 - 用户研究22项+分析师建议11项+测试bug28项" \
  -m "" \
  -m "70 个文件改动 · 来自 dereksoriano550-collab/tabletalker:qiaoling/v1.5" \
  -m "" \
  -m "亮点：" \
  -m "- AI Daily / 14 步 Trace / 5 模型 A/B（含 mock 兜底）" \
  -m "- 双模式 / 三态一体 / 看板演示模式" \
  -m "- 报告章节按域动态 + 审计版 PDF 导出" \
  -m "- 治理闭环：指标定义 + 审批流 + 权限矩阵 + 工单 + 版本 + 审计" \
  -m "- 飞书 bot 工作流集成展示" \
  -m "- CDO 视角：业务部门粒度 + 团队 leaderboard + 学习模式" \
  -m "- PII 拦截 27 关键词 + 同义词 + 场景化" \
  -m "- 命令面板 ⌘K + AI 反问澄清 + 一键 dbt model" \
  -m "- 30+ pytest + smoke-test 25/25"

# 强推（覆盖之前那个 unrelated history 的分支）
git push origin "$MY_BRANCH" --force

# 5. 发 PR
echo ""
echo "[5/5] 创建 PR..."
gh pr create \
  --repo "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" \
  --base main \
  --head "${MY_USER}:${MY_BRANCH}" \
  --title "v1.5 决赛冲刺 · 巧玲" \
  --body "## 决赛冲刺版 · 5/4

> 来自 fork: ${MY_USER}/${UPSTREAM_REPO}

### 改了什么（70 文件）
- AI Daily / 14 步 Trace / 5 模型 A/B（含 mock 兜底）
- 双模式 / 三态一体 / 看板演示模式
- 报告章节按域动态 + 审计版 PDF 导出
- 治理闭环：指标定义 + 审批流 + 权限矩阵 + 工单 + 版本 + 审计
- 飞书 bot 工作流集成展示
- CDO 视角：业务部门粒度 + 团队 leaderboard + 学习模式
- PII 拦截 27 关键词 + 同义词 + 场景化
- 命令面板 ⌘K + AI 反问澄清 + 一键 dbt model
- 30+ pytest + smoke-test 25/25

### 队长 5 分钟上手
clone 后看 \`交给队长.md\`

### 巧玲待你确认
- [ ] VPN 问题（我连不上内网真模型）
- [ ] 5/8 内网部署
- [ ] 5/9 录视频出镜
- [ ] 5/22-24 决赛分工

—— 巧玲 · 2026/05/04"

# 收尾
echo ""
echo "================================================================"
echo "✅ PR 创建完成"
echo ""
echo "📋 PR 列表：https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}/pulls"
echo ""
echo "🧹 临时目录：$TMP_DIR  （可手动 rm -rf 清理）"
echo ""
echo "✓ 你的本地仓库 $LOCAL_DIR 不受影响"
echo "================================================================"
