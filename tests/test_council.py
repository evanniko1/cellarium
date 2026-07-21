"""Socratic Council tests — offline and deterministic, via a scripted fake Anthropic client.

Mirrors tests/test_guardrails.py in spirit: exercise the differentiators (the quarantine boundary, the
A-and-B-and-quota termination gate, the D3 escalation, the round-cap fallback, the structural/feasibility
floors) without any network call. Run: `python -m pytest tests/test_council.py`.
"""

from __future__ import annotations

import sys

from cellarium import council, instrument
from cellarium.hypothesis import Hypothesis

# --- scripted fake client ----------------------------------------------------------------------------------

class _Block:
    def __init__(self, data):
        self.type = "tool_use"
        self.input = data


class _Resp:
    def __init__(self, data):
        self.content = [_Block(data)]


class FakeMessages:
    def __init__(self, scripts):
        self.scripts = scripts           # {tool_name: [dict, dict, ...]} popped FIFO
        self.calls = []                  # (tool_name) log
        self.temps = []                  # the `temperature` each call received (None => omitted) — DD-MTH-2 check

    def create(self, **kwargs):
        name = kwargs["tool_choice"]["name"]
        self.calls.append(name)
        self.temps.append(kwargs.get("temperature", "OMITTED"))
        queue = self.scripts.get(name)
        assert queue, f"no scripted response left for tool {name!r} (call #{len(self.calls)})"
        return _Resp(queue.pop(0))


class FakeClient:
    def __init__(self, scripts):
        self.messages = FakeMessages(scripts)


# --- fixtures: well-formed structured outputs --------------------------------------------------------------

def _candidate(**over):
    c = {
        "claim": "Isogenic cells vary in a metabolic enzyme's abundance beyond replicate noise.",
        "h1": "CV of the enzyme across seeds > technical baseline.",
        "h0": "CV across seeds == technical baseline.",
        "operational_defs": [{"construct": "behave differently", "observable": "protein_mass",
                              "measure": "coefficient of variation across seeds"}],
        "predicted_effect": "positive; CV markedly above baseline",
        "falsifier": {"target": "wildtype/basal", "reference": "wildtype/basal", "channel": "protein_mass",
                      "decision_rule": "reject H0 if welch_t >= 2", "refuting_result": "welch_t < 2"},
        "rivals": [{"claim": "pure measurement noise", "distinguishing_result": "CV == baseline"},
                   {"claim": "extrinsic global state", "distinguishing_result": "variance tracks cell mass"}],
        "auxiliary_assumptions": ["same medium", "same initial conditions"],
        "candidate_designs": [{"perturbation": "wildtype", "condition": "basal", "seeds": 8}],
    }
    c.update(over)
    return c


def _obj(t="undefined_term", sev="substantive", **over):
    o = {"type": t, "issue": f"{t} concern", "severity": sev}
    o.update(over)
    return o


def _verdict(**over):
    v = {"falsifiable": True, "specified": True, "operationalized": True, "discriminating": True,
         "new_substantive_objection_this_round": False, "open_objections_resolved": True}
    v.update(over)
    return v


# --- quarantine (D2/D4) ------------------------------------------------------------------------------------

def test_instrument_exposes_no_readings():
    labels = instrument.dial_labels()
    # capabilities present, no corpus values
    assert set(labels["channels"]) and "reference_design" in labels
    import json
    blob = json.dumps(labels)
    # a reading would show up as a numeric mean/z; the label view carries only metadata strings + units
    assert "welch_t" not in labels  # falsification mechanism is described, not executed
    assert "z" not in labels
    assert "note" in labels["falsification"]
    assert blob  # serialisable


def test_instrument_imports_no_result_bearing_modules():
    # importing the adapter must not pull in survey/differential/scope/store (the answer-key surfaces)
    for m in ("cellarium.survey", "cellarium.differential", "cellarium.scope", "cellarium.store"):
        sys.modules.pop(m, None)
    import importlib
    importlib.reload(instrument)
    leaked = [m for m in ("cellarium.survey", "cellarium.differential", "cellarium.scope", "cellarium.store")
              if m in sys.modules]
    assert leaked == [], f"instrument leaked result-bearing imports: {leaked}"


