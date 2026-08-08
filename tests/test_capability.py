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


def test_every_mode_that_refuses_has_words_for_that_mode():
    """A capability refused in a mode must have prose ABOUT THAT MODE — checked once per refusing mode.

    This replaces an assertion that `c.instead` was merely non-empty. That test could not survive the prose
    becoming mode-keyed: a non-empty TABLE is evidence of nothing, since the sentence it holds may be keyed to
    a mode the capability is never refused in, and the assertion would have passed on exactly the payload it
    exists to forbid. The demand is therefore made against the RESOLVED text, per mode — strictly stronger, and
    it now covers the `holds_in=()` entries the old form skipped.

    The ported-but-off case (c) is exempt for the reason the tool-surface test already gives: that model DOES
    represent the mechanism, so demanding a substitute would force an invented one. What case (c) must render
    is pinned by test_the_ported_but_off_refusal_describes_the_corpus_not_the_mode_asked_about."""
    for c in capability.CAPABILITIES:
        for mode in capability.ELONGATION_MODES:
            if capability.answerable_in(c, mode) or (c.holds_in and mode in c.holds_in):
                continue
            assert c.instead_in(mode), f"{c.key} is refused under {mode} with nothing to say it does instead"
            assert c.consequence_in(mode), f"{c.key} is refused under {mode} but never says how it misleads"


@pytest.mark.parametrize("mode", capability.ELONGATION_MODES)
def test_a_refusal_never_renders_another_modes_prose(mode):
    """THE regression. `instead`/`consequence` were single strings written when there was one elongation model,
    so a refusal rendered in one mode quoted a sentence about a different one: asked about per-isoacceptor
    charging under coarse_kinetic it described the steady-state 20-state ODE broadcast, and asked about
    per-amino-acid charging under kinetic it described the coarse model's np.zeros(86) as what the STEADY-STATE
    corpus does. Fluent text about the wrong model is worse than a bare refusal — it reads as informed, and an
    agent repeats it.

    Two halves, and both are needed. No sentence keyed to a mode other than the refusal's subject may appear in
    the rendered string; AND the subject's own sentences must appear when they exist, so this cannot be
    satisfied by a 'fix' that renders no prose at all."""
    for c in capability.CAPABILITIES:
        if capability.answerable_in(c, mode):
            continue
        r = c.refusal(mode)
        subject = c.prose_subject(mode)
        for name in ("instead", "consequence"):
            table = getattr(c, name)
            for key, text in table.items():
                claims = (key,) if isinstance(key, str) else tuple(key)
                if subject in claims:
                    continue
                assert text not in r, (
                    f"{c.key}.{name} keyed to {claims} was rendered in a {mode} refusal, whose subject is "
                    f"{subject} — this is prose about a model the run did not use")
        for resolved in (c.instead_in(mode), c.consequence_in(mode)):
            if resolved:
                assert resolved in r, f"{c.key}: the {subject} prose resolved but never reached the refusal"


