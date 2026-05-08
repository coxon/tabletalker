"""SQLite 持久化层单元测试。"""
from __future__ import annotations

import pytest

from db import storage


@pytest.fixture
def db():
    """初始化 fresh db。"""
    storage.init_db()
    yield storage


def test_create_dashboard(db):
    did = db.create_dashboard("测试看板", owner="tester")
    assert did.startswith("dash_")
    assert len(did) > 5


def test_get_dashboard(db):
    did = db.create_dashboard("Get test")
    d = db.get_dashboard(did)
    assert d is not None
    assert d["title"] == "Get test"
    assert d["owner"] == "巧玲"  # default
    assert d["cards"] == []


def test_get_nonexistent_dashboard(db):
    assert db.get_dashboard("dash_notexist") is None


def test_add_card_to_dashboard(db):
    did = db.create_dashboard("Card host")
    cid = db.add_card(
        dashboard_id=did,
        message_id="msg_test",
        title="测试卡片",
        kind="bars",
        chart_data={"data": [{"x": 1, "y": 10}]},
        annotation="人工注释",
    )
    assert cid.startswith("card_")
    d = db.get_dashboard(did)
    assert len(d["cards"]) == 1
    assert d["cards"][0]["title"] == "测试卡片"
    assert d["cards"][0]["chart_data"] == {"data": [{"x": 1, "y": 10}]}


def test_card_order_index_auto_increment(db):
    did = db.create_dashboard("Order test")
    db.add_card(did, title="第一张")
    db.add_card(did, title="第二张")
    db.add_card(did, title="第三张")
    d = db.get_dashboard(did)
    orders = [c["order_index"] for c in d["cards"]]
    assert orders == sorted(orders), "卡片应按 order_index 递增"


def test_list_dashboards_with_count(db):
    did1 = db.create_dashboard("A")
    did2 = db.create_dashboard("B")
    db.add_card(did1, title="x")
    db.add_card(did1, title="y")
    db.add_card(did2, title="z")
    rows = db.list_dashboards()
    by_id = {r["id"]: r for r in rows}
    assert by_id[did1]["card_count"] == 2
    assert by_id[did2]["card_count"] == 1


def test_delete_dashboard_cascades_cards(db):
    did = db.create_dashboard("To delete")
    db.add_card(did, title="x")
    db.delete_dashboard(did)
    assert db.get_dashboard(did) is None


def test_create_and_complete_report(db):
    rid = db.create_report("月报", template="monthly", fmt="docx")
    assert rid.startswith("rpt_")

    r = db.get_report(rid)
    assert r["status"] == "pending"
    assert r["title"] == "月报"

    db.update_report(rid, "done", "/tmp/report.docx")
    r2 = db.get_report(rid)
    assert r2["status"] == "done"
    assert r2["file_path"] == "/tmp/report.docx"
    assert r2["completed_at"] is not None


def test_list_reports_recent_first(db):
    import time
    db.create_report("旧 1"); time.sleep(0.005)
    db.create_report("旧 2"); time.sleep(0.005)
    db.create_report("最新")
    rows = db.list_reports()
    assert rows[0]["title"] == "最新"