def test_instrument_channel_names_stay_in_sync_with_survey():
    from cellarium import survey  # test-only import; runtime instrument must NOT import survey
    assert set(instrument.channel_names()) == set(survey.CHANNELS), \
        "instrument.CHANNELS drifted from survey.CHANNELS"


def test_check_design_uses_guardrail_capabilities():
    assert instrument.check_design({"perturbation": "wildtype", "condition": "basal"})["usable"]
    assert not instrument.check_design(
        {"perturbation": "timeline", "timeline": "0 minimal, 1200 minimal_acetate"})["usable"]  # carbon switch
    assert not instrument.check_design(
        {"perturbation": "tf_activity", "params": {"target_genes": ["stxA"]}})["usable"]  # virulence block


# --- clean convergence (A and B and quota) -----------------------------------------------------------------

def test_clean_convergence_returns_falsifiable_hypothesis():
    scripts = {
        "propose_hypothesis": [_candidate(), _candidate(), _candidate()],
        "raise_objections": [
            {"objections": [_obj("undefined_term"), _obj("hidden_auxiliary")]},   # round 1: 2 substantive
            {"objections": [_obj("rival_not_excluded")]},                          # round 2: 1 substantive
            {"objections": []},                                                    # round 3: none
        ],
        "rule": [
            _verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
            _verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
            _verdict(),                                                            # round 3: converged
        ],
    }
    client = FakeClient(scripts)
    h = council.deliberate("Do genetically identical cells behave differently?",
                           max_rounds=4, quota=3, client=client, models={"proposer": "m", "skeptic": "m", "judge": "m"},
                           verbose=False)
    assert isinstance(h, Hypothesis)
    assert h.converged is True
    assert h.residual_ambiguities == []
    assert h.falsifier and h.falsifier.channel == "protein_mass"
    assert len(h.rivals) >= 2
    assert h.candidate_designs and h.candidate_designs[0].perturbation == "wildtype"


def test_council_temperature_is_warm_and_reasoning_aware(monkeypatch):
    """DD-MTH-2: the Council pins its OWN warm temperature (not Cellwright's 0.0), and omits it on a reasoning model
    (the API forces temperature=1 there)."""
    assert council._council_temperature("claude-sonnet-5") == council.COUNCIL_TEMPERATURE
    assert council.COUNCIL_TEMPERATURE > 0.0                       # warm — exploration is the Council's function
    assert council._council_temperature("claude-opus-4-8") is None  # reasoning model -> omit (API forces 1)
    assert council._council_temperature("claude-sonnet-5", thinking=True) is None
    monkeypatch.setattr(council, "COUNCIL_TEMPERATURE", 0.3)       # it's a recorded knob (the sweep tunes it)
    assert council._council_temperature("claude-sonnet-5") == 0.3


def test_deliberate_pins_council_temperature_by_construction():
    """DD-MTH-2: a deliberate() the caller didn't hand a temperature (the eval A/B path) still pins the warm value on
    every role call — reproducibility no longer depends on the caller remembering."""
    scripts = {
        "propose_hypothesis": [_candidate()],
        "raise_objections": [{"objections": []}],
        "rule": [_verdict()],
    }
    client = FakeClient(scripts)
    council.deliberate("q", max_rounds=1, quota=3, client=client,
                       models={"proposer": "claude-sonnet-5", "skeptic": "claude-sonnet-5", "judge": "claude-sonnet-5"},
                       verbose=False)
    sent = [t for t in client.messages.temps if t != "OMITTED"]
    assert sent and all(t == council.COUNCIL_TEMPERATURE for t in sent)   # every role call carried the warm pin

    # an explicit temperature still wins (the sweep eval passes its own point)
    client2 = FakeClient({"propose_hypothesis": [_candidate()], "raise_objections": [{"objections": []}],
                          "rule": [_verdict()]})
    council.deliberate("q", max_rounds=1, quota=3, client=client2, temperature=0.2,
                       models={"proposer": "claude-sonnet-5", "skeptic": "claude-sonnet-5", "judge": "claude-sonnet-5"},
                       verbose=False)
    assert all(t == 0.2 for t in client2.messages.temps if t != "OMITTED")


