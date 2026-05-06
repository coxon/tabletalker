"""演示问题缓存预热脚本。

跑法：
    cd backend-skeleton
    source .venv/bin/activate
    NO_PROXY="aigw.asiainfo.com,localhost,127.0.0.1" HTTPS_PROXY="" \\
      python tools/warm_cache.py

会把 7 个 demo 题各跑一次真实 LLM 链路，把所有 SSE 事件存到 cache/answers/{md5}.json
之后启动后端时设环境变量 WARM_CACHE=true，命中缓存的问题会在 ~3 秒内回放完整结果。

整体耗时：7 题 × ~90 秒/题 ≈ 10 分钟（演示前一晚跑一次即可）

如果某题预热失败：
- 不影响其他题
- 演示时该题穿透到真 LLM (~90 秒)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# 添加项目根到 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 强制走真实 LLM（不读取已有缓存，否则递归）
os.environ["WARM_CACHE"] = "false"
os.environ["MOCK_MODE"] = "false"

from api.cache import write_cache, cache_key_path, CACHE_DIR  # noqa: E402
from agent.orchestrator import run_agent  # noqa: E402


# ============ 演示问题清单 ============
# 这些是演示视频 / 决赛 PPT 里要复现的"必问题"
# 调整建议：保持 5-7 个；超过 7 个预热时间会很长
DEMO_QUESTIONS = [
    "近 6 个月销售走势",
    "本月各渠道销售占比",
    "Top 10 客户排行",
    "本月销售总额",
    "Q1 华南区销售为什么环比下滑？",
    "BU-3 流动率为什么这么高",
    "5G 套餐迁移对 ARPU 的影响",
]


# ============ 时间压缩配置 ============
# 真实跑一次问题 ~90 秒，全部 replay 太慢。把每个事件之间的延迟压缩：
#   原始：trace_step running 后等 80 秒才 done（codegen 慢）
#   压缩：最多 200ms 延迟（trace 动画还能看到，但不傻等）
MAX_DELAY_MS = 200    # 单事件最大延迟（毫秒）
MIN_DELAY_MS = 20     # 单事件最小延迟（避免瞬时全部刷出，没有"思考"感）
COMPRESSION = 10      # 实际延迟 ÷ COMPRESSION 后再 clamp


async def warm_one(question: str) -> dict:
    """预热单个问题，返回 stats."""
    print(f"\n🔥 预热问题：{question}")
    t0 = time.time()

    events: list[dict] = []
    last_t = time.time()

    try:
        async for ev in run_agent(
            question=question,
            mode="business",
            session_id=f"warm-{int(time.time())}",
            message_id=f"msg-warm-{int(time.time() * 1000) % 1_000_000}",
        ):
            now = time.time()
            # 把"距上一个事件的真实间隔"先记下来，等会一次性压缩
            real_delay_ms = int((now - last_t) * 1000)
            ev["_delay_ms"] = real_delay_ms
            events.append(dict(ev))  # 浅拷贝
            last_t = now
    except Exception as e:
        return {"question": question, "ok": False, "error": str(e)[:200]}

    # 压缩延迟
    for ev in events:
        compressed = max(MIN_DELAY_MS, min(MAX_DELAY_MS, ev["_delay_ms"] // COMPRESSION))
        ev["_delay_ms"] = compressed

    # 写盘
    cache_file = write_cache(question, events)

    elapsed = time.time() - t0
    replay_total = sum(ev["_delay_ms"] for ev in events) / 1000.0

    return {
        "question": question,
        "ok": True,
        "events": len(events),
        "real_seconds": round(elapsed, 1),
        "replay_seconds": round(replay_total, 1),
        "cache_file": str(cache_file),
    }


async def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(f"🚀 演示问题缓存预热 · 共 {len(DEMO_QUESTIONS)} 题")
    print(f"   缓存目录：{CACHE_DIR.absolute()}")
    print("=" * 70)

    results = []
    for q in DEMO_QUESTIONS:
        r = await warm_one(q)
        results.append(r)
        if r["ok"]:
            print(f"   ✅ 真实 {r['real_seconds']}s · 回放 {r['replay_seconds']}s · {r['events']} 事件")
        else:
            print(f"   ❌ 失败：{r['error']}")

    print()
    print("=" * 70)
    ok_count = sum(1 for r in results if r["ok"])
    print(f"✅ 完成：{ok_count}/{len(DEMO_QUESTIONS)} 题预热成功")
    if ok_count < len(DEMO_QUESTIONS):
        print(f"⚠️  失败的题：{[r['question'] for r in results if not r['ok']]}")
        print("   失败题不会有缓存，演示时穿透到真 LLM (~90 秒)")
    print()
    print("📋 后续步骤：")
    print("   1. .env 加：WARM_CACHE=true")
    print("   2. 重启后端")
    print("   3. 演示时问 demo 题 → 命中缓存 ~3 秒响应")
    print("   4. 评委即兴问的题 → 穿透真 LLM ~90 秒")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
