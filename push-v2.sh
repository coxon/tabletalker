#!/bin/bash
# v2 推送：把今晚 5/6 18:00 之后做的所有改动推到 fork 的 qiaoling/v1.5 分支
# 复用 v1.5 时的 fork 方案（绕开 history-not-related 问题）
# 现有的 PR #5 会自动同步到 v2 状态（force push）

set -e

UPSTREAM_OWNER="coxon"
UPSTREAM_REPO="tabletalker"
MY_USER=$(gh api user --jq .login)
MY_FORK="${MY_USER}/${UPSTREAM_REPO}"
MY_BRANCH="qiaoling/v1.5"   # 沿用同一分支，PR #5 自动更新

LOCAL_DIR="/Users/zhangql/cc/黑松客比赛asiainfo"
TMP_DIR="/tmp/tabletalker-v2-pr-$$"

echo "=========================================================="
echo "  v2 推送 · 5/6 晚上的工作"
echo "  用户：$MY_USER"
echo "  目标分支：$MY_FORK:$MY_BRANCH"
echo "  PR #5 会自动同步到 v2 状态"
echo "=========================================================="

# 1. clone fork 到临时目录
echo ""
echo "[1/5] clone fork 到临时目录..."
gh repo clone "$MY_FORK" "$TMP_DIR"
cd "$TMP_DIR"

# 同步上游
git remote add upstream "https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}.git" 2>/dev/null || true
git fetch upstream
git checkout main
git reset --hard upstream/main 2>/dev/null || git reset --hard origin/main 2>/dev/null || echo "  （主分支可能为空，继续）"

# 2. 切到 v1.5 分支
echo ""
echo "[2/5] 切到 $MY_BRANCH（基于上游 main）..."
git checkout -B "$MY_BRANCH"

# 3. 同步本地全部文件（含演示数据、schemas、cache 等）
echo ""
echo "[3/5] 同步本地最新代码..."
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
  --exclude='cache/' \
  --exclude='logs/' \
  "$LOCAL_DIR/" "./"

echo ""
echo "  同步后变更："
git status --short | head -30
TOTAL=$(git status --short | wc -l)
echo "  共 $TOTAL 个文件改动"

# 4. commit + push
echo ""
echo "[4/5] commit 并强推到 fork..."
git add -A
git commit -m "feat(v2): 5/6 晚冲刺 · 真 LLM 端到端 + 5 项性能优化" \
  -m "" \
  -m "今晚的工作（在 v1.5 基础上）：" \
  -m "" \
  -m "■ 真实 LLM 端到端打通（v1 → v2）" \
  -m "  - 5/5 模型连通（aliyun 网关 qwen/deepseek/kimi/MiniMax/glm）" \
  -m "  - 真实演示数据生成（15 个数据集 · ~5MB CSV）" \
  -m "  - schemas.json + business_terms.json + graphrag_index.json 全建好" \
  -m "  - 真 SQL 生成（codegen prompt 加类型规则避免幻觉）" \
  -m "  - 真 DuckDB 执行 + 真 anomaly 检测（IQR/CUSUM/Pearson）" \
  -m "" \
  -m "■ 5 项性能优化" \
  -m "  - 缓存预热：演示题秒回（~3s vs 真 LLM ~80s）" \
  -m "  - schema 瘦身：codegen prompt -40% tokens" \
  -m "  - max_tokens 减半：1500 → 700" \
  -m "  - chart_pick + summary 并行（asyncio.gather）" \
  -m "  - 流式 codegen 占位（决赛前再做）" \
  -m "" \
  -m "■ 修复" \
  -m "  - codegen 静态校验缺 CSV schema 导致永远 catalog error" \
  -m "  - LLM 返回 markdown 包裹的 JSON 解析失败" \
  -m "  - chart_pick KPI delta 硬编码 0" \
  -m "  - LLM 把 trend 配 KPI、share 不配 donut 等 intent-kind 错配" \
  -m "  - business 模式 summary 误用 default 模型走 qwen 60s+" \
  -m "" \
  -m "■ 前端" \
  -m "  - ThinkingBubble loading 卡片：实时秒表 + 步骤提示 + 超时警告" \
  -m "" \
  -m "■ 工具" \
  -m "  - tools/warm_cache.py 预热脚本" \
  -m "  - tools/generate_mock_data.py / extract_schema.py / build_*.py 全跑通" \
  -m "" \
  -m "用法：" \
  -m "  cd backend-skeleton && python tools/warm_cache.py    # 预热 ~10 分钟" \
  -m "  echo 'WARM_CACHE=true' >> .env && 重启 → 演示题 ~3s 响应"

git push origin "$MY_BRANCH" --force

# 5. 同步 PR 状态
echo ""
echo "[5/5] PR #5 会自动同步到 v2 状态（fork 推送后 GitHub 会自动更新）"
PR_URL=$(gh pr list --repo "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" --head "${MY_USER}:${MY_BRANCH}" --json url --jq '.[0].url' 2>/dev/null || echo "")
if [ -n "$PR_URL" ]; then
  echo ""
  echo "  ✅ PR 链接：$PR_URL"
else
  echo ""
  echo "  ⚠️  没找到现有 PR，可能要手动跑：gh pr create --repo ${UPSTREAM_OWNER}/${UPSTREAM_REPO}"
fi

echo ""
echo "=========================================================="
echo "✅ v2 推送完成"
echo ""
echo "🧹 临时目录：$TMP_DIR （可手动 rm -rf 清理）"
echo "✓ 你的本地仓库 $LOCAL_DIR 不受影响"
echo "=========================================================="