# --- D3 escalation on irreducible construct ambiguity ------------------------------------------------------

def test_irreducible_ambiguity_asks_the_user_once():
    asked = []

    def ask(q):
        asked.append(q)
        return "growth_rate"

    scripts = {
        "propose_hypothesis": [_candidate(), _candidate(), _candidate(), _candidate()],
        "raise_objections": [
            {"objections": [_obj("construct_ambiguity", irreducible=True,
                                 user_question="Which observable — growth rate, protein abundance, or morphology?")]},
            {"objections": [_obj("hidden_auxiliary"), _obj("undefined_term")]},
            {"objections": [_obj("rival_not_excluded")]},
            {"objections": []},
        ],
        "rule": [  # judge only called on non-escalation rounds (2,3,4)
            _verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
            _verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
            _verdict(),
        ],
    }
    client = FakeClient(scripts)
    h = council.deliberate("Do identical cells behave differently?", max_rounds=5, quota=3, ask_user=ask,
                           client=client, models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    assert asked == ["Which observable — growth rate, protein abundance, or morphology?"]
    assert h.converged is True
    assert h.residual_ambiguities == []


def test_ambiguity_without_ask_user_is_parked_as_residual():
    scripts = {
        "propose_hypothesis": [_candidate() for _ in range(3)],
        "raise_objections": [
            {"objections": [_obj("construct_ambiguity", irreducible=True, user_question="which observable?")]},
            {"objections": [_obj("construct_ambiguity", irreducible=True, user_question="which observable?")]},
            {"objections": [_obj("construct_ambiguity", irreducible=True, user_question="which observable?")]},
        ],
        "rule": [_verdict(), _verdict(), _verdict()],
    }
    client = FakeClient(scripts)
    h = council.deliberate("vague?", max_rounds=3, quota=1, ask_user=None, client=client,
                           models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    assert h.converged is False
    assert any("construct_ambiguity" in r for r in h.residual_ambiguities)


# --- round-cap fallback ------------------------------------------------------------------------------------

def test_round_cap_returns_best_effort_with_residuals():
    scripts = {
        "propose_hypothesis": [_candidate() for _ in range(3)],
        "raise_objections": [{"objections": [_obj("rival_not_excluded")]} for _ in range(3)],
        "rule": [_verdict(new_substantive_objection_this_round=True, open_objections_resolved=False)
                 for _ in range(3)],
    }
    client = FakeClient(scripts)
    h = council.deliberate("q", max_rounds=3, quota=3, client=client,
                           models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    assert h.converged is False
    assert h.residual_ambiguities  # non-empty


# --- structural + feasibility floors (judge cannot wave these through) --------------------------------------

def test_missing_falsifier_blocks_convergence():
    cand = _candidate()
    cand.pop("falsifier")
    scripts = {
        "propose_hypothesis": [cand for _ in range(2)],
        "raise_objections": [{"objections": []} for _ in range(2)],
        "rule": [_verdict(), _verdict()],   # judge says everything's fine...
    }
    client = FakeClient(scripts)
    h = council.deliberate("q", max_rounds=2, quota=0, client=client,
                           models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    assert h.converged is False           # ...but the structural floor blocks it (no falsifier)
    assert h.falsifier is None


def test_infeasible_design_blocks_convergence():
    # only design is a mid-run carbon-source switch -> out of envelope -> feasible_code False
    cand = _candidate(candidate_designs=[{"perturbation": "timeline",
                                          "timeline": "0 minimal, 1200 minimal_acetate"}])
    scripts = {
        "propose_hypothesis": [cand for _ in range(2)],
        "raise_objections": [{"objections": []} for _ in range(2)],
        "rule": [_verdict(), _verdict()],
    }
    client = FakeClient(scripts)
    h = council.deliberate("q", max_rounds=2, quota=0, client=client,
                           models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    assert h.converged is False


def test_unfalsifiable_verdict_blocks_convergence():
    scripts = {
        "propose_hypothesis": [_candidate() for _ in range(2)],
        "raise_objections": [{"objections": []} for _ in range(2)],
        "rule": [_verdict(falsifiable=False), _verdict(falsifiable=False)],
    }
    client = FakeClient(scripts)
    h = council.deliberate("q", max_rounds=2, quota=0, client=client,
                           models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    assert h.converged is False


def test_substantive_objection_blocks_same_round_convergence():
    """Convergence guard: even if the JUDGE waves a round through (its flags say converged), a SUBSTANTIVE
    objection the skeptic raised THAT round must block convergence — the proposer has to earn a genuinely clean
    round. This is the aaRS-KO failure: the judge let a skeptic-flagged backwards slope-sign converge in-round."""
    scripts = {
        "propose_hypothesis": [_candidate(), _candidate()],
        "raise_objections": [
            {"objections": [_obj("undefined_term")]},   # round 1: skeptic flags a SUBSTANTIVE objection
            {"objections": []},                          # round 2: clean — skeptic silent
        ],
        # the judge (wrongly) reports 'converged' in BOTH rounds; the guard must still refuse round 1
        "rule": [_verdict(), _verdict()],
    }
    h = council.deliberate("q", max_rounds=2, quota=0, client=FakeClient(scripts),
                           models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    assert h.converged is True and h.rounds_used == 2   # NOT round 1 — the substantive objection forced a clean round


def test_web_brief_extracts_text_and_dedupes_citations():
    """The librarian returns the synthesized brief + its web sources, pulled from the text blocks' citations and
    de-duplicated by URL."""
    class _Cit:
        def __init__(self, url, title): self.url, self.title = url, title

    class _B:
        type = "text"
        text = "aaRS KOs deplete charged tRNA and crash by ~gen 3 [1][2]."
        citations = [_Cit("https://example.org/paper", "Choi & Covert 2023"),
                     _Cit("https://example.org/paper", "Choi & Covert 2023")]   # dup URL

    class _R:
        content = [_B()]

    out = council._read_web_brief(_R())
    assert out["brief"].startswith("aaRS KOs deplete")
    assert out["sources"] == [{"url": "https://example.org/paper", "title": "Choi & Covert 2023"}]   # deduped


def test_sufficiency_gate_challenges_vague_question_scope_only():
    """Phase 3(b): a too-broad question is parked with SCOPE-ONLY clarifying questions; a specified one passes
    straight through. The gate never runs the deliberation on a question too vague to yield a decisive test."""
    vague = council.sufficiency_gate("what happens to the cell?", client=FakeClient(
        {"gate": [{"sufficient": False, "missing": ["target", "observable"],
                   "clarifying_questions": ["Which gene or perturbation should we knock out?",
                                            "Which observable channel should we measure?"]}]}),
        models={"proposer": "m", "skeptic": "m", "judge": "m"})
    assert vague["sufficient"] is False and len(vague["clarifying_questions"]) == 2

    ok = council.sufficiency_gate("Is a pfkA knockout viable versus wildtype, by division_rate?",
        client=FakeClient({"gate": [{"sufficient": True}]}),
        models={"proposer": "m", "skeptic": "m", "judge": "m"})
    assert ok["sufficient"] is True and ok["clarifying_questions"] == []


def test_sufficiency_prepass_never_parks_a_specified_question():
    """The over-firing fix. A question naming a runnable MANIPULATION + a measurable OBSERVABLE is sufficient by
    construction, so the gate short-circuits WITHOUT the model — the LLM (which fires unpredictably) is never even
    consulted. A client whose .create() explodes proves it: if any of these reached the model, the test would error.
    This is the battery the gate historically over-parked (lpxC, glycolysis, rRNA)."""
    class _Boom:
        class messages:
            @staticmethod
            def create(**k):
                raise AssertionError("a specified question must be short-circuited, never sent to the model")

    specified = [
        "Is the lpxC knockout's simulated viability consistent with essentiality, vs wildtype?",  # historically PARKED
        "Do glycolysis knockouts reroute flux or cost growth?",                                    # historically PARKED
        "Does reducing rRNA operon dosage cap max growth?",                                        # historically PARKED
        "Does knocking out pfkA reduce growth rate versus wildtype?",
        "Does argS knockout raise or lower ppGpp?",
        "Does clamping ppGpp to 2x reduce growth?",
    ]
    for q in specified:
        out = council.sufficiency_gate(q, client=_Boom(), labels={})
        assert out["sufficient"] is True and out["clarifying_questions"] == [], q


def test_sufficiency_prepass_lets_genuinely_open_questions_reach_the_gate():
    """The pre-pass short-circuits ONLY specified questions; a genuinely open one (no manipulation or no observable)
    still falls through to the LLM gate, which is the only path that can park. This bounds the firing set."""
    assert council.looks_specific("does a pfkA knockout stop division?") is True
    assert council.looks_specific("clamp ppGpp and watch growth") is True
    # open — no manipulation named -> reaches the model
    assert council.looks_specific("what happens to the cell?") is False
    assert council.looks_specific("tell me about metabolism") is False
    assert council.looks_specific("is the model any good?") is False


def test_objection_resolution_is_tracked_per_objection():
    """Per-objection resolution: the skeptic (who raised it) certifies which prior objections the revision resolves.
    An objection raised in round 1 that the round-2 skeptic marks resolved must carry resolved_round=2 in the
    ledger; the UI reads this to show 'Resolved R2' instead of the coarse round-derived 'carried'."""
    scripts = {
        "propose_hypothesis": [_candidate(), _candidate(), _candidate()],
        "raise_objections": [
            {"objections": [_obj("undefined_term")]},          # round 1 -> objection id r1.1 (substantive, blocks)
            {"objections": [], "resolved": ["r1.1"]},          # round 2: skeptic certifies r1.1 addressed; clean
            {"objections": []},
        ],
        "rule": [_verdict(new_substantive_objection_this_round=True, open_objections_resolved=False), _verdict(), _verdict()],
    }
    h = council.deliberate("q", max_rounds=4, quota=0, client=FakeClient(scripts),
                           models={"proposer": "m", "skeptic": "m", "judge": "m"}, verbose=False)
    led = {o["id"]: o for o in h.objection_ledger}
    assert "r1.1" in led and led["r1.1"]["round"] == 1
    assert led["r1.1"]["resolved_round"] == 2      # certified resolved by the round-2 skeptic, not just "carried"


def test_to_design_clamps_over_specified_scale():
    """The proposer sometimes asks for 20x20 (~400 sims/design). _to_design clamps to a runnable proposal
    (seeds<=8, generations<=6) so the human isn't handed an unaffordable falsifier; in-range values pass through."""
    big = council._to_design({"perturbation": "gene_knockout", "condition": "basal",
                              "seeds": 20, "generations": 20, "params": {"target_genes": ["alaS"]}})
    assert big.seeds == 8 and big.generations == 6
    ok = council._to_design({"perturbation": "gene_knockout", "condition": "basal",
                             "seeds": 4, "generations": 3, "params": {"target_genes": ["alaS"]}})
    assert ok.seeds == 4 and ok.generations == 3            # a sane proposal is left untouched


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok:", name)


def test_proposer_prompt_uses_registry_guidance_no_stale_threshold():
    """DD-TCV-1: the proposer prompt embeds the registry-GENERATED guidance (so its examples + 'not available' note
    can't drift from the enum), and no longer coaches the pre-DD-MTH-1 flat |t|>=2 threshold — disconfirm is now
    df-aware (p<0.05 at the Welch df)."""
    from cellarium import test_registry
    assert test_registry.proposer_guidance() in council._PROPOSER_SYS   # the prompt uses the generated block
    assert "|t|>=2" not in council._PROPOSER_SYS and "|t| >= 2" not in council._PROPOSER_SYS   # stale threshold gone
    assert ", ".join(test_registry.supported_ids()) in council._PROPOSER_SYS   # the enforced enum is still the registry
