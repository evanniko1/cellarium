"""L-1: before a run is proposed, can any run of that kind resolve what separates the hypotheses?

Not identifiability, which a stochastic model with thousands of parameters does not admit: a reachability check over
elongation models, read from the registry the gate reads. The forced faults are the project's own cases: isoacceptor
charging is exhausted in the default model and resolvable in the kinetic one; isoacceptor charging under starvation
needs two mechanisms no single model holds together; an operon-specific rRNA question is resolvable nowhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import reach  # noqa: E402


def test_isoacceptor_charging_is_exhausted_in_the_default_model_and_resolvable_in_the_kinetic_one():
    r = reach.reach("trna_charging", "per_isoacceptor", mode="steady_state")
    assert r["verdict"] == "exhausted" and r["modes_that_resolve"] == ["kinetic"]
    assert "kinetic" in r["what_would"] and r["why"] and r["why"][0]
    assert reach.reach("trna_charging", "per_isoacceptor", mode="kinetic")["verdict"] == "resolvable"


def test_two_mechanisms_no_single_model_holds_together_are_exhausted_everywhere():
    for mode in ("steady_state", "kinetic", "coarse_kinetic"):
        r = reach.reach("trna_charging", "per_isoacceptor", ["amino_acid_starvation"], mode=mode)
        assert r["verdict"] == "exhausted" and r["modes_that_resolve"] == [], mode
    assert "no elongation model" in r["what_would"]


def test_an_operon_specific_question_is_resolvable_nowhere():
    r = reach.reach("rrna_transcription", "per_operon", mode="kinetic")
    assert r["verdict"] == "exhausted" and r["modes_that_resolve"] == []


def test_an_aggregate_quantity_is_resolvable_in_the_default_model():
    assert reach.reach("trna_charging", "per_amino_acid", mode="steady_state")["verdict"] == "resolvable"


def test_a_quantity_no_record_covers_is_undeclared_not_resolvable():
    r = reach.reach("other", "other")
    assert r["verdict"] == "undeclared" and "not evidence" in r["why"]


def test_a_proposal_says_whether_its_run_can_resolve_what_it_is_for(monkeypatch):
    from cellarium import tools
    seen = {}

    def fake_propose(**kw):
        seen.update(kw)
        return {"status": "queued"}
    out = tools.with_reach(fake_propose)(perturbation="wildtype", condition="basal",
                                         observable="trna_charging", granularity="per_isoacceptor")
    assert out["reach"]["verdict"] == "exhausted" and out["reach"]["modes_that_resolve"] == ["kinetic"]
    assert "observable" not in seen and "granularity" not in seen   # the proposer itself is unchanged
    plain = tools.with_reach(fake_propose)(perturbation="wildtype", condition="basal")
    assert "reach" not in plain
