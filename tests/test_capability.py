"""A mechanism the model cannot represent must produce a refusal, never a number.

Written because we measured a within-family tRNA charging spread of exactly 0.00e+00 and published it as a
result. It was an algebraic identity: one per-amino-acid scalar broadcast across 86 isoacceptor columns. The
model was not silent about a hard question — it was structurally incapable of the question and answered anyway,
with a value indistinguishable from a measurement. These tests pin the guarantee that replaces that.
"""

from __future__ import annotations

import os

import pytest

from cellarium import capability, tools


def test_the_capability_that_burned_us_is_declared_absent():
    c = capability.get("per_isoacceptor_trna_charging")
    # EXT-PORT-1 put the mechanism IN the checkout, so `present` is now honestly True — but the flag defaults
    # OFF and no run in the corpus used it. The distinction is the whole point: a registry that collapsed
    # "ported" into "available" would start green-lighting per-isoacceptor claims against steady-state runs,
    # which is precisely the failure this module was written after.
    assert c is not None and c.present is True and c.default_on is False
    assert capability.check(c.key)["can_answer"] is False
    assert c in capability.missing()
    # the refusal must name the mechanism, the substitute, AND why the output misleads
    r = c.refusal()
    assert "CANNOT" in r
    # This assertion used to read `"defaults OFF" in r`, which described a world with a boolean flag. The
    # elongation model is a three-valued FIELD, not a switch, so that sentence could only be kept by
    # contorting the prose around a string match. It is replaced — deliberately, and named as the one
    # contract edit — by asserts that pin something STRONGER: the refusal must say which mode the corpus is
    # in AND which mode could answer, because a flat "no" here throws away the most useful thing the system
    # can say and is a worse answer, not a safer one.
    assert "elongation_model" in r and "steady_state" in r, "the refusal must name the mode the corpus is in"
    assert "kinetic" in r, "and the mode that CAN answer it — a flat refusal here is a worse answer"
    assert "aa_from_trna" in r, "the refusal must name the actual aggregation that causes it"
    assert "arithmetic" in r or "IDENTICAL BY CONSTRUCTION" in r
    assert "v3.0.1" in r, "must point at where the mechanism does exist"


