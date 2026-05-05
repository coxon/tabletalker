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

    # Allocate must be paired with set/discard in real usage so the
    # per-session lock is released; mirror that here so the second
    # allocation isn't blocked on its own predecessor.
    id1, idx1 = store.allocate_follow_up_turn("p", id_factory=factory)
    store.set_turn_response("p", idx1, question="q1", is_refusal=False)
    id2, idx2 = store.allocate_follow_up_turn("p", id_factory=factory)
    store.set_turn_response("p", idx2, question="q2", is_refusal=False)
    assert id1 != id2
    assert idx1 + 1 == idx2

    fetched = store.get("p")
    assert fetched is not None
    # Two finalised turns recorded.
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


def test_concurrent_followups_serialised_per_session(tmp_path: Path) -> None:
    """Per-session lock prevents q-number gaps when two follow-ups
    interleave: B can only allocate after A has finalised or discarded.

    Reproduces CR's scenario: previously, A reserved q1, B reserved q2,
    A failed → discard_turn refused to pop a non-tail placeholder and
    the next allocation skipped to q3. With per-session serialisation,
    B blocks until A finishes, so the q-counter is gap-free even under
    concurrent failures.
    """

    import threading

    store = SessionStore()
    store.put(_mk_session("p", tmp_path / "p"))

    def factory(sid: str, idx: int) -> str:
        return f"eval_follow_p_q{idx + 1}"

    # Allocate A (q1).
    id_a, idx_a = store.allocate_follow_up_turn("p", id_factory=factory)
    assert id_a.endswith("_q1")

    # B's allocate must block until A releases. Run it on a thread.
    b_result: dict = {}

    def allocate_b() -> None:
        b_result["id"], b_result["idx"] = store.allocate_follow_up_turn(
            "p", id_factory=factory
        )

    t = threading.Thread(target=allocate_b)
    t.start()
    # Give B time to attempt acquire and block.
    time.sleep(0.05)
    assert not b_result, "B should be blocked on the per-session lock"

    # A fails — discard. After this B unblocks and gets q1 (the slot A
    # vacated), keeping the q-sequence gap-free.
    store.discard_turn("p", idx_a)

    t.join(timeout=1.0)
    assert not t.is_alive()
    assert b_result["id"].endswith("_q1"), b_result
    assert b_result["idx"] == 0


def test_set_turn_response_rejects_double_finalisation(tmp_path: Path) -> None:
    """A regression where the route called set_turn_response twice would
    silently overwrite a real answer; the placeholder check raises instead."""

    store = SessionStore()
    store.put(_mk_session("p", tmp_path / "p"))
    _, turn_index = store.allocate_follow_up_turn(
        "p", id_factory=lambda sid, idx: f"id-{idx}"
    )
    store.set_turn_response("p", turn_index, question="real", is_refusal=False)
    # The placeholder is gone; a second finalisation must raise rather
    # than silently overwriting a completed turn.
    with pytest.raises(RuntimeError, match="already finalised"):
        store.set_turn_response("p", turn_index, question="oops", is_refusal=False)
