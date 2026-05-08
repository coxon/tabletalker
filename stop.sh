#!/usr/bin/env bash
# Table-Talker 一键停服
# 用法：bash stop.sh

cd "$(dirname "$0")"

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RESET="\033[0m"

echo "→ 停止 Table-Talker 服务 ..."

# 先用记录的 PID 杀
for f in .run/backend.pid .run/frontend.pid; do
    if [ -f "$f" ]; then
        PID=$(cat "$f")
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null && echo -e "  ${GREEN}✅${RESET} 停止 PID=$PID"
        fi
        rm -f "$f"
    fi
done

# 兜底：按端口杀
for PORT in 8000 8080; do
    PIDS=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$PIDS" ]; then
        echo "$PIDS" | xargs kill -9 2>/dev/null
        echo -e "  ${YELLOW}⚠️${RESET}  按端口 $PORT 杀掉残留进程"
    fi
done

# 兜底：按进程名杀
pkill -9 -f "uvicorn main:app" 2>/dev/null && echo -e "  ${YELLOW}⚠️${RESET}  按名字杀掉残留 uvicorn"
pkill -9 -f "python3 -m http.server 8080" 2>/dev/null && echo -e "  ${YELLOW}⚠️${RESET}  按名字杀掉残留 http.server"

echo -e "${GREEN}✅ Table-Talker 已停${RESET}"
