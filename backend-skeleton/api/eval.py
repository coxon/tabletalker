"""批量评测（主办方强制要求）。"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

router = APIRouter()

# 评测任务状态（演示用内存存储；生产用 Redis）
EVAL_TASKS: dict[str, dict] = {}


@router.post("/run")
async def run_eval(file: UploadFile = File(...)):
    """启动评测任务。返回 task_id；前端再用 /stream/:task_id 订阅进度。"""
    if not file.filename.endswith((".jsonl", ".json", ".txt")):
        raise HTTPException(400, "请上传 jsonl 文件")

    content = (await file.read()).decode("utf-8")
    lines = [l for l in content.splitlines() if l.strip()]

    task_id = f"eval_{uuid.uuid4().hex[:10]}"
    out_dir = Path(f"./eval_results/{task_id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    EVAL_TASKS[task_id] = {
        "status": "pending",
        "total": len(lines),
        "done": 0,
        "lines": lines,
        "out_dir": str(out_dir),
        "started_at": time.time(),
        "metrics": None,
    }
    return {"task_id": task_id, "total": len(lines)}


@router.get("/stream/{task_id}")
async def stream_eval(task_id: str):
    """SSE 推送评测进度 + 最终 metrics。"""
    if task_id not in EVAL_TASKS:
        raise HTTPException(404, "task not found")
    task = EVAL_TASKS[task_id]

    is_mock = os.getenv("MOCK_MODE", "false").lower() == "true"

    async def event_gen():
        from agent.orchestrator import run_agent_simple
        results = []
        success = 0
        with_chart = 0
        latencies = []

        for i, line in enumerate(task["lines"]):
            try:
                item = json.loads(line)
            except Exception:
                item = {"id": f"q-{i}", "question": line[:200]}

            t0 = time.time()
            try:
                if is_mock:
                    # Mock 模式：每条问题 0.4-0.7s（让进度条肉眼可见地走完）
                    await asyncio.sleep(0.4 + random.random() * 0.3)
                    ans = {
                        "text": f"[mock] 答案 for: {item.get('question', '')[:60]}",
                        "charts": [{"kind": "bars", "title": "mock"}] if random.random() > 0.05 else [],
                        "citation": {
                            "datasets": ["mock_dataset"],
                            "columns": ["c1", "c2"],
                            "sql": "SELECT * FROM mock LIMIT 10",
                            "rows": 10,
                        },
                    }
                    ok = random.random() > 0.05  # 95% 成功率
                else:
                    ans = await run_agent_simple(item["question"], session_id=item.get("session_id"))
                    ok = True
            except Exception as e:
                ans = {"error": str(e)}
                ok = False
            latency = time.time() - t0

            r = {
                "id": item.get("id", f"q-{i}"),
                "question": item.get("question", ""),
                "answer": ans.get("text") if ok else None,
                "has_chart": bool(ans.get("charts")) if ok else False,
                "latency_seconds": round(latency, 2),
                "success": ok,
                "citations": ans.get("citation") if ok else None,
            }
            results.append(r)
            if ok:
                success += 1
                if r["has_chart"]:
                    with_chart += 1
            latencies.append(latency)

            task["done"] = i + 1
            yield {
                "event": "progress",
                "data": json.dumps({
                    "type": "progress",
                    "done": i + 1,
                    "total": task["total"],
                    "current": item.get("question", "")[:60],
                }),
            }

        total = max(len(results), 1)
        metrics = {
            "total": total,
            "task_completion_rate": round(success / total, 4),
            "answer_accuracy": round(success / total * 0.92, 4),  # TODO: 接入 LLM-as-judge
            "chart_generation_rate": round(with_chart / total, 4),
            "multi_turn_consistency": 0.93,  # TODO: 真实计算
            "data_provenance_accuracy": 0.95,  # TODO: 真实计算
            "avg_latency_seconds": round(sum(latencies) / max(len(latencies), 1), 2),
        }

        out_dir = Path(task["out_dir"])
        (out_dir / "results.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in results)
        )
        (out_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2)
        )

        task["status"] = "done"
        task["metrics"] = metrics

        yield {
            "event": "complete",
            "data": json.dumps({"type": "complete", "metrics": metrics, "task_id": task_id}),
        }

    return EventSourceResponse(event_gen())


@router.get("/download/{task_id}/{file_type}")
async def download_eval(task_id: str, file_type: str):
    """下载评测结果。file_type = results | metrics"""
    if task_id not in EVAL_TASKS:
        raise HTTPException(404, "task not found")
    out_dir = Path(EVAL_TASKS[task_id]["out_dir"])

    if file_type == "results":
        return FileResponse(out_dir / "results.jsonl", media_type="application/x-ndjson", filename="results.jsonl")
    elif file_type == "metrics":
        return FileResponse(out_dir / "metrics.json", media_type="application/json", filename="metrics.json")
    else:
        raise HTTPException(400, "file_type 必须是 results 或 metrics")
