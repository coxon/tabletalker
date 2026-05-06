#!/usr/bin/env bash
# Table-Talker 演示预热
# 用法：bash warmup.sh
#
# 演示前必跑：把所有页面 + 7 个对话提前请求一遍，
# 让浏览器 Babel 编译 + React 组件挂载 + Plotly 加载 全部就绪。
# 演示时切换页面零延迟。

set -e
cd "$(dirname "$0")"

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RESET="\033[0m"

echo "========================================"
echo "  Table-Talker · 演示预热"
echo "========================================"
echo ""

# Step 1: 后端健康
echo "→ 检查后端 ..."
if ! curl -s -m 2 http://localhost:8000/api/health | grep -q '"status":"ok"'; then
    echo -e "${YELLOW}⚠️${RESET}  后端未启动，先跑 bash start.sh"
    exit 1
fi
echo -e "  ${GREEN}✅${RESET} 后端就绪"

# Step 2: 前端
echo "→ 检查前端 ..."
if ! curl -s -m 2 -o /dev/null -w "%{http_code}" http://localhost:8080/Table-Talker.html | grep -q "200"; then
    echo -e "${YELLOW}⚠️${RESET}  前端未启动，先跑 bash start.sh"
    exit 1
fi
echo -e "  ${GREEN}✅${RESET} 前端就绪"

# Step 3: 触发 7 个 mock 对话（让后端缓存）
echo ""
echo "→ 预热 7 个对话场景 ..."

QUESTIONS=(
    "Q1 华南区销售为什么环比下滑 12%？哪些 BU 拖累最大？"
    "4 月人力月度复盘：流动率、认证密度、各 BU 人均产出?"
    "本月哪些用户 ARPU 异常下跌？是否与套餐变更相关？"
    "工单 SLA 达成率最近怎么样？怎么拉升？"
    "Q1 各部门预算偏差，哪个超支最严重？"
    "员工技能矩阵 × BU 分布"
    "客户流失 7 日早期信号"
)

for i in "${!QUESTIONS[@]}"; do
    Q="${QUESTIONS[$i]}"
    echo -n "  [$((i+1))/7] ${Q:0:30}... "
    # 后端 SSE 触发一次（不需要等完成，让后端 mock 数据加载到内存）
    curl -s -m 5 -X POST http://localhost:8000/api/chat/stream \
        -H "Content-Type: application/json" \
        -d "{\"question\":\"$Q\",\"mode\":\"business\",\"conversation_id\":\"c$((i+1))\"}" \
        -o /dev/null &
done
wait
echo -e "  ${GREEN}✅${RESET} 7 个对话场景预热完成"

# Step 4: 触发批量评测（提前测一次）
echo ""
echo "→ 预热批量评测 ..."
EVAL_FILE="evaluation/sample_eval.jsonl"
if [ -f "$EVAL_FILE" ]; then
    RESP=$(curl -s -m 5 -F "file=@$EVAL_FILE" http://localhost:8000/api/eval/run)
    TASK_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null)
    if [ -n "$TASK_ID" ]; then
        # 后台跑完整的 eval（不阻塞）
        curl -s -m 10 "http://localhost:8000/api/eval/stream/$TASK_ID" -o /dev/null &
        echo -e "  ${GREEN}✅${RESET} 批量评测预热完成（task_id=$TASK_ID）"
    else
        echo -e "  ${YELLOW}⚠️${RESET}  评测预热失败，演示时再上传也行"
    fi
fi

# Step 5: 触发各个静态资源加载（让浏览器缓存）
echo ""
echo "→ 预热前端静态资源 ..."
RESOURCES=(
    "/Table-Talker.html"
    "/styles/tokens.css"
    "/data.js"
    "/api.js"
    "/app.jsx"
    "/sidebar.jsx"
    "/chat.jsx"
    "/pages.jsx"
    "/trace.jsx"
    "/charts.jsx"
    "/tweaks-panel.jsx"
)
for r in "${RESOURCES[@]}"; do
    curl -s -m 2 -o /dev/null "http://localhost:8080$r"
done
echo -e "  ${GREEN}✅${RESET} 前端静态资源预热完成（${#RESOURCES[@]} 个）"

echo ""
echo "========================================"
echo -e "  ${GREEN}🎬 演示就绪${RESET}"
echo "========================================"
echo "  ⌘+R 刷新浏览器一次（让 React 重新挂载）"
echo "  然后立即开始录制即可"
echo ""
echo "  📋 录制前过一遍 录制前自检.md"
echo "========================================"
