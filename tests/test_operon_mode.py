"""Operons ON/OFF advice, and the launch-surface probe that makes a dead flag loud.

Both are about the same failure shape and neither is about a number being wrong.

`capability.probe_launch_surface` exists because we shipped `MODE_FLAGS["kinetic"] =
"--kinetic-trna-charging"` while the file that DEFINES that option was withheld from the overlay. On a
public clone `check()` said "yes, run it in kinetic mode", the launcher emitted the flag, and argparse
rejected the command line. Nothing in the registry could see it, because a flag is not a capability
MARKER. These tests pin that it is seen now — including the case that matters most, an UNREADABLE
checkout, which must report `verified: False` rather than a green tick.

`operons.advise` exists because the operon option changes what every other answer MEANS. The tests
below pin the two things the advice must never do: invent a measured ON-vs-OFF difference (this
project has never run operons OFF), and quietly let an operons-OFF row be compared with the corpus.
"""

from __future__ import annotations

import os

import pytest

from cellarium import capability, operons, tools


# --------------------------------------------------------------------------------------------------
# probe_launch_surface
# --------------------------------------------------------------------------------------------------
def test_an_unreadable_checkout_is_unverified_not_green():
    """The silent-absence bug, pinned. "Could not read" must never be reported as "nothing wrong"."""
    out = capability.probe_launch_surface("")
    assert out["verified"] is False
    assert out["why"], "an unverified probe must say WHY it could not measure"
    # `ok` stays True so an audit run without a checkout is not a false alarm — which is exactly why
    # `verified` has to be checked, and why audit() carries a comment saying so.
    assert out["ok"] is True
    assert out["flags"] == {} and out["variants"] == {}


def test_every_mode_flag_is_probed_and_the_default_needs_no_flag():
    out = capability.probe_launch_surface(os.path.dirname(__file__))   # a dir with no model in it
    # a directory that exists but is not a checkout is still UNVERIFIED, not a pile of failures
    assert out["verified"] is False
    # and the mapping it would probe covers every declared mode
    assert set(capability.MODE_FLAGS) == set(capability.ELONGATION_MODES)
    assert not capability.MODE_FLAGS[capability.DEFAULT_MODE].startswith("--"), (
        "the default mode must be the ABSENCE of a flag — a per-capability flag string cannot express "
        "'go back to steady_state', which is why MODE_FLAGS is a mode-level table")


def test_the_launched_variants_are_the_ones_the_overlay_ships():
    """The three knockout surfaces the task ships must all be probed, not just the new one."""
    for name in ("gene_knockout", "graded_gene_knockout", "multi_gene_knockout"):
        assert name in capability.LAUNCHED_VARIANT_MODULES
    # every probed name must be a real module name, not a Cellarium-side spelling: `wildtype`/`timeline`
    # are perturbation labels and asserting them would fail on a perfectly good checkout.
    for name in capability.LAUNCHED_VARIANT_MODULES:
        assert "/" not in name and not name.startswith("--")


@pytest.mark.skipif(not os.environ.get("WCECOLI_DIR") and not os.environ.get("WCECOLI_PATH"),
                    reason="no model checkout available to probe")
def test_the_real_checkout_has_no_dead_flags():
    out = capability.probe_launch_surface()
    assert out["verified"] is True
    assert out["ok"] is True, out


# --------------------------------------------------------------------------------------------------
# operons.advise
# --------------------------------------------------------------------------------------------------
def test_comparing_with_the_corpus_forces_the_setting():
    a = operons.advise("what happens to growth rate", compare_with_corpus=True)
    assert a["recommendation"] == "keep_operons_on"
    a = operons.advise("what happens to growth rate", compare_with_corpus=False)
    assert a["recommendation"] == "separate_arm_operons_off"
    assert "separate arm" in a["headline"].lower() or "self-contained arm" in a["headline"].lower()


@pytest.mark.parametrize("q", ["should I knock out pfkA?", "KO of murA", "is flgB dispensable",
                               "design a reduced genome", "gene deletion panel", "knock-out screen"])