def test_the_ported_but_off_refusal_describes_the_corpus_not_the_mode_asked_about():
    """The subtlest of the three, and the one place where quoting the asked-for mode would be wrong.

    Case (c)'s sentence is "what THOSE RUNS do instead", and "those runs" is the corpus — every row of which is
    steady_state. Quoting the mode in the question would describe a model that has never produced a row, inside
    a refusal whose entire content is that no such row exists.

    RETARGETED 2026-08-08, because the FACT changed and the property did not. This asked
    `per_isoacceptor_trna_charging.refusal("kinetic")` for case (c). The kinetic campaign this very registry
    proposed then landed, `MODES_IN_CORPUS` gained "kinetic", and the honest answer became "IS answerable
    here" — which `capability.py` already guards for explicitly, by design, with the measurement in its
    comment. Asserting the old sentence would require the registry to keep telling a reader no kinetic run
    exists while twelve sit in the manifest: the silent-absence shape, demanded by a test.

    So case (c) is now exercised through `coarse_kinetic` — a model that holds for this entry and has produced
    no row — which is exactly the state the branch describes, and the live kinetic fact is pinned separately
    below rather than frozen.
    """
    c = capability.get("per_isoacceptor_trna_charging")
    assert c.prose_subject("kinetic") == capability.DEFAULT_MODE

    # Case (c), reached through a mode that genuinely has no runs.
    ported = capability.get("knockout_of_a_multi_transcription_unit_gene")
    assert "coarse_kinetic" in ported.holds_in and "coarse_kinetic" not in capability.MODES_IN_CORPUS, \
        "this test needs a mode that HOLDS but has no runs — re-point it if the corpus gains coarse rows"
    r = ported.refusal("coarse_kinetic")
    assert "no run in the corpus" in r.lower()
    assert capability.DEFAULT_MODE in r, \
        "'what those runs do instead' must name the CORPUS's model, not the one asked about"

    # And the fact that changed, asserted as a fact rather than assumed: a mode WITH runs is not refused.
    assert "kinetic" in capability.MODES_IN_CORPUS
    rk = c.refusal("kinetic")
    assert "no run in the corpus" not in rk.lower(), (
        "the registry told a reader no kinetic run exists while the corpus holds them — the silent-absence "
        "failure this registry exists to prevent, emitted by the registry itself")
    assert "answerable" in rk.lower() and "do not treat this as a refusal" in rk.lower()

    # The case where the honest answer is SILENCE. per_amino_acid_trna_charging holds in steady_state, so the
    # corpus does nothing "instead" of it; the only mode that lacks it is coarse_kinetic, and that sentence
    # must not be dragged into a kinetic refusal about steady-state rows. It used to be, verbatim.
    p = capability.get("per_amino_acid_trna_charging")
    rk = p.refusal("kinetic")
    assert p.instead_in("kinetic") == "" and p.consequence_in("kinetic") == ""
    assert "np.zeros(86)" not in rk and "does not solve charging" not in rk
    assert p.instead_in("coarse_kinetic"), "the coarse sentence is still there — it is simply keyed to coarse"
    # This entry HOLDS in kinetic, and kinetic now has runs, so it is honestly answerable there — it is no
    # longer an example of anything being refused. The property it was carrying, that SILENCE about the
    # substitute must not soften the refusal, is real and now has no live case, so it is exercised directly:
    # a capability with no prose at all must still produce a refusal that refuses.
    assert capability.check("per_amino_acid_trna_charging", mode="kinetic")["can_answer"] is True, \
        "this entry holds in kinetic and the corpus has kinetic runs — refusing it would be the inverse error"
    mute = capability.Capability(key="mute", question="q?", present=True, holds_in=("steady_state",))
    assert mute.instead_in("coarse_kinetic") == "" and mute.consequence_in("coarse_kinetic") == ""
    assert "CANNOT represent" in mute.refusal("coarse_kinetic"), \
        "silence about the substitute must not soften the refusal itself"


def test_the_multi_tu_knockout_caveat_is_not_tied_to_the_elongation_model():
    """This entry's prose is about the VARIANT axis — `gene_knockout` vs `graded_gene_knockout` — which is
    orthogonal to elongation. Keyed to one mode it would imply the caveat arrives with that mode; keyed to all
    of them it says the caveat is invariant, which it is. So: identical in every mode, naming no elongation
    model, and still reaching the refusal, since 'what those corpus runs do instead' is a real answer."""
    c = capability.get("knockout_of_a_multi_transcription_unit_gene")
    rendered = {m: (c.instead_in(m), c.consequence_in(m)) for m in capability.ELONGATION_MODES}
    assert len(set(rendered.values())) == 1, f"the variant caveat differs by elongation model: {rendered}"
    instead, consequence = rendered[capability.DEFAULT_MODE]
    assert instead and consequence, "keying it to every mode must not mean losing it"
    for m in capability.ELONGATION_MODES:
        assert m not in instead and m not in consequence, \
            f"the variant caveat names elongation model {m!r}, implying the two axes are related"
    assert "graded_gene_knockout" in c.available_in and "variant" in c.flag, \
        "the route out is a VARIANT, and it must be stated as one"
    # The caveat must survive into a refusal that actually refuses. Asked under a mode the CORPUS now contains,
    # this entry is answerable and correctly returns no refusal at all, so the caveat is checked under
    # `coarse_kinetic` — holds here, no rows — which is the case-(c) sentence the caveat belongs to.
    assert instead in c.refusal("coarse_kinetic")
    assert "no run in the corpus" not in c.refusal("kinetic").lower(), \
        "a mode the corpus contains must not be refused for lack of runs"


def test_every_prose_key_is_a_real_mode():
    """A typo'd key ('kinetc') makes that sentence unreachable in every mode and nothing raises — the refusal
    just quietly degrades to a bare 'no'. That is the silent-absence shape this repo keeps re-encountering, so
    it is audited rather than trusted, and a field reverted to a bare string fails here too."""
    for c in capability.CAPABILITIES:
        for name in ("instead", "consequence"):
            table = getattr(c, name)
            assert isinstance(table, dict), \
                f"{c.key}.{name} must be mode-keyed — an unkeyed string is how the wrong model gets described"
            for m in capability._prose_keys(table):
                assert m in capability.ELONGATION_MODES, f"{c.key}.{name} claims undeclared mode {m!r}"
    assert not capability.audit()["undeclared_prose_modes"], "and the audit must say so too, not just this test"


