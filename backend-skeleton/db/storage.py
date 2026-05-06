"""SQLite 轻量持久化层（用 Python 标准库，无外部依赖）。

只存"看板"（dashboards）、"卡片"（dashboard_cards）、"报告"（reports）这 3 类资源。
开发阶段够用；生产化时可平迁到 PostgreSQL（同样的 SQL）。

文件位置：./tt.db（首次启动自动创建）
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", "./tt.db"))


def _now() -> int:
    """毫秒级时间戳（保证同一秒内多次插入也有序）。"""
    return int(time.time() * 1000)


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@contextmanager
def conn():
    """SQLite 连接上下文。每次新连接（SQLite 多连接安全）。"""
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    """首次启动建表（IF NOT EXISTS 幂等）。"""
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS dashboards (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            subtitle TEXT,
            owner TEXT,
            source_conv_id TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dashboard_cards (
            id TEXT PRIMARY KEY,
            dashboard_id TEXT NOT NULL,
            message_id TEXT,
            title TEXT,
            kind TEXT,
            chart_data TEXT,
            annotation TEXT,
            order_index INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (dashboard_id) REFERENCES dashboards(id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            template TEXT,
            format TEXT,
            conversation_id TEXT,
            file_path TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            completed_at INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_cards_dashboard ON dashboard_cards(dashboard_id);
        """)


# ============ Dashboards ============

def list_dashboards() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM dashboards ORDER BY updated_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["card_count"] = c.execute(
                "SELECT COUNT(*) AS n FROM dashboard_cards WHERE dashboard_id=?", (d["id"],)
            ).fetchone()["n"]
            out.append(d)
        return out


def get_dashboard(dashboard_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM dashboards WHERE id=?", (dashboard_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        cards = c.execute(
            "SELECT * FROM dashboard_cards WHERE dashboard_id=? ORDER BY order_index ASC, created_at ASC",
            (dashboard_id,),
        ).fetchall()
        d["cards"] = [dict(c) for c in cards]
        for card in d["cards"]:
            if card.get("chart_data"):
                try:
                    card["chart_data"] = json.loads(card["chart_data"])
                except Exception:
                    pass
        return d


def create_dashboard(title: str, owner: str = "巧玲", source_conv_id: str | None = None) -> str:
    did = _gen_id("dash")
    now = _now()
    with conn() as c:
        c.execute(
            "INSERT INTO dashboards (id, title, subtitle, owner, source_conv_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (did, title, f"来自 {source_conv_id} · 钉于刚刚" if source_conv_id else "刚刚创建", owner, source_conv_id, now, now),
        )
    return did


def add_card(
    dashboard_id: str,
    message_id: str | None = None,
    title: str = "",
    kind: str = "bars",
    chart_data: dict | None = None,
    annotation: str = "",
) -> str:
    cid = _gen_id("card")
    with conn() as c:
        order = c.execute(
            "SELECT COALESCE(MAX(order_index), 0) + 1 AS n FROM dashboard_cards WHERE dashboard_id=?",
            (dashboard_id,),
        ).fetchone()["n"]
        c.execute(
            "INSERT INTO dashboard_cards (id, dashboard_id, message_id, title, kind, chart_data, annotation, order_index, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, dashboard_id, message_id, title, kind,
             json.dumps(chart_data, ensure_ascii=False) if chart_data else None,
             annotation, order, _now()),
        )
        c.execute("UPDATE dashboards SET updated_at=? WHERE id=?", (_now(), dashboard_id))
    return cid


def delete_dashboard(dashboard_id: str) -> bool:
    with conn() as c:
        c.execute("DELETE FROM dashboard_cards WHERE dashboard_id=?", (dashboard_id,))
        c.execute("DELETE FROM dashboards WHERE id=?", (dashboard_id,))
    return True


# ============ Reports ============

def create_report(title: str, template: str = "monthly", fmt: str = "docx", conversation_id: str | None = None) -> str:
    rid = _gen_id("rpt")
    with conn() as c:
        c.execute(
            "INSERT INTO reports (id, title, template, format, conversation_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rid, title, template, fmt, conversation_id, "pending", _now()),
        )
    return rid


def update_report(report_id: str, status: str, file_path: str | None = None):
    with conn() as c:
        if status == "done":
            c.execute(
                "UPDATE reports SET status=?, file_path=?, completed_at=? WHERE id=?",
                (status, file_path, _now(), report_id),
            )
        else:
            c.execute("UPDATE reports SET status=? WHERE id=?", (status, report_id))


def get_report(report_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        return dict(row) if row else None


def list_reports() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM reports ORDER BY created_at DESC, id DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]
