#!/usr/bin/env bash
# Table-Talker 后端一键安装脚本（v2 - 严格错误检测）
# 用法：cd backend-skeleton && bash install.sh

set -e
set -o pipefail

cd "$(dirname "$0")"

echo "========================================"
echo "  Table-Talker 后端安装 v2"
echo "========================================"

# Step 0：检查代理（公司代理可能拦 PyPI）
echo ""
echo "→ 检查代理环境变量 ..."
PROXY_VARS=$(env | grep -i -E "^(http_proxy|https_proxy|all_proxy)=" || true)
if [ -n "$PROXY_VARS" ]; then
    echo "⚠️  检测到代理设置："
    echo "$PROXY_VARS"
    echo ""
    echo "→ 临时清除代理（仅本次安装期间）..."
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
fi

# Step 1：venv
if [ ! -d ".venv" ]; then
    echo "→ 创建虚拟环境 .venv ..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
PYBIN="$(which python)"
echo "✅ 虚拟环境：$PYBIN"
echo "   Python: $(python --version)"

# Step 2：pip 升级
echo ""
echo "→ 升级 pip ..."
python -m pip install --upgrade pip --disable-pip-version-check 2>&1 | tail -3 || {
    echo "❌ pip 升级失败，可能仍是网络问题"
    exit 1
}

# Step 3：试探网络（先装 1 个最小包）
echo ""
echo "→ 网络连通性测试（装一个 6KB 的小包 'six'）..."

MIRRORS=(
    "https://mirrors.aliyun.com/pypi/simple/|mirrors.aliyun.com"
    "https://pypi.tuna.tsinghua.edu.cn/simple/|pypi.tuna.tsinghua.edu.cn"
    "https://mirrors.cloud.tencent.com/pypi/simple/|mirrors.cloud.tencent.com"
    "https://pypi.org/simple/|pypi.org"
)

WORKING_MIRROR=""
for entry in "${MIRRORS[@]}"; do
    url="${entry%|*}"
    host="${entry##*|}"
    echo -n "  · 试 $host ... "
    if pip install -i "$url" --trusted-host "$host" --no-cache-dir --disable-pip-version-check six >/tmp/pip-probe.log 2>&1; then
        echo "✅ 通"
        WORKING_MIRROR="$url"
        WORKING_HOST="$host"
        break
    else
        echo "❌"
    fi
done

if [ -z "$WORKING_MIRROR" ]; then
    echo ""
    echo "❌❌❌ 所有 PyPI 镜像都不通"
    echo ""
    echo "可能原因："
    echo "  1. 公司网络拦了 PyPI 全网 → 试手机热点 / VPN / 亚信内网"
    echo "  2. SSL 证书拦截 → 你公司可能有 SSL 中间人"
    echo "  3. DNS 污染 → 试试 8.8.8.8 或 119.29.29.29"
    echo ""
    echo "诊断命令："
    echo "  curl -v https://mirrors.aliyun.com/pypi/simple/  # 看具体哪一步失败"
    echo "  cat /tmp/pip-probe.log                             # 上一次 pip 详细错误"
    exit 1
fi

echo ""
echo "✅ 用源：$WORKING_MIRROR"

# Step 4：装核心包（必须成功）
CORE="fastapi uvicorn[standard] pydantic sse-starlette python-multipart httpx openai tenacity duckdb pandas numpy plotly redis loguru python-dotenv"
echo ""
echo "→ 装核心 15 个包 ..."
pip install -i "$WORKING_MIRROR" --trusted-host "$WORKING_HOST" --no-cache-dir --disable-pip-version-check $CORE

# Step 5：装可选包（失败容忍）
OPTIONAL="python-docx reportlab sqlalchemy psycopg2-binary pymysql rdflib"
echo ""
echo "→ 装可选包 ..."
for pkg in $OPTIONAL; do
    if pip install -i "$WORKING_MIRROR" --trusted-host "$WORKING_HOST" --no-cache-dir --disable-pip-version-check --quiet "$pkg" 2>/dev/null; then
        echo "  ✅ $pkg"
    else
        echo "  ⚠️  $pkg 跳过（不影响主链路）"
    fi
done

# Step 6：导入测试
echo ""
echo "→ 验证核心包导入 ..."
python <<'PY'
import sys
ok = []
fail = []
for mod in ["fastapi", "uvicorn", "pydantic", "openai", "duckdb", "pandas", "numpy", "plotly", "sse_starlette", "loguru", "dotenv", "tenacity", "httpx"]:
    try:
        __import__(mod)
        ok.append(mod)
    except Exception as e:
        fail.append(f"{mod}: {e}")
print(f"\n✅ {len(ok)}/{len(ok)+len(fail)} 个核心包导入 OK")
if fail:
    print("失败:")
    for f in fail:
        print(f"  ❌ {f}")
    sys.exit(1)
PY

echo ""
echo "========================================"
echo "  ✅ 全部完成！"
echo "========================================"
echo ""
echo "下一步："
echo "  python tools/test_llm.py"
echo "  uvicorn main:app --reload --host 0.0.0.0 --port 8000"
