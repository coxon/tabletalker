#!/bin/bash
# Table-Talker · Fork 模式推送（无需队长加权限）
# 自动 fork → 推到你 fork → 发跨仓库 PR
# 上游：https://github.com/coxon/tabletalker

set -e

UPSTREAM_OWNER="coxon"
UPSTREAM_REPO="tabletalker"
UPSTREAM_URL="https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}.git"
MY_BRANCH="qiaoling/v1.5"

echo "============================================="
echo "  Table-Talker → Fork 模式推送"
echo "  上游：$UPSTREAM_URL"
echo "  策略：fork 到你账号 → 推 fork → 发 PR 给队长"
echo "============================================="

cd "$(dirname "$0")"
rm -f .git/index.lock 2>/dev/null

# ============ 1. gh CLI 就绪 + 授权 ============
if ! command -v gh &> /dev/null; then
  echo "需要先装 GitHub CLI："
  echo "  brew install gh   (推荐)"
  echo "  或访问 https://cli.github.com/ 下载 .pkg"
  exit 1
fi

if ! gh auth status &> /dev/null; then
  echo "[1/6] 浏览器授权..."
  gh auth login --hostname github.com --git-protocol https --web
fi
gh auth setup-git

# 当前 GitHub 用户名
MY_USER=$(gh api user --jq .login)
MY_FORK_URL="https://github.com/${MY_USER}/${UPSTREAM_REPO}.git"
echo "✓ 当前 GitHub 用户：${MY_USER}"

# ============ 2. fork 到我的账号（如已 fork 则跳过）============
echo ""
echo "[2/6] 检查 / 创建 fork..."
if gh repo view "${MY_USER}/${UPSTREAM_REPO}" &> /dev/null; then
  echo "✓ fork 已存在：${MY_USER}/${UPSTREAM_REPO}"
else
  echo "  fork 中..."
  gh repo fork "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" --clone=false
  echo "✓ fork 完成：${MY_USER}/${UPSTREAM_REPO}"
  sleep 3
fi

# ============ 3. 安全检查 ============
if git ls-files --error-unmatch .env 2>/dev/null; then
  echo "⛔ .env 已被跟踪，先 git rm --cached .env"
  exit 1
fi

# ============ 4. commit 所有变更 ============
echo ""
echo "[3/6] 提交所有变更..."
TOTAL=$(git status --short | wc -l)
echo "  共 $TOTAL 个变更待提交"
git add -A
git commit -m "feat(v1.5): 决赛冲刺 - 用户研究22项+分析师建议11项+测试bug28项" \
  -m "- AI Daily / 14 步 Trace / 5 模型 A/B（含 mock 兜底）" \
  -m "- 双模式 / 三态一体 / 看板演示模式 / 命名 / 删除" \
  -m "- 报告章节按域动态 / 审计版 PDF 导出" \
  -m "- 治理闭环：指标定义 + 审批流 + 权限矩阵 + 工单 + 版本 + 审计" \
  -m "- 工作流集成：飞书 bot 配置展示" \
  -m "- CDO 视角：业务部门粒度 + 团队 leaderboard + 学习模式" \
  -m "- PII 拦截 27 关键词 + 同义词 + 场景化" \
  -m "- 命令面板 ⌘K + AI 反问澄清 + 一键 dbt model" \
  -m "- 30+ pytest + smoke-test 25/25" \
  || echo "  （无新变更，跳过 commit）"

# ============ 5. 配置 remote + 推送到 fork ============
echo ""
echo "[4/6] 配置 remote..."
# 移除旧的 github remote（可能指向上游）
git remote remove github 2>/dev/null || true
# 新增 myfork remote 指向自己 fork
if git remote | grep -q "^myfork$"; then
  git remote set-url myfork "$MY_FORK_URL"
else
  git remote add myfork "$MY_FORK_URL"
fi
echo "✓ remotes:"
git remote -v | sed 's/^/    /'

echo ""
echo "[5/6] 推到你 fork 的分支：$MY_BRANCH..."
git push myfork "HEAD:$MY_BRANCH"

# ============ 6. 自动开 cross-fork PR ============
echo ""
echo "[6/6] 自动开 Pull Request..."
gh pr create \
  --repo "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" \
  --base main \
  --head "${MY_USER}:${MY_BRANCH}" \
  --title "v1.5 决赛冲刺 · 巧玲" \
  --body "## 决赛冲刺版 · 5/4 提交

> 来自 fork: ${MY_USER}/${UPSTREAM_REPO}

### 改了什么
- AI Daily / 14 步 Trace / 5 模型 A/B（含 mock 兜底）
- 双模式 / 三态一体 / 看板演示模式
- 报告章节按域动态 + 审计版 PDF 导出
- 治理闭环：指标定义 + 审批流 + 权限矩阵 + 工单 + 版本 + 审计
- 飞书 bot 工作流集成展示
- CDO 视角：业务部门粒度 + 团队 leaderboard + 学习模式
- PII 拦截 27 关键词 + 同义词 + 场景化
- 命令面板 ⌘K + AI 反问澄清 + 一键 dbt model
- 30+ pytest + smoke-test 25/25
- 共 70 个文件变更

### 队长 5 分钟上手
clone 下来后看 \`交给队长.md\` —— 包含一键启动 + 5 个必看亮点 + 你来做的 6 项关键事

### 待你确认
- [ ] 5/8 内网部署权限申请
- [ ] 5/9 录视频谁出镜（建议巧玲）
- [ ] 5/22-24 决赛分工

—— 巧玲 · 2026/05/04" \
  2>&1 || echo "（PR 已存在或创建失败 - 链接见下）"

PR_LINK="https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}/compare/main...${MY_USER}:${UPSTREAM_REPO}:${MY_BRANCH}"

echo ""
echo "================================================================"
echo "✅ 全部完成"
echo ""
echo "📦 你的 fork：https://github.com/${MY_USER}/${UPSTREAM_REPO}"
echo "📋 PR 链接：${PR_LINK}"
echo ""
echo "📨 发给张扬："
echo "    我把决赛冲刺版从我 fork 提了 PR："
echo "    ${PR_LINK}"
echo "    你 review 后 merge，clone 主仓库后看 交给队长.md"
echo ""
echo "🎉 以后再推：git push myfork HEAD:$MY_BRANCH （免密）"
echo "================================================================"