def _numeric_fields(obj, path=""):
    """Every numeric leaf anywhere in a payload, nested dicts and lists included.

    The scan used to be one level deep, which was enough while a refusal was flat. Case (b) introduced the
    first NESTED dict in a refusal (`switch`), and a nested field the scanner does not descend into is a hole
    in the one rule the payload has — opened by the very change that added the nesting. This is a contract
    EXTENSION, not a relaxation, and it lands with the nesting rather than after it."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _numeric_fields(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _numeric_fields(v, f"{path}[{i}]")
    # `bool` subclasses `int` in Python, so a type check alone flags the flags. Exclude bools explicitly.
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(path)
    return out


@pytest.mark.parametrize("mode", capability.ELONGATION_MODES)
def test_an_unsupported_capability_returns_a_refusal_and_forbids_a_number(mode):
    """THE contract Cellwright depends on: can_answer False always carries a refusal and never a value.

    Checked in EVERY mode, because mode-aware code tested in one mode is untested code."""
    for key in (c.key for c in capability.missing(mode)):
        res = capability.check(key, mode)
        assert res["can_answer"] is False
        assert res.get("refusal"), key
        assert res.get("report_a_number") is False, key
        numeric = _numeric_fields(res)
        assert not numeric, \
            f"{key}: a refusal must not carry numeric field(s) {numeric} — mistakable for a result"


def test_an_undeclared_capability_is_not_treated_as_absent():
    """Absence of a declaration is not evidence of absence of the mechanism — the silent-absence rule again."""
    res = capability.check("some_mechanism_nobody_declared")
    assert res["known"] is False and res["can_answer"] is None
    assert "not evidence of absence" in res["note"]


def test_declarations_agree_with_the_model_checkout():
    """Declared AND probed. A stale `present=True` is confidently-wrong metadata, which is worse than none."""
    if not (os.environ.get("WCECOLI_DIR") and os.path.isdir(os.environ["WCECOLI_DIR"])):
        pytest.skip("no model checkout to probe")
    a = capability.audit()
    assert a["ok"], f"registry disagrees with the checkout: {a['disagreements']}"


def test_probing_without_a_checkout_says_unverified_rather_than_confirmed():
    res = capability.probe(wcecoli="/definitely/not/a/checkout")
    assert all(r.agrees for r in res)
    assert all("UNVERIFIED" in r.note for r in res), \
        "with nothing to probe, the result must read as unverified — never as confirmation"


def test_the_agent_has_the_tool_and_is_told_to_use_it():
    from cellarium import agent
    assert "model_capabilities" in tools._DISPATCH, "the tool must be dispatchable by the agent loop"
    names = {t["name"] for t in tools.TOOLS}
    assert "model_capabilities" in names
    low = agent.SYSTEM.lower()
    assert "model_capabilities" in agent.SYSTEM
    assert "cannot represent" in low and "measurement of zero" in low
    assert "isoacceptor" in low, "the prompt must name the concrete trap, not just the principle"


def test_the_tool_surface_separates_can_from_cannot():
    out = tools.model_capabilities()
    cannot = {c["capability"] for c in out["cannot_represent"]}
    can = {c["capability"] for c in out["can_represent"]}
    assert "per_isoacceptor_trna_charging" in cannot, "ported but off by default is still not answerable"
    assert "per_isoacceptor_trna_charging" in {
        c["capability"] for c in out["ported_but_off_by_default"]}
    assert "per_amino_acid_trna_charging" in can, "what the model DOES do must be declared too"
    assert not (cannot & can)
    for c in out["cannot_represent"]:
        assert c["instead"] and c["why_the_output_misleads"], c["capability"]
    assert out["elongation_model"] == capability.DEFAULT_MODE, \
        "the view must SAY which model it is conditioned on — an unconditional picture is a lie under three"


@pytest.mark.parametrize("mode", capability.ELONGATION_MODES)
def test_the_tool_surface_holds_in_every_elongation_mode(mode):
    """The original version of this test only ever exercised the default mode, so it would have passed while
    the kinetic view was broken. The specific hole it left open is ppGpp: the kinetic view is the ONLY view
    in which that entry is a refusal, and it was the view no test looked at — its `instead`/`consequence`
    were empty, invisible while it sat in can_represent, and would have become a bare 'no' the moment a
    kinetic view moved it into cannot_represent."""
    out = tools.model_capabilities(mode=mode)
    assert out["elongation_model"] == mode
    cannot = {c["capability"] for c in out["cannot_represent"]}
    can = {c["capability"] for c in out["can_represent"]}
    assert not (cannot & can), f"{mode}: a capability cannot be both answerable and refused"
    for c in out["cannot_represent"]:
        assert c["why_not"] in ("no_elongation_model_represents_it", "another_mode_represents_it",
                                "no_run_used_this_mode"), c["why_not"]
        # Give the agent the WORDS. Until now only the single-key form returned a refusal, so an agent that
        # called the listing had to compose one from the parts — and composing is where the hedge creeps in.
        assert c["refusal"], f"{mode}/{c['capability']}: the listing must carry the refusal verbatim"
        if c["why_not"] == "no_run_used_this_mode":
            # Nothing to say about "what it does instead": this model DOES represent the mechanism, and the
            # only gap is that no run used it. Demanding a substitute here would force an invented one.
            assert c["switch"]["in_corpus"] is False, f"{mode}/{c['capability']}"
            continue
        assert c["instead"], f"{mode}/{c['capability']}: a refusal with no substitute is a bare no"
        assert c["why_the_output_misleads"], f"{mode}/{c['capability']}"


def test_every_declared_mode_is_a_real_mode():
    """A typo'd mode name in `holds_in` would silently make a capability answerable nowhere, with no error."""
    for c in capability.CAPABILITIES:
        unknown = [m for m in c.holds_in if m not in capability.ELONGATION_MODES]
        assert not unknown, f"{c.key} declares undeclared elongation model(s) {unknown}"


