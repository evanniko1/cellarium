"""GATE-2b — a connected agent must be inside the CAPABILITY gate even when it is outside the CONSENT gate.

TWO GATES, AND THEY ARE NOT THE SAME KIND OF THING. This surface has always had a consent gate: may a
third-party agent spend the operator's compute and write to their launch queue? That one is liftable on
purpose. A subagent cannot consent on a person's behalf, so without a way to pre-grant it an autonomous
investigate-simulate-reread loop cannot be built at all, and refusing to offer one would be a capability hole
dressed as safety.

The capability gate answers a different question -- can this model represent what is being asked? -- and
serves the truth of the answer rather than the operator's control of their machine. **Lifting it does not
grant autonomy; it grants the ability to be confidently wrong.** There is no autonomous workflow improved by
removing it.

WHAT WAS WRONG. `CELLARIUM_MCP_EXPOSE_ALL=1` lifted both, and said so about neither. In the default
three-tool mode a connected agent's questions arrive through `ask_cellwright`, which calls
`orchestrate.gate_question` before dispatching. With the flag set, `call()` went straight to
`tools.dispatch` and the registry was never consulted -- while that agent, unlike a Python caller who has
already chosen the quantity and the design, is usually answering a natural-language question from its own
user, which is exactly the case the gate exists for. The flag's description said it "does not grant
permission to anything that was refused": true, and on the wrong axis.

WHAT THE FIX DELIBERATELY DOES NOT DO. It does not refuse every capability-scoped read. The measured 0.0
within-family spread this project rests on was obtained by READING a value whose capability does not hold and
reporting it with its scope attached; a surface that refused it outright would have made that finding
unobtainable. So a capability absent in EVERY mode refuses, and one absent only in the mode being read
returns the value with the registry's sentence attached to it.
"""

from __future__ import annotations

import pytest

from cellarium import capability, mcp

# ---------------------------------------------------------------------------------------------------------
# resolving what a call will read, before it reads it
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("design,expected", [
    ("gene_knockout/KO:argS", "steady_state"),
    ("gene_knockout/KO:argS#elong:kinetic", "kinetic"),
    ("wildtype/basal#elong:coarse_kinetic", "coarse_kinetic"),
])
def test_the_mode_is_resolved_from_the_label_without_touching_the_corpus(design, expected):
    """It has to be a PRE-check, so it cannot depend on reading the rows it is deciding about."""
    assert mcp._mode_of({"design": design}) == expected


def test_an_explicit_elongation_model_wins_over_the_label():
    assert mcp._mode_of({"design": "wildtype/basal", "elongation_model": "kinetic"}) == "kinetic"


def test_an_unparseable_label_falls_back_to_the_default_rather_than_failing():
    """A label this cannot parse must not take the surface down, and must not be read as 'no capability
    applies' either -- it reads as the default mode, which is the mode every corpus row was produced in."""
    assert mcp._mode_of({"design": "@@ not a design @@"}) == capability.DEFAULT_MODE


# ---------------------------------------------------------------------------------------------------------
# the two outcomes
# ---------------------------------------------------------------------------------------------------------

def test_a_capability_absent_in_every_mode_is_refused():
    """The rRNA operon case: the variant's dose survives and the operon identity does not, in all three
    elongation models. No reading of that output means what its name says, so there is nothing to annotate."""
    r = mcp.capability_precheck("differential", {"target": "rrna_operon_knockout/minimal|rRNA_KO:4op"})
    assert r is not None, "a design whose capability holds in no mode was allowed through"
    assert r["tier"] == "not_representable_in_any_mode"
    assert r["refused_by"] == "cellarium-capability-gate"
    assert "operon_specific_rrna_knockout" in r["capabilities"]
    assert any("synth_prob_from_ppgpp" in w or "MEAN" in w for w in r["why"]), \
        "the refusal does not carry the mechanism, which is what makes it source-derived"


def test_the_emptiness_of_holds_in_is_the_condition_not_presence():
    """Pins the fix to a real bug. The first version also required `present`, which excluded the strongest
    case: a capability declared absent from the checkout has `present=False`, and that is more absent."""
    cap = capability._BY_KEY["operon_specific_rrna_knockout"]
    assert cap.present is False and cap.holds_in == (), "fixture assumption"
    assert mcp.capability_precheck("differential", {"target": "rrna_operon_knockout/x"}) is not None


def test_a_capability_absent_only_in_the_read_mode_is_annotated_not_refused():
    """The value must stay obtainable; what must not happen is the number travelling without its scope."""
    args = {"design": "wildtype/basal#elong:coarse_kinetic"}
    assert mcp.capability_precheck("trna_families", args) is None, \
        "refusing here would have made the 0.0 within-family finding unobtainable"
    note = mcp.capability_note("trna_families", args)
    assert note is not None
    assert "per_amino_acid_trna_charging" in note["does_not_hold"]
    assert note["elongation_model"] == "coarse_kinetic"
    assert note["what_the_model_does_instead"] and note["what_the_model_does_instead"][0]


