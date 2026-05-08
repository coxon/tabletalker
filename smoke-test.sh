#!/usr/bin/env bash
# Table-Talker 冒烟测试 · 一键确认核心链路全 OK
# 用法：
#   bash smoke-test.sh           # 默认本地（localhost）
#   BASE=http://10.x.x.x:8000 FRONT=http://10.x.x.x:8080 bash smoke-test.sh   # 内网部署
#
# 退出码：0=全 OK，非 0=有失败项

set +e   # 不要在第一个失败时退出，跑完所有再汇总
cd "$(dirname "$0")"

BASE="${BASE:-http://localhost:8000}"
FRONT="${FRONT:-http://localhost:8080}"
EVAL_FILE="${EVAL_FILE:-evaluation/sample_eval.jsonl}"

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
BOLD="\033[1m"
RESET="\033[0m"

ok()   { echo -e "  ${GREEN}✅${RESET} $1"; OK_COUNT=$((OK_COUNT + 1)); }
fail() { echo -e "  ${RED}❌${RESET} $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); FAIL_ITEMS+=("$1"); }
warn() { echo -e "  ${YELLOW}⚠${RESET} $1"; }
section() { echo -e "\n${BOLD}━━━ $1 ━━━${RESET}"; }

OK_COUNT=0
FAIL_COUNT=0
FAIL_ITEMS=()

echo -e "${BOLD}════════════════════════════════════════"
echo -e "  Table-Talker · 冒烟测试"
echo -e "════════════════════════════════════════${RESET}"
echo -e "  Backend : $BASE"
echo -e "  Frontend: $FRONT"
echo -e "  Eval    : $EVAL_FILE"

# ============ Step 1：后端基础 ============
section "1/7 后端健康"

H=$(curl -s -m 3 -w "\n%{http_code}" "$BASE/api/health")
HCODE=$(echo "$H" | tail -n1)
# macOS head 不支持 -n-1，用 sed '$d' 跨平台
HBODY=$(echo "$H" | sed '$d')
if [ "$HCODE" = "200" ]; then
    ok "/api/health 返回 200"
    if echo "$HBODY" | grep -q '"status":"ok"'; then ok "status=ok"
    else fail "status 字段缺失或非 ok"; fi
    if echo "$HBODY" | grep -q '"models_configured"'; then ok "models_configured 存在"
    else fail "models_configured 字段缺失"; fi
    MOCK=$(echo "$HBODY" | python3 -c "import json,sys;print(json.load(sys.stdin).get('mock_mode'))" 2>/dev/null)
    echo -e "    ${YELLOW}ℹ${RESET}  Mock mode: $MOCK"
else
    fail "/api/health 不通（HTTP $HCODE）。后端可能没起，跑 bash start.sh"
    echo -e "    ${YELLOW}ℹ${RESET}  其余测试无意义，stop early"
    echo -e "\n${RED}━━━ 失败 ━━━${RESET}"
    exit 1
fi

# ============ Step 2：对话流式 ============
section "2/7 对话 SSE"

CHAT_RESP=$(curl -s -m 8 -X POST "$BASE/api/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"question":"Q1 华南销售下滑原因","mode":"business"}')
if echo "$CHAT_RESP" | grep -q 'event: trace_step'; then ok "SSE trace_step 事件就绪"
else fail "SSE 无 trace_step 事件"; fi
if echo "$CHAT_RESP" | grep -q 'event: answer_chunk'; then ok "SSE answer_chunk 事件就绪"
else fail "SSE 无 answer_chunk 事件"; fi
if echo "$CHAT_RESP" | grep -q 'event: chart'; then ok "SSE chart 事件就绪"
else warn "SSE 无 chart 事件（fallback 路径可能命中）"; fi
if echo "$CHAT_RESP" | grep -q 'event: complete\|event: done'; then ok "SSE 流正常关闭"
else fail "SSE 无 complete/done 终止事件"; fi

# 测一下空 question 不再 422
EMPTY_CHAT=$(curl -s -o /dev/null -w "%{http_code}" -m 5 -X POST "$BASE/api/chat/stream" \
  -H "Content-Type: application/json" -d '{}')
if [ "$EMPTY_CHAT" = "200" ]; then ok "空 question 不报 422（200）"
else fail "空 question 异常返回 $EMPTY_CHAT"; fi

# ============ Step 3：批量评测 ============
section "3/7 批量评测"

if [ -f "$EVAL_FILE" ]; then
    EVAL_RESP=$(curl -s -m 5 -F "file=@$EVAL_FILE" "$BASE/api/eval/run")
    if echo "$EVAL_RESP" | grep -q '"task_id"'; then
        ok "上传 jsonl + 拿到 task_id"
        TASK_ID=$(echo "$EVAL_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['task_id'])")
        TOTAL=$(echo "$EVAL_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['total'])")
        echo -e "    ${YELLOW}ℹ${RESET}  task_id=$TASK_ID, total=$TOTAL"

        # 流进度（最多等 15s）
        STREAM=$(curl -s -m 15 "$BASE/api/eval/stream/$TASK_ID")
        if echo "$STREAM" | grep -q 'event: complete'; then
            ok "评测流式完成"
            METRICS=$(curl -s -m 3 "$BASE/api/eval/download/$TASK_ID/metrics")
            if echo "$METRICS" | grep -q 'task_completion_rate'; then
                ok "metrics.json 可下载"
                RATE=$(echo "$METRICS" | python3 -c "import json,sys;d=json.load(sys.stdin);print(f\"{d.get('task_completion_rate',0)*100:.0f}%\")" 2>/dev/null)
                echo -e "    ${YELLOW}ℹ${RESET}  完成率 $RATE"
            else fail "metrics.json 内容异常"; fi
            RESULTS=$(curl -s -m 3 "$BASE/api/eval/download/$TASK_ID/results")
            if echo "$RESULTS" | grep -q 'question'; then ok "results.jsonl 可下载"
            else fail "results.jsonl 内容异常"; fi
        else fail "评测流没等到 complete 事件"; fi
    else fail "评测 /run 上传失败"; fi
else warn "评测样本 $EVAL_FILE 不存在，跳过批量评测测试"; fi

# ============ Step 4：看板持久化 ============
section "4/7 看板（SQLite 持久化）"

PIN=$(curl -s -m 3 -X POST "$BASE/api/dashboard/pin" \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke Test 看板","kind":"bars","message_id":"msg_smoke","chart_data":{"data":[{"x":"A","y":1}]}}')
if echo "$PIN" | grep -q '"dashboard_id"'; then
    ok "看板钉住 → 写入数据库"
    DASH_ID=$(echo "$PIN" | python3 -c "import json,sys;print(json.load(sys.stdin)['dashboard_id'])")
    LIST=$(curl -s -m 3 "$BASE/api/dashboard/")
    if echo "$LIST" | grep -q "$DASH_ID"; then ok "看板列表能查到刚才的 ID"
    else fail "看板列表没出现新建的 ID"; fi
    DETAIL=$(curl -s -m 3 "$BASE/api/dashboard/$DASH_ID")
    if echo "$DETAIL" | grep -q "Smoke Test"; then ok "看板详情含 cards"
    else fail "看板详情缺失 title 或 cards"; fi
else fail "看板钉住接口失败"; fi

# ============ Step 5：报告 docx 生成 ============
section "5/7 报告 docx 生成"

REPORT=$(curl -s -m 3 -X POST "$BASE/api/report/generate" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"c1","template":"monthly","title":"Smoke Test 报告"}')
if echo "$REPORT" | grep -q '"report_id"'; then
    RID=$(echo "$REPORT" | python3 -c "import json,sys;print(json.load(sys.stdin)['report_id'])")
    ok "报告生成任务已创建（$RID）"

    # 等 8 秒等后台生成完成
    for i in 1 2 3 4 5 6 7 8 9 10; do
        sleep 1
        STATUS=$(curl -s -m 2 "$BASE/api/report/$RID/status")
        if echo "$STATUS" | grep -q '"status":"done"'; then break; fi
    done

    if echo "$STATUS" | grep -q '"status":"done"'; then
        ok "报告 ${i}s 内生成完成"
        # 下载验证大小 > 5KB
        DL_FILE="/tmp/smoke-report-$RID.docx"
        curl -s -m 5 "$BASE/api/report/$RID/download" -o "$DL_FILE"
        SIZE=$(wc -c < "$DL_FILE" 2>/dev/null || echo 0)
        if [ "$SIZE" -gt 5000 ]; then
            ok "报告 docx 文件正常下载（$(echo "scale=1; $SIZE/1024" | bc 2>/dev/null || echo '?') KB）"
            rm -f "$DL_FILE"
        else fail "报告文件大小异常 ($SIZE bytes)"; fi
    else fail "报告生成超时（等了 10s 仍非 done）"; fi
else fail "报告 /generate 失败"; fi

# ============ Step 6：数据集 ============
section "6/7 数据集列表"

DS=$(curl -s -m 3 "$BASE/api/datasets/")
DS_COUNT=$(echo "$DS" | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('datasets',[])))" 2>/dev/null)
if [ "$DS_COUNT" -ge 1 ] 2>/dev/null; then ok "数据集列表 $DS_COUNT 个"
else fail "数据集列表为空或异常"; fi

# ============ Step 7：前端 ============
section "7/7 前端可访问"

FRONT_CODE=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "$FRONT/Table-Talker.html")
if [ "$FRONT_CODE" = "200" ]; then ok "前端 Table-Talker.html 可访问"
else fail "前端不可访问（HTTP $FRONT_CODE，跑 bash start.sh）"; fi

# 检查关键 JS 文件
for f in api.js app.jsx chat.jsx data.js styles/tokens.css; do
    CODE=$(curl -s -o /dev/null -m 2 -w "%{http_code}" "$FRONT/$f")
    if [ "$CODE" = "200" ]; then ok "$f 200"
    else fail "$f 缺失（HTTP $CODE）"; fi
done

# ============ 总结 ============
echo ""
echo -e "${BOLD}════════════════════════════════════════"
echo -e "  汇总"
echo -e "════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}通过${RESET}: $OK_COUNT"
echo -e "  ${RED}失败${RESET}: $FAIL_COUNT"

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "\n${GREEN}${BOLD}🎉 全部 OK，可以演示 / 提交${RESET}"
    exit 0
else
    echo ""
    echo -e "${RED}失败项：${RESET}"
    for item in "${FAIL_ITEMS[@]}"; do
        echo -e "  ${RED}•${RESET} $item"
    done
    echo ""
    echo -e "${YELLOW}排查见 TROUBLESHOOTING.md${RESET}"
    exit 1
fi
