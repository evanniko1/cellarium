"""HypothesisStore + the Council-run orchestrator (Phase 1 of the Hypothesis-Generation surface)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

import hypotheses  # noqa: E402


def test_store_roundtrip(tmp_path):
    s = hypotheses.HypothesisStore(path=tmp_path / "t.db")
    rid = s.new_id()
    s.create(rid, "Is aaRS-KO survival biochemical?", "claude-opus-4-8")
    assert s.get(rid)["status"] == "running"

    s.append_round(rid, {"round": 1, "judge": {"falsifiable": False, "discriminating": False}})
    s.append_round(rid, {"round": 2, "judge": {"falsifiable": True, "discriminating": True}})
    s.complete(rid, {"claim": "c", "h1": "h1"}, [{"perturbation": "gene_knockout"}],
               {"converged": True, "rounds_used": 2, "substantive_objections": 5})

    run = s.get(rid)
    assert run["status"] == "done"
    assert len(run["rounds"]) == 2 and run["rounds"][1]["judge"]["falsifiable"] is True
    assert run["hypothesis"]["claim"] == "c"
    assert len(run["designs"]) == 1
    assert run["meta"]["converged"] is True

    summary = s.list()[0]
    assert summary["id"] == rid and summary["n_rounds"] == 2 and summary["n_designs"] == 1 and summary["claim"] == "c"

    s.delete(rid)
    assert s.get(rid) is None


def test_fail_marks_error(tmp_path):
    s = hypotheses.HypothesisStore(path=tmp_path / "t.db")
    rid = s.new_id()
    s.create(rid, "q", None)
    s.fail(rid, "RuntimeError: boom")
    run = s.get(rid)
    assert run["status"] == "error" and "boom" in run["meta"]["error"]


def test_run_council_persists(tmp_path, monkeypatch):
    """The orchestrator runs deliberate (blind), streams+captures rounds, and persists the whole run."""
    import cellarium.council as council

    class _Hyp:
        claim = "aaRS survival is biochemical, not a generation-depth artifact"
        h1 = "argS/gltX decline steeper than alaS"
        candidate_designs = [{"perturbation": "gene_knockout", "condition": "KO:alaS", "params": {}},
                             {"perturbation": "gene_knockout", "condition": "KO:argS", "params": {}}]
        converged = True
        rounds_used = 4
        substantive_objections = 6

        def brief(self):
            return "operationalized brief"

    def _fake_deliberate(question, *, verbose=False, on_round=None, **kw):
        for r in (1, 2):
            on_round({"round": r, "proposer": {"claim": "c"}, "skeptic": [], "judge": {"falsifiable": r == 2}})
        return _Hyp()

    monkeypatch.setattr(council, "deliberate", _fake_deliberate)
    monkeypatch.setattr(council, "sufficiency_gate", lambda q, **kw: {"sufficient": True, "clarifying_questions": []})

    s = hypotheses.HypothesisStore(path=tmp_path / "t.db")
    seen = []
    run = hypotheses.run_council(s, "Is aaRS-KO survival biochemical?", model="claude-opus-4-8",
                                 on_round=lambda rid, p: seen.append(p["round"]))

    assert run["status"] == "done"
    assert run["hypothesis"]["claim"].startswith("aaRS")
    assert len(run["rounds"]) == 2 and len(run["designs"]) == 2
    assert run["meta"]["rounds_used"] == 4 and run["meta"]["substantive_objections"] == 6
    assert seen == [1, 2]                       # rounds streamed to the caller AND persisted
    assert s.get(run["id"])["status"] == "done"


def test_run_council_soft_nudges_broad_question_but_deliberates(tmp_path, monkeypatch):
    """Soft nudge, never block: a broad question is NOT parked — the Council deliberates it (its core competency)
    and only carries a non-blocking sharpening hint in meta. The old blocking gate parked ~23/25 canonical
    questions (see evals/run_ab.py gate diagnostic); midwifing a vague seed IS the Council's whole purpose."""
    import cellarium.council as council

    class _Hyp:
        claim = "operationalized from a broad seed"; h1 = "h1"; candidate_designs = []
        converged = True; rounds_used = 3; substantive_objections = 2

        def brief(self):
            return "b"

    ran = {"n": 0}

    def _fake_deliberate(question, *, verbose=False, on_round=None, **kw):
        ran["n"] += 1
        if on_round:
            on_round({"round": 1, "proposer": {"claim": "c"}, "skeptic": [], "judge": {}})
        return _Hyp()

    monkeypatch.setattr(council, "deliberate", _fake_deliberate)

    s = hypotheses.HypothesisStore(path=tmp_path / "t2.db")
    run = hypotheses.run_council(s, "what happens to the cell?")     # maximally broad
    assert run["status"] == "done"                                   # NEVER needs_spec — the gate no longer blocks
    assert ran["n"] == 1                                             # deliberate DID run on the broad question
    assert run["meta"]["broad_question"] is True                    # flagged broad...
    assert run["meta"]["hint"]                                       # ...with an advisory, non-blocking hint
    assert s.list()                                                  # and it appears in the run list (a real run)


def test_run_council_specific_question_has_no_nudge(tmp_path, monkeypatch):
    """A question that already names a manipulation + observable deliberates with no nudge (broad_question False)."""
    import cellarium.council as council

    class _Hyp:
        claim = "c"; h1 = "h1"; candidate_designs = []
        converged = True; rounds_used = 1; substantive_objections = 0

        def brief(self):
            return "b"

    monkeypatch.setattr(council, "deliberate", lambda q, *, verbose=False, on_round=None, **kw: _Hyp())
    s = hypotheses.HypothesisStore(path=tmp_path / "t3.db")
    run = hypotheses.run_council(s, "Does knocking out pfkA reduce growth rate versus wildtype?")
    assert run["status"] == "done"
    assert run["meta"]["broad_question"] is False and run["meta"]["hint"] is None