def test_a_capability_declared_absent_claims_no_mode():
    """`holds_in` DEFAULTS to every mode, so an entry written with `present=False` and no `holds_in` lands in
    the ported-but-off branch and opens with 'The mechanism for X IS present in the model' — the registry
    contradicting its own `present` flag, fluently, in the one sentence an agent will quote. Nothing in the
    code prevents that; this does."""
    for c in capability.CAPABILITIES:
        if not c.present:
            assert c.holds_in == (), f"{c.key} is declared absent but claims to hold in {c.holds_in}"


@pytest.mark.parametrize("mode", capability.ELONGATION_MODES)
def test_the_listing_and_the_refusal_quote_the_same_model(mode):
    """`model_capabilities` is the SECOND renderer of this prose, and two renderers each holding their own copy
    of the rule is how they drift — particularly over case (c), where the subject is the corpus and not the
    mode asked about. Pin that the listing carries the RESOLVED sentence, string-identical to the one inside
    the refusal it ships alongside, and never the raw table."""
    out = tools.model_capabilities(mode=mode)
    for entry in out["cannot_represent"]:
        c = capability.get(entry["capability"])
        assert isinstance(entry["instead"], str), f"{entry['capability']}: a prose TABLE leaked into the payload"
        assert isinstance(entry["why_the_output_misleads"], str), entry["capability"]
        assert entry["instead"] == c.instead_in(mode), entry["capability"]
        assert entry["why_the_output_misleads"] == c.consequence_in(mode), entry["capability"]
        if entry["instead"]:
            assert entry["instead"] in entry["refusal"], \
                f"{entry['capability']}: the listing and the refusal disagree about what the model does instead"


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
    now — so `can_answer`/`report_a_number` stay False and `switch.in_corpus` is always explicit.

    The redirect got MORE dangerous, not less, when the kinetic campaign landed. This used to assert
    `in_corpus is False` for the steady_state -> kinetic redirect, on the reasoning that no kinetic run
    existed. Twelve now do, so the honest value is True — and that is precisely when "another model
    represents this" is most easily read as "so go and read those": the rows are right there. The permission
    invariant is therefore asserted against the harder case, not retired with the old fact.
    """
    res = capability.check("per_isoacceptor_trna_charging")           # steady_state -> kinetic
    assert res["why_not"] == "another_mode_represents_it"
    assert res["can_answer"] is False and res["report_a_number"] is False, (
        "the redirect became permission: the destination mode now HAS runs, which is exactly when an agent "
        "will read them and call the question answered under the mode it actually asked about")
    assert res["answerable_in"], "a redirect with no destination is just a refusal wearing a label"
    assert res["switch"]["in_corpus"] is True and "re-issue" in res["refusal"], \
        "kinetic runs exist; telling the agent to propose a campaign would send it to re-run what it has"

    # The mirror case, and the reason `in_corpus` had to branch: asked in kinetic mode, ppGpp redirects to
    # steady_state, which the ENTIRE corpus already is. "Propose a run" would be exactly wrong here.
    back = capability.check("ppgpp_stringent_response", mode="kinetic")
    assert back["why_not"] == "another_mode_represents_it"
    assert back["switch"]["mode"] == "steady_state" and back["switch"]["in_corpus"] is True
    assert "re-issue" in back["refusal"]

    # The OTHER branch — redirect to a mode with no runs — now has no live example, because every mode any
    # registry entry redirects to is in the corpus. Built synthetically rather than dropped: an untested
    # branch is how "propose a NEW RUN" would rot into "re-issue" for a mode that has nothing to re-issue.
    probe = capability.Capability(key="probe", question="q?", present=True,
                                  holds_in=("coarse_kinetic",), available_in="a test fixture")
    assert "coarse_kinetic" not in capability.MODES_IN_CORPUS, "re-point this probe if coarse rows land"
    r = probe.refusal(capability.DEFAULT_MODE)
    assert "no run in the corpus used it" in r.lower()
    assert "NEW RUN to propose" in r and "re-issue the query" not in r


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
    c = capability.get("ppgpp_stringent_response")
    for mode in ("kinetic", "coarse_kinetic"):
        res = capability.check("ppgpp_stringent_response", mode=mode)
        assert res["can_answer"] is False, mode
        assert "constant" in res["refusal"] or "frozen" in res["refusal"], mode
        # The account rendered must be of the model the question was asked under. One tuple-keyed sentence
        # covers both kinetic models because it was audited as true of both — that is a claim, not a shortcut.
        assert c.instead_in(mode) == c.instead_in("kinetic"), mode
    assert capability.check("ppgpp_stringent_response")["can_answer"] is True, \
        "steady_state — the whole corpus — must keep answering it"
    # And the mirror, which is what mode-keying buys: under steady_state ppGpp IS live, so 'nothing synthesises
    # or degrades ppGpp' is simply false there and must be unreachable, not merely unused.
    assert c.instead_in("steady_state") == "" and c.consequence_in("steady_state") == "", \
        "the kinetic account of ppGpp must not be reachable from the mode where ppGpp is computed"