def test_the_annotated_case_on_data_the_corpus_CAN_produce():
    """The test above uses a `coarse_kinetic` label, which exercises the logic and which NO ROW CARRIES --
    the corpus has no runs in that mode. End-to-end validation against the real surface caught that: the
    scenario a connected agent actually hits is ppGpp under the kinetic model, where the stringent response
    is uncoupled and kinetic runs exist. A unit test whose only case is unreachable in practice is a test of
    the code rather than of the situation.
    """
    args = {"design": "wildtype/basal#elong:kinetic", "channel": "ppgpp_conc"}
    assert mcp.capability_precheck("trajectory", args) is None
    note = mcp.capability_note("trajectory", args)
    assert note is not None and note["does_not_hold"] == ["ppgpp_stringent_response"]
    assert note["elongation_model"] == "kinetic"


def test_nothing_is_said_when_every_capability_holds():
    """A note on every call would be noise, and noise is how a caveat stops being read."""
    args = {"design": "wildtype/basal"}
    assert mcp.capability_precheck("trna_families", args) is None
    assert mcp.capability_note("trna_families", args) is None


def test_a_channel_argument_carries_its_own_dependency():
    """`ppgpp_conc` under the kinetic model is the stringent response, which kinetic does not couple --
    whatever tool is doing the reading."""
    note = mcp.capability_note("trajectory", {"design": "wildtype/basal#elong:kinetic",
                                              "channel": "ppgpp_conc"})
    assert note is not None and "ppgpp_stringent_response" in note["does_not_hold"]


def test_an_undeclared_tool_is_not_thereby_declared_safe():
    """The table is incomplete by construction, the same limit the registry carries. A tool absent from it
    passes, and this test exists so that is a recorded decision rather than an assumption nobody wrote down."""
    assert mcp.capability_precheck("survey_corpus", {}) is None
    assert mcp.capability_note("survey_corpus", {}) is None


# ---------------------------------------------------------------------------------------------------------
# the wiring: the gate is on the dispatch path, not beside it
# ---------------------------------------------------------------------------------------------------------

def test_the_raw_tool_path_consults_the_gate(monkeypatch):
    """The whole point. With EXPOSE_ALL set, a raw call must still reach the capability check."""
    monkeypatch.setenv(mcp.EXPOSE_ALL_ENV, "1")
    seen = {}

    def _boom(name, args):
        seen["dispatched"] = name
        return {"value": 1}

    import cellarium.tools as tools_mod
    monkeypatch.setattr(tools_mod, "dispatch", _boom)

    out = mcp.call("differential", {"target": "rrna_operon_knockout/minimal|rRNA_KO:4op"})
    assert "dispatched" not in seen, "the tool ran despite a capability absent in every mode"
    assert out.get("refused_by") == "cellarium-capability-gate"


def test_an_allowed_raw_call_carries_the_verdict_with_its_result(monkeypatch):
    """The other direction: the call goes through, and the scope travels attached to the number."""
    monkeypatch.setenv(mcp.EXPOSE_ALL_ENV, "1")
    import cellarium.tools as tools_mod
    monkeypatch.setattr(tools_mod, "dispatch", lambda name, args: {"charged": 0.0})

    out = mcp.call("trna_families", {"design": "wildtype/basal#elong:coarse_kinetic"})
    assert out["charged"] == 0.0, "the value must still be obtainable"
    assert "capability" in out, "the number came back without the registry's verdict attached"
    assert "per_amino_acid_trna_charging" in out["capability"]["does_not_hold"]


def test_the_consent_gate_is_still_the_liftable_one(monkeypatch):
    """The distinction, pinned. EXPOSE_ALL lifts visibility of the read surface and nothing else; the write
    tier and the never tier are untouched by it, and the capability gate is not liftable at all."""
    monkeypatch.setenv(mcp.EXPOSE_ALL_ENV, "1")
    monkeypatch.delenv(mcp.ALLOW_WRITES_ENV, raising=False)
    monkeypatch.delenv(mcp.ALLOW_ALL_ENV, raising=False)
    for name in mcp._NEVER:
        assert mcp.refusal(name) is not None, f"{name} became reachable under EXPOSE_ALL"
    for name in mcp._WRITE_GATED:
        assert mcp.refusal(name) is not None, f"{name} became reachable under EXPOSE_ALL"
    # and the capability gate has no environment variable at all
    import inspect
    src = inspect.getsource(mcp.capability_precheck)
    assert "environ" not in src and "getenv" not in src, \
        "the capability gate reads an environment variable; it must not be liftable"