def test_a_partial_holds_in_promises_that_the_redirect_has_words():
    """A capability real in SOME modes will be refused in the others, and that refusal quotes `instead` and
    `consequence`. Declaring a partial `holds_in` without them queues up a bare 'no'."""
    for c in capability.CAPABILITIES:
        if c.holds_in and set(c.holds_in) != set(capability.ELONGATION_MODES):
            assert c.instead, f"{c.key} holds in {c.holds_in} but says nothing about what happens elsewhere"
            assert c.consequence, f"{c.key} holds in {c.holds_in} but never says how the output misleads"


def test_the_coarse_model_reports_zeros_and_the_registry_refuses_them():
    """The finding this axis turned up, pinned so a future edit cannot quietly re-widen it.

    `per_amino_acid_trna_charging` was declared present with no qualification. Under coarse_kinetic,
    `CoarseKineticTrnaChargingModel.request` and `.evolve` both return `np.zeros(86)` — so
    `fraction_trna_charged` is IDENTICALLY 0.00 in all 86 columns at every timestep. A registry vouching for
    that capability green-lights reading a column of zeros as 100% uncharged tRNA: a dramatic, publishable,
    entirely fabricated starvation phenotype. Steady-state gave a within-family SPREAD of 0.00 (an identity);
    this is the ABSOLUTE LEVEL at 0.00 (no model at all), which is strictly worse."""
    res = capability.check("per_amino_acid_trna_charging", mode="coarse_kinetic")
    assert res["can_answer"] is False
    assert res["report_a_number"] is False
    assert "zeros" in res["refusal"] or "0.00" in res["refusal"]


def test_a_redirect_is_never_permission():
    """Case (b) is the only non-flat refusal, so it is the only one that could become an attack surface: an
    agent told 'the kinetic model represents this' will otherwise go looking for a kinetic run, find
    steady-state rows, and read them anyway. The redirect changes what to DO NEXT, never what may be reported
    now — so `can_answer`/`report_a_number` stay False and `switch.in_corpus` is always explicit."""
    res = capability.check("per_isoacceptor_trna_charging")           # steady_state -> kinetic
    assert res["why_not"] == "another_mode_represents_it"
    assert res["can_answer"] is False and res["report_a_number"] is False
    assert res["answerable_in"], "a redirect with no destination is just a refusal wearing a label"
    assert res["switch"]["in_corpus"] is False, "no kinetic run exists — say so, or the agent will hunt one"
    assert "propose" in res["refusal"] or "NEW RUN" in res["refusal"]

    # The mirror case, and the reason `in_corpus` had to branch: asked in kinetic mode, ppGpp redirects to
    # steady_state, which the ENTIRE corpus already is. "Propose a run" would be exactly wrong here.
    back = capability.check("ppgpp_stringent_response", mode="kinetic")
    assert back["why_not"] == "another_mode_represents_it"
    assert back["switch"]["mode"] == "steady_state" and back["switch"]["in_corpus"] is True
    assert "re-issue" in back["refusal"]


def test_an_unknown_elongation_mode_is_not_treated_as_a_refusal():
    """Absence of a declaration is not evidence of absence — the silent-absence rule, applied to the mode."""
    res = capability.check("ppgpp_stringent_response", mode="hyperdrive")
    assert res["can_answer"] is None and res["known_mode"] is False
    assert "not a declared elongation model" in res["note"]


def test_ppgpp_is_refused_under_both_kinetic_models():
    """The mirror image of the isoacceptor trap, and strictly more dangerous because it fails silently in the
    direction of a NEGATIVE result. Measured in the checkout: 66 ppGpp mentions inside
    SteadyStateElongationModel, and every mention inside either kinetic class is a comment saying ppGpp is
    NOT computed on the codon-aware path. 'We knocked out the synthetase and ppGpp did not rise' is a
    publishable claim, and under either kinetic model it is guaranteed by construction."""
    for mode in ("kinetic", "coarse_kinetic"):
        res = capability.check("ppgpp_stringent_response", mode=mode)
        assert res["can_answer"] is False, mode
        assert "constant" in res["refusal"] or "frozen" in res["refusal"], mode
    assert capability.check("ppgpp_stringent_response")["can_answer"] is True, \
        "steady_state — the whole corpus — must keep answering it"
