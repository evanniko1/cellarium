"""NMI-1 / NMI-2 — the pre-dispatch capability gate, pinned. No network, deliberately.

WHAT THESE DEFEND. The paper's claim is "the language model cannot override a refusal". Before this module
that was false as written: `capability.check` had two call sites and both were inside a tool the model elects
to call, so the registry was consulted when the model remembered to consult it. The property under test is
therefore not "the registry is correct" — other tests cover that — but **that the decision happens on a path
the model cannot skip, and that the model does not make it**.

WHY NO NETWORK. The parser needs a model; the decision does not. Splitting them is the design, and it is what
makes the load-bearing half testable on any runner with no key: every test here supplies the requirement
directly or through a stub parser, so what is exercised is the deterministic lookup and the placement. The
parser's accuracy is an EVALUATION, not a unit test — `scripts/run_gate_eval.py`, scored against labels the
registry generates.

THE REMOVAL TEST IS THE ONE THAT MATTERS. A test that passes with the mechanism deleted is measuring
something else, and this repository has shipped one of those before (`audit()` returning a pass for a check
it never performed). `test_the_gate_is_load_bearing` asserts the opposite outcomes with the gate on and off,
so deleting the call changes the result.
"""

from __future__ import annotations

import pytest

from cellarium import capability as C
from cellarium import gate, orchestrate


def req(observable: str, granularity: str, deps: tuple[str, ...] = (), q: str = "test question"):
    return gate.Requirement(observable=observable, granularity=granularity,
                            regulatory_dependencies=deps, raw_question=q, parser="manual")


# ---------------------------------------------------------------------------------------------------------
# the lookup: representability, separated from data coverage
# ---------------------------------------------------------------------------------------------------------

def test_representability_is_not_data_coverage():
    """The distinction the three-outcome design depends on, pinned at its source.

    `capability.answerable_in` is a conjunction that includes "a run exists in this mode". That is right for
    its own purpose and wrong here: under it, every capability reads as absent in `coarse_kinetic` purely
    because nobody has run that mode, and the gate would tell a user the simulator cannot represent a
    nutrient shift when it represents one in all three modes.
    """
    cap = C._BY_KEY["nutrient_shift_timelines"]
    assert cap.holds_in == C.ELONGATION_MODES, "fixture assumption: this capability holds in every mode"
    assert "coarse_kinetic" not in C.MODES_IN_CORPUS, "fixture assumption: no runs in coarse_kinetic"

    assert C.answerable_in(cap, "coarse_kinetic") is False, "answerable_in folds in corpus coverage"
    assert gate.representable("nutrient_shift_timelines", "coarse_kinetic") is True, \
        "the gate must separate 'the model computes it' from 'someone has run it'"


def test_an_unknown_capability_is_never_treated_as_absent():
    assert gate.representable("no_such_capability", "steady_state") is None
    assert gate.representable("ppgpp_stringent_response", "no_such_mode") is None


@pytest.mark.parametrize("observable,granularity,deps,mode,expected", [
    # representable and runs exist -> answer
    ("trna_charging",      "per_amino_acid",  (),                      "steady_state",   "answer"),
    ("trna_charging",      "per_isoacceptor", (),                      "kinetic",        "answer"),
    ("media_response",     "aggregate",       (),                      "steady_state",   "answer"),
    ("elongation",         "per_codon",       (),                      "kinetic",        "answer"),
    # not representable in this mode -> refuse
    ("trna_charging",      "per_isoacceptor", (),                      "steady_state",   "refuse"),
    ("rrna_transcription", "per_operon",      (),                      "steady_state",   "refuse"),
    ("trna_abundance",     "per_gene",        (),                      "kinetic",        "refuse"),
    ("ppgpp",              "aggregate",       (),                      "kinetic",        "refuse"),
    # representable, but the mode has no runs -> propose, NOT refuse
    ("media_response",     "aggregate",       (),                      "coarse_kinetic", "propose"),
    # two requirements that cannot be satisfied together -> refuse with no route
    ("trna_charging",      "per_isoacceptor", ("stringent_response",), "steady_state",   "refuse"),
    ("trna_charging",      "per_isoacceptor", ("stringent_response",), "kinetic",        "refuse"),
    # nothing declared covers it -> proceed, never refuse
    ("other",              "other",           (),                      "steady_state",   "answer"),
])
def test_the_decision_table(observable, granularity, deps, mode, expected):
    d = gate.decide(req(observable, granularity, deps), mode=mode)
    assert d.verdict == expected, f"{observable}/{granularity} in {mode}: {d.reason}"


def test_granularity_alone_flips_the_verdict():
    """The near-neighbour property: same entity, same intervention, same observable, one field different.

    A gate that refused on keywords would give these two the same answer, because the only textual difference
    is the resolution asked for.
    """
    coarse = gate.decide(req("trna_charging", "per_amino_acid"), mode="steady_state")
    fine = gate.decide(req("trna_charging", "per_isoacceptor"), mode="steady_state")
    assert (coarse.verdict, fine.verdict) == ("answer", "refuse")


def test_a_route_must_satisfy_every_requirement_at_once():
    """The tRNA case. Per-isoacceptor charging holds in `kinetic`; the stringent response holds in
    `steady_state`. Each blocker has a mode that fixes it, and no mode fixes both — so naming either as a
    route would send the user somewhere that cannot answer the question."""
    d = gate.decide(req("trna_charging", "per_isoacceptor", ("stringent_response",)), mode="steady_state")
    assert d.verdict == "refuse"
    assert d.route == "", "a route was offered that does not satisfy the whole requirement"
    assert any("no single elongation model" in n for n in d.notes)


