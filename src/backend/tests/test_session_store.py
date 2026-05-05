"""Session store TTL/LRU + workspace cleanup tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.session import Session, SessionStore, Turn


def _mk_session(
    sid: str, workspace: Path, *, refused: bool = False, last_used: float | None = None
) -> Session:
    workspace.mkdir(parents=True, exist_ok=True)
    s = Session(
        id=sid,
        workspace_dir=workspace,
        filename="data.csv",
        dataset="ds",
        original_question="q",
        findings=[],
        refused=refused,
    )
    if last_used is not None:
        s.last_used_at = last_used
    return s


def test_store_put_and_get_roundtrip(tmp_path: Path) -> None:
    store = SessionStore()
    store.put(_mk_session("a", tmp_path / "a"))
    fetched = store.get("a")
    assert fetched is not None
    assert fetched.id == "a"


def test_store_get_returns_none_for_missing() -> None:
    store = SessionStore()
    assert store.get("missing") is None


def test_store_evicts_expired_entries_on_get(tmp_path: Path) -> None:
    """Past-TTL entries vanish on access AND have their workspace cleaned."""

    store = SessionStore(ttl_seconds=0.01)
    workspace = tmp_path / "stale"
    store.put(_mk_session("stale", workspace))
    time.sleep(0.05)
    assert store.get("stale") is None
    # Workspace cleanup is best-effort but synchronous on TTL-miss.
    assert not workspace.exists()


def test_store_lru_trim_drops_oldest(tmp_path: Path) -> None:
    store = SessionStore(max_sessions=2)
    store.put(_mk_session("a", tmp_path / "a"))
    store.put(_mk_session("b", tmp_path / "b"))
    store.put(_mk_session("c", tmp_path / "c"))  # forces eviction of "a"
    assert store.get("a") is None
    assert store.get("b") is not None
    assert store.get("c") is not None
    # Evicted workspace gets cleaned up.
    assert not (tmp_path / "a").exists()


def test_store_get_refreshes_lru(tmp_path: Path) -> None:
    """Accessing 'a' before adding 'c' should evict 'b' (now LRU), not 'a'."""

    store = SessionStore(max_sessions=2)
    store.put(_mk_session("a", tmp_path / "a"))
    store.put(_mk_session("b", tmp_path / "b"))
    assert store.get("a") is not None  # bumps a to MRU
    store.put(_mk_session("c", tmp_path / "c"))
    assert store.get("a") is not None
    assert store.get("b") is None


def test_append_turn_updates_last_used(tmp_path: Path) -> None:
    store = SessionStore()
    store.put(_mk_session("a", tmp_path / "a", last_used=time.time() - 100))
    turn = Turn(index=1, kind="follow_up", question="q", response_id="r", is_refusal=False)
    store.append_turn("a", turn)
    fetched = store.get("a")
    assert fetched is not None
    assert fetched.turns[-1] is turn
    assert (time.time() - fetched.last_used_at) < 1.0


def test_append_turn_raises_for_unknown_session() -> None:
    store = SessionStore()
    with pytest.raises(KeyError):
        store.append_turn(
            "nope",
            Turn(index=1, kind="follow_up", question="q", response_id="r", is_refusal=False),
        )


def test_clear_removes_all_and_cleans_workspaces(tmp_path: Path) -> None:
    store = SessionStore()
    store.put(_mk_session("a", tmp_path / "a"))
    store.put(_mk_session("b", tmp_path / "b"))
    store.clear()
    assert len(store) == 0
    assert not (tmp_path / "a").exists()
    assert not (tmp_path / "b").exists()


def test_invalid_max_sessions_rejected() -> None:
    with pytest.raises(ValueError):
        SessionStore(max_sessions=0)
    with pytest.raises(ValueError):
        SessionStore(ttl_seconds=0)


def test_allocate_follow_up_turn_is_unique_per_call(tmp_path: Path) -> None:
    """Two consecutive allocations against the same session must produce
    distinct ids — the route relies on this for `_qN` collision safety
    even before we hand out any responses."""

    store = SessionStore()
    store.put(_mk_session("p", tmp_path / "p"))

    def factory(sid: str, idx: int) -> str:
        return f"eval_follow_{sid}_q{idx}"

    id1, idx1 = store.allocate_follow_up_turn("p", id_factory=factory)
    id2, idx2 = store.allocate_follow_up_turn("p", id_factory=factory)
    assert id1 != id2
    assert idx1 + 1 == idx2

    fetched = store.get("p")
    assert fetched is not None
    # Two placeholder turns reserved.
    assert len(fetched.turns) == 2


def test_set_turn_response_overwrites_placeholder(tmp_path: Path) -> None:
    store = SessionStore()
    store.put(_mk_session("p", tmp_path / "p"))
    _, turn_index = store.allocate_follow_up_turn(
        "p", id_factory=lambda sid, idx: f"id-{idx}"
    )
    store.set_turn_response(
        "p", turn_index, question="real question", is_refusal=False
    )
    fetched = store.get("p")
    assert fetched is not None
    assert fetched.turns[turn_index].question == "real question"


def test_discard_turn_rolls_back_placeholder(tmp_path: Path) -> None:
    store = SessionStore()
    store.put(_mk_session("p", tmp_path / "p"))
    _, turn_index = store.allocate_follow_up_turn(
        "p", id_factory=lambda sid, idx: f"id-{idx}"
    )
    store.discard_turn("p", turn_index)
    fetched = store.get("p")
    assert fetched is not None
    assert fetched.turns == []  # placeholder removed; q-counter not consumed


def test_allocate_follow_up_raises_keyerror_for_missing_session() -> None:
    store = SessionStore()
    with pytest.raises(KeyError):
        store.allocate_follow_up_turn(
            "missing", id_factory=lambda sid, idx: "x"
        )


def test_set_turn_response_raises_keyerror_after_eviction(tmp_path: Path) -> None:
    """Mid-flight eviction surfaces as KeyError so the route maps to 404."""

    store = SessionStore()
    store.put(_mk_session("p", tmp_path / "p"))
    _, turn_index = store.allocate_follow_up_turn(
        "p", id_factory=lambda sid, idx: f"id-{idx}"
    )
    store.clear()  # simulate TTL/LRU eviction
    with pytest.raises(KeyError):
        store.set_turn_response(
            "p", turn_index, question="q", is_refusal=False
        )
