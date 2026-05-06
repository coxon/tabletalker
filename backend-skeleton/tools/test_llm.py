"""LLM 联通自测脚本。

用法：
    cd backend-skeleton
    pip install -r requirements.txt --break-system-packages
    python tools/test_llm.py

输出每个模型的：
    ✓ 联通  延迟（秒）  返回字符串前 80 字
    ✗ 失败  错误信息

环境变量从 .env 读取（仓库根目录或 backend-skeleton/.env）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# 自动加载 .env
try:
    from dotenv import load_dotenv
except ImportError:
    print("⚠️  请先 pip install python-dotenv")
    sys.exit(1)

# 优先级：当前目录 .env → 上级目录 .env → backend-skeleton/.env
for p in [
    Path(".env"),
    Path("../.env"),
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent.parent / ".env",
]:
    if p.exists():
        load_dotenv(p)
        print(f"✅ 加载配置：{p.resolve()}")
        break
else:
    print("⚠️  未找到 .env 文件，请先在仓库根目录或 backend-skeleton/ 下创建 .env")
    sys.exit(1)

from openai import AsyncOpenAI


MODELS = [
    os.getenv("LLM_MODEL_DEFAULT", "aliyun/qwen3.6-plus"),
    os.getenv("LLM_MODEL_SMALL", "aliyun/deepseek-v3.2"),
    os.getenv("LLM_MODEL_LONG", "aliyun/kimi-k2.5"),
    os.getenv("LLM_MODEL_FALLBACK", "aliyun/MiniMax-M2.5"),
    os.getenv("LLM_MODEL_FALLBACK_2", "aliyun/glm-5"),
]

QUESTION = "请用一句话介绍你自己（包含模型名/版本）。"


async def test_one(client: AsyncOpenAI, model: str) -> dict:
    t0 = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": QUESTION}],
            max_tokens=200,
            temperature=0.3,
        )
        ms = int((time.time() - t0) * 1000)
        return {
            "model": model,
            "ok": True,
            "latency_ms": ms,
            "echo": resp.choices[0].message.content[:200],
            "tokens": resp.usage.total_tokens if resp.usage else None,
        }
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"model": model, "ok": False, "latency_ms": ms, "error": str(e)[:300]}


async def main():
    api_key = os.getenv("LLM_API_KEY") or os.getenv("QWEN_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://aigw.asiainfo.com/v1")

    if not api_key or api_key.startswith("sk-xxxxx"):
        print("⚠️  LLM_API_KEY 未配置或为占位符")
        sys.exit(1)

    print(f"\n🌐 网关: {base_url}")
    print(f"🔑 Key:  {api_key[:8]}...{api_key[-4:]}")
    print(f"📋 待测 {len(MODELS)} 个模型\n" + "=" * 80)

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0)

    # 顺序测，便于看每个的耗时
    results = []
    for m in MODELS:
        print(f"\n→ 测试 {m} ...", flush=True)
        r = await test_one(client, m)
        results.append(r)
        if r["ok"]:
            print(f"  ✅ {r['latency_ms']}ms · tokens={r.get('tokens')}")
            print(f"  💬 {r['echo']}")
        else:
            print(f"  ❌ {r['latency_ms']}ms · {r['error']}")

    # 汇总
    print("\n" + "=" * 80)
    ok = sum(1 for r in results if r["ok"])
    fail = len(results) - ok
    print(f"汇总：{ok} 通过 / {fail} 失败")
    if ok > 0:
        avg = sum(r["latency_ms"] for r in results if r["ok"]) / ok
        print(f"平均延迟：{int(avg)}ms")
    if fail > 0:
        print("\n失败模型：")
        for r in results:
            if not r["ok"]:
                print(f"  - {r['model']}: {r['error']}")
    return ok, fail


if __name__ == "__main__":
    ok, fail = asyncio.run(main())
    sys.exit(0 if fail == 0 else 1)
