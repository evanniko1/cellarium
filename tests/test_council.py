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

    def create(self, **kwargs):
        name = kwargs["tool_choice"]["name"]
        self.calls.append(name)
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
