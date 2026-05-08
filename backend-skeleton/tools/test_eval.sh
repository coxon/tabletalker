#!/usr/bin/env bash
# 一键测后端批量评测端到端：upload → stream → done
# 用法：bash tools/test_eval.sh [评测文件路径]

set -e

FILE="${1:-/Users/zhangql/cc/黑松客比赛asiainfo/frontend-demo/sample_eval.jsonl}"
BASE="${BASE:-http://localhost:8000}"

if [ ! -f "$FILE" ]; then
    echo "❌ 文件不存在：$FILE"
    exit 1
fi

echo "→ Step 1: 上传 $FILE 到 $BASE/api/eval/run ..."
RESP=$(curl -s -F "file=@$FILE" "$BASE/api/eval/run")
echo "   响应: $RESP"

TASK_ID=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('task_id', ''))")
TOTAL=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total', 0))")

if [ -z "$TASK_ID" ]; then
    echo "❌ 没拿到 task_id"
    exit 1
fi

echo "✅ task_id = $TASK_ID, total = $TOTAL"

echo ""
echo "→ Step 2: 流式订阅 $BASE/api/eval/stream/$TASK_ID"
echo "   （会逐条输出 progress + 最后 complete）"
echo "----------------------------------------"

curl -N -s "$BASE/api/eval/stream/$TASK_ID" | head -50

echo ""
echo "----------------------------------------"
echo "→ Step 3: 下载 metrics"
curl -s "$BASE/api/eval/download/$TASK_ID/metrics" | python3 -m json.tool
echo ""
echo "✅ 测试完成"
