#!/usr/bin/env bash
# Table-Talker 一键启动
# 用法：bash start.sh
#
# 自动完成：
#   1. 检测 venv / 端口 / 进程
#   2. 杀掉旧进程释放端口
#   3. 启动后端（uvicorn）+ 前端（http.server）
#   4. 健康检查 + 自动打开浏览器
#   5. 输出 PID 到 .run/ 便于 stop.sh 杀

set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
mkdir -p .run

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

ok()    { echo -e "${GREEN}✅${RESET} $1"; }
warn()  { echo -e "${YELLOW}⚠️ ${RESET} $1"; }
fail()  { echo -e "${RED}❌${RESET} $1"; exit 1; }

echo "========================================"
echo "  Table-Talker · 一键启动"
echo "========================================"

# Step 1: 检查 venv
if [ ! -d "backend-skeleton/.venv" ]; then
    fail "找不到 backend-skeleton/.venv，请先跑 bash backend-skeleton/install.sh"
fi
ok "venv 存在"

# Step 2: 检查 .env
if [ ! -f ".env" ]; then
    fail "找不到 .env，请 cp .env.example .env 并填 LLM_API_KEY"
fi
MOCK_MODE=$(grep "^MOCK_MODE" .env | cut -d'=' -f2 | tr -d ' "')
ok ".env 加载成功（MOCK_MODE=${MOCK_MODE}）"

# Step 3: 杀旧进程
if lsof -ti :8000 >/dev/null 2>&1; then
    warn "8000 端口被占用，杀掉旧进程..."
    lsof -ti :8000 | xargs kill -9 2>/dev/null
    sleep 1
fi
if lsof -ti :8080 >/dev/null 2>&1; then
    warn "8080 端口被占用，杀掉旧进程..."
    lsof -ti :8080 | xargs kill -9 2>/dev/null
    sleep 1
fi
ok "端口 8000 / 8080 已就绪"

# Step 4: 启动后端
echo ""
echo "→ 启动后端 ..."
cd "$ROOT/backend-skeleton"
source .venv/bin/activate
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > "$ROOT/.run/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$ROOT/.run/backend.pid"
cd "$ROOT"

# 等待后端起来（最多 15s）
for i in $(seq 1 15); do
    if curl -s -m 1 http://localhost:8000/api/health >/dev/null 2>&1; then
        ok "后端启动成功（PID=$BACKEND_PID，耗时 ${i}s）"
        break
    fi
    sleep 1
    if [ $i -eq 15 ]; then
        fail "后端启动超时，看日志：tail -50 .run/backend.log"
    fi
done

# Step 5: 启动前端
echo ""
echo "→ 启动前端 ..."
cd "$ROOT/design-source"
nohup python3 -m http.server 8080 > "$ROOT/.run/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > "$ROOT/.run/frontend.pid"
cd "$ROOT"

sleep 1
if curl -s -m 2 -o /dev/null -w "%{http_code}" http://localhost:8080/Table-Talker.html | grep -q "200"; then
    ok "前端启动成功（PID=$FRONTEND_PID）"
else
    warn "前端可能还在起，请稍后手动访问"
fi

# Step 6: 健康检查
echo ""
echo "→ 健康检查 ..."
HEALTH=$(curl -s http://localhost:8000/api/health)
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    ok "API 健康"
    echo "    Mock 模式: $(echo "$HEALTH" | grep -o '"mock_mode":[^,]*' || echo "N/A")"
fi

# Step 7: 打开浏览器
echo ""
echo "→ 打开浏览器 ..."
URL="http://localhost:8080/Table-Talker.html"
if command -v open >/dev/null 2>&1; then
    open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"
else
    echo "    手动打开: $URL"
fi

echo ""
echo "========================================"
echo -e "  ${GREEN}🚀 Table-Talker 已启动${RESET}"
echo "========================================"
echo "  前端  : http://localhost:8080/Table-Talker.html"
echo "  后端  : http://localhost:8000/docs"
echo "  健康  : http://localhost:8000/api/health"
echo "  日志  : tail -f .run/backend.log"
echo ""
echo "  停止  : bash stop.sh"
echo "  预热  : bash warmup.sh   （演示前先跑一次让 React 编译完）"
echo "========================================"
