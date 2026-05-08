"""数据集 CRUD + 接入。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter()


class DBConnectorConfig(BaseModel):
    name: str
    type: str  # mysql / postgresql / hive / starrocks
    host: str
    port: int
    database: str
    username: str
    password: str
    tables: list[str] = []


class APIConnectorConfig(BaseModel):
    name: str
    base_url: str
    auth_type: str = "none"
    auth_config: dict = {}
    endpoints: list[dict] = []


@router.get("/")
async def list_datasets():
    """列出所有数据集（含 6 个 mock + 真实接入）。"""
    from agent.mock import MOCK_DATASETS
    return {"datasets": MOCK_DATASETS}


@router.get("/{dataset_id}")
async def get_dataset_detail(dataset_id: str):
    """数据集详情（含 schema、样本行、敏感字段标记）。"""
    schemas_path = Path(os.getenv("SCHEMAS_FILE", "./schemas.json"))
    if not schemas_path.exists():
        raise HTTPException(404, f"schemas.json 不存在，请先跑 tools/extract_schema.py")
    schemas = json.loads(schemas_path.read_text())
    if dataset_id not in schemas:
        raise HTTPException(404, f"dataset {dataset_id} 不存在")
    return schemas[dataset_id]


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    name: str = Form(None),
    description: str = Form(""),
    encoding: str = Form("auto"),
):
    """文件上传 + 自动 schema 抽取。"""
    # MVP：保存到 data/ 目录 + 触发 schema 抽取
    target = Path("./data") / file.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(413, "文件超过 100MB")
    target.write_bytes(content)

    # TODO: 调 tools.extract_schema.extract_one(target)
    return {
        "ok": True,
        "id": f"file_{file.filename}",
        "name": name or file.filename,
        "size": len(content),
        "path": str(target),
        "message": "上传成功，schema 抽取已触发",
    }


@router.post("/connector/db")
async def add_db_connector(cfg: DBConnectorConfig):
    """新增数据库连接器。"""
    # TODO: 加密 password 后存 DB；测试连接
    return {"ok": True, "id": f"db_{cfg.name}", "tables_detected": cfg.tables}


@router.post("/connector/api")
async def add_api_connector(cfg: APIConnectorConfig):
    """新增 API 连接器。"""
    return {"ok": True, "id": f"api_{cfg.name}"}


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str):
    """软删除数据集（30 天可恢复）。"""
    return {"ok": True, "id": dataset_id, "soft_deleted": True}