def test_a_refusal_carries_the_mechanism_not_the_phrasing():
    """Over-refusal is a real cost, and a refusal that blamed the question would be it in a new costume."""
    d = gate.decide(req("trna_charging", "per_isoacceptor"), mode="steady_state")
    assert d.verdict == "refuse"
    assert "aa_from_trna" in d.reason or "20-state" in d.reason, \
        "the refusal must name the implementation, which is what makes it source-derived"
    text = gate.render(d)
    assert "vague" not in text.lower() and "unclear" not in text.lower()


def test_decisions_are_reproducible():
    a = gate.decide(req("trna_charging", "per_isoacceptor"), mode="steady_state")
    b = gate.decide(req("trna_charging", "per_isoacceptor"), mode="steady_state")
    assert (a.verdict, a.blocking, a.route) == (b.verdict, b.blocking, b.route)


def test_every_vocabulary_term_is_reachable():
    """A controlled vocabulary with unreachable values lets the parser name a target the lookup cannot
    resolve, which would silently become `other` and read as 'nothing declared covers this'."""
    used_obs = {o for o, _ in gate.REQUIRES}
    used_gran = {g for _, g in gate.REQUIRES}
    assert used_obs <= set(gate.OBSERVABLES) and used_gran <= set(gate.GRANULARITIES)
    unreachable = [o for o in gate.OBSERVABLES if o != "other" and o not in used_obs]
    assert not unreachable, f"observables no mapping can resolve: {unreachable}"
    for keys in gate.REQUIRES.values():
        for k in keys:
            assert k in C._BY_KEY, f"REQUIRES names a capability that is not declared: {k}"
    for keys in gate.DEPENDENCY_REQUIRES.values():
        for k in keys:
            assert k in C._BY_KEY, f"DEPENDENCY_REQUIRES names an undeclared capability: {k}"


# ---------------------------------------------------------------------------------------------------------
# the placement: the gate runs before anything dispatches a tool
# ---------------------------------------------------------------------------------------------------------

def _stub_parser(observable: str, granularity: str, deps: tuple[str, ...] = ()):
    return lambda q: req(observable, granularity, deps, q)


def test_a_refused_question_never_reaches_the_agent(monkeypatch):
    """PRE-dispatch means the tool-running half is not entered at all — not that it runs and is discarded."""
    called = {"agent": False}

    def _boom(*a, **k):
        called["agent"] = True
        raise AssertionError("agent.run was reached despite a refusal; the gate is not pre-dispatch")

    import cellarium.agent as agent_mod
    monkeypatch.setattr(agent_mod, "run", _boom)

    inv = orchestrate.investigate("does leucine tRNA-1 stay charged?", use_council=False, verbose=False,
                                  gate_parser=_stub_parser("trna_charging", "per_isoacceptor"))
    assert called["agent"] is False
    assert inv.gated is True
    assert inv.decision.verdict == "refuse"
    assert "cannot represent" in inv.answer


def test_an_admitted_question_does_reach_the_agent(monkeypatch):
    """The other direction. Without this the gate could be satisfied by refusing everything."""
    seen = {}

    def _fake_run(question, **k):
        seen["question"] = question
        return "grounded answer"

    import cellarium.agent as agent_mod
    monkeypatch.setattr(agent_mod, "run", _fake_run)

    inv = orchestrate.investigate("what fraction of leucine tRNA is charged?", use_council=False, verbose=False,
                                  gate_parser=_stub_parser("trna_charging", "per_amino_acid"))
    assert seen.get("question")
    assert inv.gated is False
    assert inv.answer == "grounded answer"
    assert inv.decision is not None and inv.decision.verdict == "answer", \
        "an admitted question must still carry its decision, or a caller cannot tell a pass from no gate"


def test_the_gate_is_load_bearing(monkeypatch):
    """THE REMOVAL TEST. The same question, gate on and gate off, must come out differently — otherwise the
    gate is decoration and every other test here is measuring the registry rather than the placement."""
    import cellarium.agent as agent_mod
    monkeypatch.setattr(agent_mod, "run", lambda q, **k: "the agent answered anyway")

    parser = _stub_parser("trna_charging", "per_isoacceptor")
    on = orchestrate.investigate("q", use_council=False, verbose=False, gate_parser=parser)
    off = orchestrate.investigate("q", use_council=False, verbose=False, gate_parser=parser, use_gate=False)

    assert on.gated is True and on.answer != "the agent answered anyway"
    assert off.gated is False and off.answer == "the agent answered anyway"


def test_a_broken_parser_proceeds_rather_than_refusing(monkeypatch):
    """Failing closed sounds safe and is not: a parser outage would become a system that refuses everything,
    and a refusal the registry never asked for is indistinguishable to a user from a real one."""
    import cellarium.agent as agent_mod
    monkeypatch.setattr(agent_mod, "run", lambda q, **k: "ran")

    def _broken(_q):
        return gate.Requirement(raw_question=_q, parser="stub (failed: Timeout)")

    inv = orchestrate.investigate("anything", use_council=False, verbose=False, gate_parser=_broken)
    assert inv.gated is False and inv.answer == "ran"
    assert inv.decision.verdict == "answer"
    assert any("not evidence of absence" in n for n in inv.decision.notes)