def test_a_knockout_question_is_routed_to_the_variant_not_a_rebuild(q):
    """The cheap fix for 'my knockout deleted the operon' is `graded_gene_knockout`, not a ParCa rebuild.
    Advising the rebuild would cost a full recalibration AND make the result incomparable."""
    a = operons.advise(q, compare_with_corpus=True)
    assert a["recommendation"] == "use_graded_gene_knockout"
    assert "graded_gene_knockout" in a["knockout_guidance"]
    assert a["cheaper_alternative"]["variant"] == "graded_gene_knockout"


def test_ko_matches_as_a_word_and_not_inside_a_gene_symbol():
    """`ko` as a bare substring fires on the gene symbol `kdpA` and on 'knock'. The first version of this
    branch used substring matching for everything and never fired on 'knock out' (with the space)."""
    assert operons.advise("KO of murA")["recommendation"] == "use_graded_gene_knockout"
    assert operons.advise("does kdpA matter")["recommendation"] == "keep_operons_on"
    assert operons.advise("what is the growth law")["recommendation"] == "keep_operons_on"


def test_the_gap_is_stated_at_the_width_it_actually_has():
    """This test previously asserted the prose said operons-OFF had "never run". It had — OPERONS-3
    ran ParCa and simulations under OFF — and that first-draft sentence was written from memory rather
    than read off the backlog. Both halves are pinned now, because the failure this module exists to
    prevent is a confident sentence about evidence nobody re-opened.

    What IS unestablished is narrower: no KNOCKOUT has been run under OFF, and OPERONS-1's tests are
    still open. What is NOT unestablished is that OFF runs at all."""
    a = operons.advise()
    joined = " ".join(a["not_established"]).lower()
    assert "no `gene_knockout` has been run under off" in joined or "knockout" in joined
    assert "operons-1" in joined, "must point at the backlog row that would close the gap"
    assert "never run" not in joined, (
        "OPERONS-3 ran operons-OFF: ParCa green in 380 s, probe_relation 0/4309, sims exit 0")

    # the OFF column must carry BOTH: it runs clean, AND it is not a validation reference
    off_for = " ".join(a["tradeoff"]["off"]["for"]).lower()
    off_against = " ".join(a["tradeoff"]["off"]["against"]).lower()
    assert "operons-3" in off_for and "0/4309" in off_for
    assert "not comparable" in off_against
    assert "not a validation reference" in off_against and "0.8416" in off_against, (
        "the measured direction matters: OFF moves FURTHER from the published 0.788, so quoting it as "
        "validation would be backwards")


def test_the_flag_is_declared_a_parca_option_with_no_sim_override():
    """The single fact a user most needs and is most likely to guess wrong: there is no `runSim --operons`."""
    m = operons.advise()["how_the_flag_is_set"]
    assert "runParca" in m["where_it_is_set"]
    assert "runSim" in m["not_a_sim_option"]
    assert m["default"] == "on"
    assert any("DEFAULT_OPERON_OPTION" in c for c in m["code_path"])


def test_the_corpus_count_is_measured_not_asserted():
    """A hardcoded 'all 322 rows are ON' is falsified by one operons-OFF campaign with nothing raising, so
    the count is read from the manifest and the pinned figure is carried alongside as a baseline."""
    c = operons.advise()["corpus"]
    assert "pinned_baseline" in c
    if c["verified"]:
        assert set(c["rows_by_operon_mode"]) and all(isinstance(v, int)
                                                     for v in c["rows_by_operon_mode"].values())
        if not c["all_one_mode"]:
            assert "MUST NOT be pooled" in c["note"]
    else:
        assert c["why"] and "NOT a measurement" in c["note"]


def test_it_is_wired_as_an_agent_tool_and_classified():
    from cellarium import test_registry
    assert "operon_mode_advice" in tools._DISPATCH
    assert any(t["name"] == "operon_mode_advice" for t in tools.TOOLS)
    assert test_registry.unclassified_tools({t["name"] for t in tools.TOOLS}) == []
    out = tools.dispatch("operon_mode_advice", {"question": "knock out flgB"})
    assert out["recommendation"] == "use_graded_gene_knockout"
