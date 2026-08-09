"""A re-convene must not destroy the deliberation it is refining (SP-3a).

`HypothesisStore.create` is `INSERT OR REPLACE`, and `run_council(reuse_id=X)` passes the existing id — so the
one feature whose entire purpose is to REFINE a deliberation overwrote it: `rounds`, `hypothesis`, `designs`
and `meta` all reset to empty. Nothing warned, and the surface looked correct afterwards because the new run
streamed into the same row.

The cost was not hypothetical. M-7's progressive narrowing exercises `reuse_id` twice
(`tests/test_narrowing.py`), and the record of what it narrowed FROM was gone each time; "round 0 beside
round 3", which the backlog asks for, was unanswerable because round 0 no longer existed.

The fix archives instead of replacing. The LIVE run keeps its id — the caller streams rounds to it and the
surface polls it, so moving the live row would break the stream — and the prior state moves to a snapshot id,
with the two rows pointing at each other (`supersedes` / `superseded_by`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from apps.hypotheses import HypothesisStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return HypothesisStore(tmp_path / "t.db")


def _deliberate(store, run_id, question, rounds=("r0",)):
    store.create(run_id, question, "claude-opus-4-8")
    for r in rounds:
        store.append_round(run_id, {"round": r})
    store.complete(run_id, {"claim": question}, [{"perturbation": "wildtype"}], {"n": len(rounds)})


def test_a_reconvene_preserves_the_prior_deliberation(store):
    """THE regression. Before the fix this lost `rounds`, `hypothesis`, `designs` and `meta` outright."""
    _deliberate(store, "h_1", "does argS starve arginine?", rounds=("r0", "r1"))
    before = store.get("h_1")
    assert len(before["rounds"]) == 2 and before["hypothesis"]

    archived = store.archive_prior("h_1")
    assert archived and archived != "h_1", "nothing was archived, so the overwrite below destroys it"
    store.create("h_1", "does argS starve arginine at 10% expression?", "claude-opus-4-8")
    store.link_supersedes("h_1", archived)

    live = store.get("h_1")
    assert live["rounds"] == [] and live["question"].endswith("10% expression?"), "the live run did not restart"
    kept = store.get(archived)
    assert kept is not None, "the prior deliberation is gone — this is the defect"
    assert len(kept["rounds"]) == 2, kept["rounds"]
    assert kept["hypothesis"] == before["hypothesis"] and kept["designs"] == before["designs"]


def test_the_live_run_keeps_its_id(store):
    """Non-negotiable: the caller streams rounds to `reuse_id` and the surface polls it."""
    _deliberate(store, "h_2", "q")
    store.archive_prior("h_2")
    store.create("h_2", "q refined", None)
    assert store.get("h_2")["question"] == "q refined"


def test_snapshots_do_not_clutter_the_run_list(store):
    """History is reachable, not listed — otherwise one refined question reads as several asked repeatedly."""
    _deliberate(store, "h_3", "q")
    archived = store.archive_prior("h_3")
    store.create("h_3", "q refined", None)
    store.link_supersedes("h_3", archived)
    store.complete("h_3", {}, [], {})
    ids = [r["id"] for r in store.list()]
    assert "h_3" in ids and archived not in ids, ids


def test_the_thread_reconstructs_the_chain_oldest_first(store):
    """Two re-convenes. This is the 'round 0 beside round 3' the overwrite made impossible."""
    _deliberate(store, "h_4", "v1", rounds=("a",))
    for n, q in ((2, "v2"), (3, "v3")):
        arch = store.archive_prior("h_4")
        store.create("h_4", q, None)
        store.link_supersedes("h_4", arch)
        store.append_round("h_4", {"round": q})
        store.complete("h_4", {"claim": q}, [], {})
    thread = store.thread("h_4")
    assert [t["question"] for t in thread] == ["v1", "v2", "v3"], [t["question"] for t in thread]
    assert thread[-1]["id"] == "h_4", "the newest run must be the live id"
    assert len({t["id"] for t in thread}) == 3


def test_archiving_a_run_with_nothing_in_it_is_a_no_op(store):
    """An empty snapshot is clutter that looks like history."""
    store.create("h_5", "q", None)
    assert store.archive_prior("h_5") is None
    assert store.archive_prior("h_does_not_exist") is None


def test_run_council_archives_before_it_overwrites(monkeypatch, store):
    """The wiring, not just the primitive: `run_council(reuse_id=...)` must call it."""
    from apps import hypotheses
    _deliberate(store, "h_6", "original question", rounds=("r0",))

    monkeypatch.setattr(hypotheses, "_council_deliberate",
                        getattr(hypotheses, "_council_deliberate", None) or (lambda *a, **k: None),
                        raising=False)

    calls = {}
    real_archive = store.archive_prior
    monkeypatch.setattr(store, "archive_prior",
                        lambda rid: calls.setdefault("archived", real_archive(rid)))
    try:
        hypotheses.run_council(store, "refined question", reuse_id="h_6")
    except Exception:
        pass          # the live Council needs an API key; the archive must happen BEFORE it is reached
    assert calls.get("archived"), "run_council overwrote the row without archiving it first"
    kept = store.get(calls["archived"])
    assert kept and kept["rounds"], "the snapshot exists but is empty"
    assert kept["question"] == "original question"
