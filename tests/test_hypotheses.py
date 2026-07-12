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


def test_run_council_parks_underspecified_question(tmp_path, monkeypatch):
    """Phase 3(b): a question the sufficiency gate deems too broad is parked as 'needs_spec' with SCOPE-ONLY
    clarifying questions — deliberate is never called on a question too vague to yield a decisive test."""
    import cellarium.council as council

    def _no_deliberate(*a, **k):
        raise AssertionError("deliberate must not run on an underspecified question")

    monkeypatch.setattr(council, "deliberate", _no_deliberate)
    monkeypatch.setattr(council, "sufficiency_gate", lambda q, **kw: {
        "sufficient": False, "missing": ["target"], "clarifying_questions": ["Which gene or perturbation?"]})

    s = hypotheses.HypothesisStore(path=tmp_path / "t2.db")
    run = hypotheses.run_council(s, "what happens to the cell?")
    assert run["status"] == "needs_spec"
    assert run["meta"]["clarifying_questions"] == ["Which gene or perturbation?"]
