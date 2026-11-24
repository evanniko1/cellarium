"""P-1: an answer cannot be wider than its admission.

The gate admits a question with a Decision: the capabilities it requires, in one elongation model. Afterwards the agent
calls tools, and a tool can read more than was admitted: a question admitted at per-amino-acid resolution can be
answered from a per-isoacceptor read the model does not represent in that mode. Each tool result is checked against the
admission, using the same declaration of what a tool reads that the raw-tool gate uses (P-2), and a result that reads
a capability the admission does not cover carries a note naming it. Outside an admission nothing changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import effect, gate  # noqa: E402


def _decision(observable="trna_charging", granularity="per_amino_acid", mode="steady_state"):
    req = gate.Requirement(observable=observable, granularity=granularity)
    return gate.Decision(verdict="answer", mode=mode, requirement=req,
                         required_capabilities=gate.required_capabilities(req))


def test_a_read_inside_the_admission_is_untouched():
    with effect.admitted(_decision()):
        out = effect.verify("trna_families", {"design": "wildtype/basal"}, {"value": 1})
    assert out == {"value": 1}


def test_a_read_wider_than_the_admission_is_named():
    with effect.admitted(_decision()):
        out = effect.verify("selective_charging", {"design": "wildtype/basal"}, {"value": 1})
    w = out["wider_than_admitted"]
    assert w["not_admitted"] == ["per_isoacceptor_trna_charging"]
    assert w["admitted"] == ["per_amino_acid_trna_charging"] and w["elongation_model"] == "steady_state"
    assert w["represented_here"] == {"per_isoacceptor_trna_charging": False}


def test_a_read_in_another_mode_than_the_admission_is_named():
    # ppGpp admitted under steady_state; the tool reads a kinetic design, where it is not represented
    with effect.admitted(_decision(observable="ppgpp", granularity="aggregate")):
        out = effect.verify("trajectory", {"design": "wildtype/basal#elong:kinetic", "channel": "ppgpp_conc"},
                            {"value": 1})
    w = out["wider_than_admitted"]
    assert w["modes_read"] == ["kinetic"] and w["represented_here"] == {"ppgpp_stringent_response": False}


def test_outside_an_admission_nothing_changes():
    assert effect.verify("selective_charging", {"design": "wildtype/basal"}, {"value": 1}) == {"value": 1}


def test_an_error_and_a_tool_that_reads_nothing_simulated_are_left_alone():
    with effect.admitted(_decision()):
        assert effect.verify("selective_charging", {}, {"error": "x"}) == {"error": "x"}
        assert effect.verify("comparable_designs", {"design": "condition/minus_phosphate"}, {"v": 1}) == {"v": 1}


def test_the_admission_ends_with_its_block_and_does_not_leak_between_threads():
    import threading
    seen = {}
    with effect.admitted(_decision()):
        t = threading.Thread(target=lambda: seen.update(a=effect.current()))
        t.start()
        t.join()
    assert seen["a"] is None and effect.current() is None


# ---- the wiring ------------------------------------------------------------------------------------------------

def test_dispatch_marks_a_wider_read_made_inside_an_admission(monkeypatch):
    from cellarium import tools
    monkeypatch.setitem(tools._DISPATCH, "selective_charging", lambda design=None, reference=None: {"value": 1})
    monkeypatch.setattr(tools, "_validate_args", lambda n, a: None)
    with effect.admitted(_decision()):
        out = tools.dispatch("selective_charging", {"design": "wildtype/basal"})
    assert out["wider_than_admitted"]["not_admitted"] == ["per_isoacceptor_trna_charging"]
    assert "wider_than_admitted" not in tools.dispatch("selective_charging", {"design": "wildtype/basal"})


def test_an_admitted_investigation_runs_its_tools_inside_the_admission(monkeypatch):
    from cellarium import agent, orchestrate
    seen = {}

    def fake_run(*a, **k):
        seen["admission"] = effect.current()
        return "an answer"
    monkeypatch.setattr(orchestrate, "gate_question", lambda q, **k: _decision())
    monkeypatch.setattr(agent, "run", fake_run)
    orchestrate.investigate("q", use_council=False, verbose=False)
    assert seen["admission"] is not None and seen["admission"].required_capabilities == (
        "per_amino_acid_trna_charging",)
    assert effect.current() is None


def test_the_web_app_runs_its_admitted_turn_inside_the_admission():
    # the server's turn is a closure over a streaming response; read from its source, as the gate-coverage test does
    src = (REPO / "apps" / "server.py").read_text(encoding="utf-8")
    i = src.index("decision = orchestrate.gate_question(question)")
    tail = src[i:i + 4000]
    assert "with effect.admitted(decision):" in tail and tail.index("with effect.admitted(decision):") < tail.index(
        "agent.converse(")
