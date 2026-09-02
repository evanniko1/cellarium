"""A knowledge-base rebuild is a proposable job, behind the same airlock as a simulation (PARCA-3).

Cellwright could propose a SIMULATION but had no way to propose a REBUILD, so a whole class of question was
unreachable to the agent: "does this hold with the pseudogene reverted?", "is 91.2 min a fitted half-life or
the estimator's floor?". No number of simulations answers those, because every run in the corpus shares ONE
fitted parameter set. Today's estimator-artefact finding needed 25 rebuilds launched by hand.

THE HARD GATE IS DESTINATION, and it is the only one, because the hazard is different in kind from a
simulation's. A rebuild runs no organism design — there is nothing to biosecurity-screen. What it can do,
which no simulation can, is silently invalidate results that already exist: ParCa writes to
`runs/<sim_path>/kb/simData.cPickle` and OVERWRITES it, so a rebuild at an occupied path replaces the fit
that existing rows point at, and a row whose parameters no longer exist cannot be compared against anything.
Nothing in the model warns; the rebuild simply succeeds.

CORRECTION 2026-08-08: this docstring claimed the failure had already happened — "18 analysable rows carry
`5f19d040…` while `cellarium` now holds `3b2f8ebd…`, orphaned". **It had not.** That came from
`_sim_path_of` collapsing four output roots onto one key; each root holds its own kb, and read root-aware
297 of 297 rows agree with their own row. The hazard is real and PROSPECTIVE; the incident was not.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import launch, runner, tools  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_queue(tmp_path, monkeypatch):
    """Never write the real launch queue from a test."""
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "queue.json")


def _docker_or_skip():
    """Guard on the SAME object the runner reads, not on the environment behind it.

    `runner.WCECOLI_DOCKER` is captured at import time (`runner.py:27`). Reading `os.environ` here instead
    made the guard and the guarded thing disagree the moment anything in the suite imported `apps/server.py`,
    which calls `load_dotenv()` — the variable appeared in the environment AFTER `runner` had already frozen
    an empty string, so the guard passed and `read_flat_file` raised. Green alone, red in the full suite,
    for a reason that had nothing to do with either test. A guard that shares no object with what it guards
    is not a guard.
    """
    if not runner.WCECOLI_DOCKER:
        pytest.skip("needs the model image (WCECOLI_DOCKER)")


# ---------------------------------------------------------------------------------------------------------
# The gate.
# ---------------------------------------------------------------------------------------------------------

def test_a_rebuild_over_a_kb_live_rows_depend_on_is_refused():
    """The loss this exists to prevent, asserted against the real corpus."""
    dep = launch.kb_dependents("cellarium")
    if not dep.get("n"):
        pytest.skip("no live rows depend on the kb at 'cellarium' in this checkout")
    res = launch.propose_rebuild("probe", sim_path="cellarium")
    assert res["status"] == "blocked" and res["runnable"] is False, (
        "a rebuild was queued as runnable over a knowledge base %d live rows depend on" % dep["n"])
    # Asserted on CONTENT, not on one word: a refusal has to name what would be destroyed — which kb, and how
    # many rows depend on it — or the operator cannot weigh it. Matching a single word ("orphan") pinned the
    # phrasing instead, and broke when the wording was corrected without the meaning changing.
    refusal = next((n for n in res["vet"]["notes"] if n.startswith("REFUSED")), "")
    assert refusal, "a blocked rebuild produced no REFUSED note: %s" % res["vet"]["notes"]
    assert str(dep["kb_sha256"])[:8] in refusal and str(dep["n"]) in refusal, (
        "the refusal does not say WHAT it would destroy (kb %s, %d dependent rows): %s"
        % (str(dep["kb_sha256"])[:8], dep["n"], refusal))
    assert res["vet"]["would_orphan"]["n"] == dep["n"]


def test_a_fresh_destination_is_allowed_and_named():
    res = launch.propose_rebuild("revert the pseudogene and re-fit")
    assert res["status"] == "pending_approval", res
    assert res["sim_path"] and res["sim_path"] != "cellarium"
    assert launch.kb_dependents(res["sim_path"])["n"] == 0


def test_the_proposal_says_it_mints_an_arm():
    """A rebuild that reads as 'just re-run the fit' is how a corpus fragments without anyone deciding to."""
    res = launch.propose_rebuild("probe")
    assert any("NEW ARM" in n for n in res["vet"]["notes"]), res["vet"]["notes"]


def test_a_rebuild_needs_a_reason():
    assert launch.propose_rebuild("")["status"] == "unresolved"
    assert launch.propose_rebuild("   ")["status"] == "unresolved"


def test_operons_is_validated_and_off_is_flagged_as_uncomparable():
    assert launch.propose_rebuild("probe", operons="maybe")["status"] == "blocked"
    off = launch.propose_rebuild("probe", operons="off")
    assert off["status"] == "pending_approval", "operons='off' is legal, just uncomparable"
    assert any("UNTESTED" in n or "no comparator" in n for n in off["vet"]["notes"])


def test_cellwright_cannot_launch_one():
    """The airlock. `propose_rebuild` is a tool; `approve_and_run` is deliberately not."""
    assert "propose_rebuild" in tools._DISPATCH
    assert "approve_and_run" not in tools._DISPATCH
    assert not any(t["name"] == "approve_and_run" for t in tools.TOOLS)
    res = tools.dispatch("propose_rebuild", {"reason": "probe"})
    assert res["status"] == "pending_approval" and "request_id" in res


# ---------------------------------------------------------------------------------------------------------
# The queue carries two job kinds now.
# ---------------------------------------------------------------------------------------------------------

def test_a_rebuild_request_does_not_break_the_queue_readers():
    """`list_requests` reads `design` unconditionally, and the interface renders it."""
    launch.propose_rebuild("probe", retype_cistrons={"G0-10634_RNA": "pseudo"})
    reqs = launch.list_requests()
    assert len(reqs) == 1
    r = reqs[0]
    assert r["design"]["perturbation"] == "parca_rebuild"
    assert r["seeds"] == 0 and r["generations"] == 0
    assert launch.lifecycle_for_designs([{"perturbation": "wildtype", "condition": "basal"}])[0]["status"] \
        == "proposed", "a rebuild matched a real design in _match_key"


def test_a_pre_parca3_entry_still_routes_to_the_simulation_path(monkeypatch):
    """Entries written before this change carry no `kind`; they must not fall into the rebuild branch."""
    import json
    launch.QUEUE.parent.mkdir(parents=True, exist_ok=True)
    launch.QUEUE.write_text(json.dumps([{
        "id": "req_legacy", "status": "pending_approval",
        "design": {"perturbation": "wildtype", "condition": "basal", "timeline": None, "params": {},
                   "elongation_model": "steady_state"},
        "seeds": 1, "generations": 1, "vet": {"runnable": True}, "ts": 0}]), encoding="utf-8")
    seen: dict = {}

    def fake_campaign(designs, seeds, generations, parallel):
        seen["designs"] = designs
        return "shard.parquet"
    from src.cellarium import manifest
    monkeypatch.setattr(manifest, "campaign", fake_campaign)
    monkeypatch.setattr(manifest, "compact", lambda: {"shard": "shard.parquet"})
    # The fake campaign returns a path that does not exist, which approve_and_run now reads as "no rows
    # landed" and reports as failed. That check is right; it is just not what this test is about, which
    # is that a legacy entry routes to the simulation path rather than the rebuild path.
    monkeypatch.setattr(manifest, "shard_row_count", lambda s: 1)
    monkeypatch.setattr(runner, "parca_rebuild",
                        lambda *a, **k: pytest.fail("a legacy entry was run as a rebuild"))
    out = launch.approve_and_run("req_legacy")
    assert out["status"] == "done" and seen.get("designs"), out


def test_approving_a_rebuild_runs_parca_and_not_a_campaign(monkeypatch):
    res = launch.propose_rebuild("probe", retype_cistrons={"G0-10634_RNA": "pseudo"})
    called: dict = {}

    def fake_rebuild(sim_path, retypes=None, operons="on", cpus=None):
        called.update(sim_path=sim_path, retypes=retypes, operons=operons)
        return {"sim_path": sim_path, "kb_sha256": "deadbeef" * 8, "retyped": [{"id": "G0-10634_RNA"}]}
    from src.cellarium import manifest
    monkeypatch.setattr(runner, "parca_rebuild", fake_rebuild)
    monkeypatch.setattr(manifest, "campaign",
                        lambda *a, **k: pytest.fail("a rebuild was run as a simulation campaign"))
    out = launch.approve_and_run(res["request_id"])
    assert out["status"] == "done", out
    assert called["sim_path"] == res["sim_path"]
    assert called["retypes"] == {"G0-10634_RNA": "pseudo"}, "the approved edit did not reach ParCa"
    assert "NEW ARM" in (out.get("note") or "")


def test_the_gate_is_rechecked_at_approval_not_trusted_from_proposal(monkeypatch):
    """A request can sit pending for hours; the destination can stop being empty in that window.

    What a human approved was "build somewhere harmless". If another rebuild lands at that path first, the
    approval no longer describes what would happen — and the damage is unrecoverable, unlike the cheap check.
    """
    res = launch.propose_rebuild("probe")
    assert res["status"] == "pending_approval"
    monkeypatch.setattr(launch, "kb_dependents",
                        lambda sp: {"sim_path": sp, "kb_sha256": "f" * 64, "n": 7, "designs": []})
    monkeypatch.setattr(runner, "parca_rebuild",
                        lambda *a, **k: pytest.fail("ParCa ran at a destination that had stopped being safe"))
    out = launch.approve_and_run(res["request_id"])
    assert out["status"] == "failed"
    assert "stopped being safe" in (out.get("error") or "")


def test_a_blocked_rebuild_cannot_be_approved():
    res = launch.propose_rebuild("probe", sim_path="cellarium")
    if res["status"] != "blocked":
        pytest.skip("nothing depends on the kb at 'cellarium' here")
    out = launch.approve_and_run(res["request_id"])
    assert "error" in out and "BLOCKED" in out["error"].upper()


# ---------------------------------------------------------------------------------------------------------
# The edit itself.
# ---------------------------------------------------------------------------------------------------------

def test_a_retype_changes_exactly_one_row_and_deletes_nothing():
    """Deleting the row breaks referential integrity — genes.tsv still points at the RNA and the build dies in
    getter_functions.py with a KeyError before any fitting happens. Retyping is also what phnE1 itself did."""
    _docker_or_skip()
    body = runner.read_flat_file("rnas.tsv")
    new, changed = runner.retype_rnas(body, {"G0-10634_RNA": "pseudo"})
    assert changed == [{"id": "G0-10634_RNA", "from": "mRNA", "to": "pseudo"}]
    a, b = body.splitlines(), new.splitlines()
    assert len(a) == len(b), "a retype changed the row COUNT — that is a delete, not a retype"
    assert sum(1 for x, y in zip(a, b) if x != y) == 1


def test_an_unmatched_cistron_raises_rather_than_rebuilding_the_same_kb():
    """Silently skipping would spend 7 minutes and 114 MB producing a knowledge base identical to the one on
    disk, which the caller would then compare against as though it were the perturbation."""
    _docker_or_skip()
    body = runner.read_flat_file("rnas.tsv")
    with pytest.raises(ValueError, match="no row in rnas.tsv"):
        runner.retype_rnas(body, {"NOT_A_REAL_RNA": "pseudo"})
    with pytest.raises(ValueError, match="unknown RNA type"):
        runner.retype_rnas(body, {"G0-10634_RNA": "banana"})


def test_the_airlock_renders_a_rebuild_refusal_with_its_reason():
    """`ui.vet_summary` is what the human reads before approving. It was written for the simulation vet shape.

    Read literally against a rebuild it reports `safety: "clear"` for a REFUSED job and asserts an envelope
    judgement nobody made — so the operator sees a refusal with no reason. A gate that renders but says the
    wrong thing is worse than one that renders nothing.
    """
    from src.cellarium import ui
    blocked = launch.propose_rebuild("probe", sim_path="cellarium")
    if blocked["status"] != "blocked":
        pytest.skip("nothing depends on the kb at 'cellarium' here")
    g = ui.vet_summary(blocked["vet"])
    assert g["runnable"] is False
    assert "clear" not in g["safety"].lower(), "a refused rebuild rendered as safety-clear"
    assert "orphan" in g["why"] or "REFUSED" in g["why"], "the refusal reached the operator with no reason"

    ok = ui.vet_summary(launch.propose_rebuild("probe")["vet"])
    assert ok["runnable"] is True
    assert "NEW ARM" in ok["provenance"], "the airlock does not tell the approver this mints an arm"


def test_the_simulation_vet_still_renders_unchanged():
    """The branch above must not capture an ordinary design."""
    from src.cellarium import ui
    g = ui.vet_summary(launch.propose("wildtype", "basal")["vet"])
    assert g["safety"] in ("clear", "FLAGGED — human review required")
    assert "envelope" in g["feasibility"] or "boundary" in g["feasibility"]


def test_reconcile_asks_the_kb_not_the_manifest_for_a_rebuild(monkeypatch):
    """A rebuild writes no manifest rows, so `count_runs` returns 0 and would heal a COMPLETED rebuild to
    'failed' — reporting failure for work that succeeded and prompting a needless seven-minute re-run."""
    import json

    from src.cellarium import manifest
    res = launch.propose_rebuild("probe")
    q = json.loads(launch.QUEUE.read_text(encoding="utf-8"))
    q[0]["status"] = "running"
    launch.QUEUE.write_text(json.dumps(q), encoding="utf-8")

    monkeypatch.setattr(manifest, "_kb_prov", lambda sp: {"kb_sha256": "c0ffee" * 10})
    launch.reconcile()
    assert launch.list_requests()[0]["status"] == "done", "a completed rebuild was healed to failed"

    q = json.loads(launch.QUEUE.read_text(encoding="utf-8"))
    q[0]["status"] = "running"
    launch.QUEUE.write_text(json.dumps(q), encoding="utf-8")
    monkeypatch.setattr(manifest, "_kb_prov", lambda sp: {})
    launch.reconcile()
    assert launch.list_requests()[0]["status"] == "failed", "a rebuild that produced no kb was healed to done"
    assert res["status"] == "pending_approval"


def test_the_gate_protects_ROWS_not_paths(monkeypatch):
    """A kb on disk that nothing depends on is not protected; one a row points at is.

    This is the semantics worth pinning, because the looser reading ("never build where a kb exists") would
    forbid iterating on a fresh refit, and the tighter one ("only the corpus path is special") would let the
    second rebuild at a scratch path destroy the first one's results the moment runs landed against it. The
    gate asks the ROWS, so a destination becomes protected exactly when something starts depending on it.
    """
    from src.cellarium import manifest, survey
    monkeypatch.setattr(manifest, "_kb_prov", lambda sp: {"kb_sha256": "abc" * 21 + "d"})

    monkeypatch.setattr(survey, "analysis_rows", lambda arm=None: ([], []))
    assert launch.propose_rebuild("probe", sim_path="scratch")["status"] == "pending_approval", (
        "a kb nobody depends on was treated as protected — this forbids iterating on a refit")

    monkeypatch.setattr(survey, "analysis_rows",
                        lambda arm=None: ([{"kb_sha256": "abc" * 21 + "d", "perturbation": "wildtype",
                                            "label": "wildtype·basal·s0"}], []))
    blocked = launch.propose_rebuild("probe", sim_path="scratch")
    assert blocked["status"] == "blocked", (
        "a rebuild was allowed over a kb a live row depends on, just because the path was not 'cellarium'")
    assert blocked["vet"]["would_orphan"]["n"] == 1


@pytest.mark.parametrize("bad", ["../../etc/evil", "a/../../b", "./cellarium", "cellarium/.",
                                 "a/../cellarium", "refit1;rm -rf /", "with space", "-leading"])
def test_a_destination_must_be_a_plain_name(bad):
    """`sim_path` is AGENT-SUPPLIED and becomes a directory inside the model's output tree.

    Two failures, and the second is the easy one to miss. `../../etc/evil` resolves to `out/../../etc/evil`
    and writes 114 MB outside the tree. And a path that ALIASES a protected one — `./cellarium`,
    `cellarium/.`, `a/../cellarium` — reads as a fresh destination to a string-compared dependency check while
    ParCa overwrites the knowledge base 188 rows depend on. A strict charset closes both without having to
    reason about path normalisation on two operating systems.
    """
    res = launch.propose_rebuild("probe", sim_path=bad)
    assert res["status"] == "blocked", "%r was accepted as a rebuild destination" % bad
    assert any("plain name" in n for n in res["vet"]["notes"]), res["vet"]["notes"]


def test_a_plain_name_is_still_accepted():
    for good in ("refit1", "ok-name_2.b", "A1"):
        assert launch.propose_rebuild("probe", sim_path=good)["status"] == "pending_approval", good
