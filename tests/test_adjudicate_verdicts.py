"""Stages 3 and 4: can this corpus settle the claim, and what would the demand cost?

STAGE 3 decides ADJUDICABILITY, not truth. It answers "is there an arm of this corpus in which this claim
could be tested, and on which channel" — and deliberately computes no statistic, because that is what
`rigor.disconfirm` and the survey already do and a second implementation of it would be a second answer to
one question (conformance family 9).

Its load-bearing refusal is the ARM boundary. Two designs that exist in different arms were produced by
different fitted parameter sets, so a comparison between them describes nothing; `corpus_schema.same_arm`
is the authority and the verdict names both arms rather than quietly pooling.

STAGE 4 classifies COST, and every class resolves against an existing authority rather than a copy of one:
`capability.MODE_FLAGS`, `capability.LAUNCHED_VARIANT_MODULES`, `envelope.VALIDATED_PERTURBATIONS`,
`capability.DRAFT_PATCHES` and `doe.REFIT_FACTORS`. Conformance family 7 fails any two views of one
capability that disagree without declaring it, and a classifier carrying its own list of runnable variants
would be exactly that.

One bucket produced the wrong headline — "47 of 48 need a parameter rebuild" — and the fix is not a better
regex, it is having classes at all. `not_a_simulation` is the class that six reports needed.

Rows are injected, so none of this touches the corpus.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import adjudicate, capability, doe, envelope, errors  # noqa: E402

KB_A, KB_B = "a" * 64, "b" * 64


def _row(design, kb=KB_A, mode="steady_state", seeds=4):
    return {"design": design, "kb_sha256": kb, "operons": "on", "elongation_model": mode, "seeds": seeds}


ROWS = (
    [_row("gene_knockout/KO:argS") for _ in range(4)]
    + [_row("wildtype/basal") for _ in range(4)]
    + [_row("gene_knockout/KO:hisS", kb=KB_B, mode="kinetic") for _ in range(4)]
    + [_row("gene_knockout/KO:leuS", seeds=1)]
)


def _claim(**kw):
    base = dict(quantity="growth rate falls", target="gene_knockout/KO:argS", reference="wildtype/basal",
                quote="growth rate falls by 20% in the argS knockout", section="Expected Outcomes",
                section_kind="claim")
    base.update(kw)
    return adjudicate.Claim(**base)


# --- stage 3 -----------------------------------------------------------------------------------------

def test_a_claim_both_of_whose_designs_sit_in_one_arm_is_decidable():
    v = adjudicate.adjudicate_claim(_claim(), rows=ROWS)
    assert v["decidable"] is True and "error" not in v
    assert v["channel"] == "growth_rate"
    assert v["arm"]["elongation_model"] == "steady_state"
    assert v["n_target_rows"] == 4 and v["n_reference_rows"] == 4
    # It must NOT have computed an effect: that is another component's answer.
    assert "effect" not in v and "p_value" not in v


def test_a_claim_whose_designs_sit_in_DIFFERENT_arms_is_refused_naming_both():
    v = adjudicate.adjudicate_claim(_claim(target="gene_knockout/KO:hisS"), rows=ROWS)
    assert v["decidable"] is False
    assert v["reason"] == "no_shared_arm" and v["about"] == "corpus"
    assert "kinetic" in v["error"] and "steady_state" in v["error"]
    assert v["arms_available"] and len(v["arms_available"]) == 2


def test_a_design_the_corpus_does_not_have_is_a_coverage_fact_not_a_caller_error():
    """`unknown_design` is registered ('request', 'fix_argument') because inside the tool surface naming a
    missing design IS the caller's mistake. Here the caller is a document we did not write, so the same
    situation is a fact about our coverage and needs its own code."""
    v = adjudicate.adjudicate_claim(_claim(target="gene_knockout/KO:nothing"), rows=ROWS)
    assert v["decidable"] is False
    assert v["reason"] == "design_not_in_corpus" and v["about"] == "corpus"
    assert v["next_step"] == "run_more"


def test_too_few_replicates_in_the_shared_arm_is_insufficient_data():
    v = adjudicate.adjudicate_claim(_claim(target="gene_knockout/KO:leuS"), rows=ROWS)
    assert v["decidable"] is False and v["reason"] == "insufficient_data"
    assert v["about"] == "corpus" and v["n_target_rows"] == 1


@pytest.mark.parametrize("quantity,reason", [
    ("ribosome profiling shows stalling", "channel_not_recorded"),
    ("the model becomes more faithful", "bad_argument"),
    ("growth rate falls while ppGpp rises", "bad_argument"),
])
def test_the_quantity_verdict_short_circuits_before_any_row_is_read(quantity, reason):
    """Stage 1's verdict is final. A claim naming no channel cannot be settled by any arm, and looking for
    rows first would let a row count stand in for an answer."""
    v = adjudicate.adjudicate_claim(_claim(quantity=quantity), rows=ROWS)
    assert v["decidable"] is False and v["reason"] == reason
    assert "n_target_rows" not in v


def test_a_claim_from_a_wet_lab_section_is_never_adjudicated_against_the_corpus():
    """The six-report mislabelling, as a guard. A bench readout is not a weak claim about the simulator."""
    v = adjudicate.adjudicate_claim(_claim(section_kind="validation_wetlab"), rows=ROWS)
    assert v["decidable"] is False and v["reason"] == "not_applicable_to_design"
    assert "wet-lab" in v["error"] or "bench" in v["error"]


def test_an_empty_corpus_refuses_rather_than_reporting_nothing_to_compare():
    v = adjudicate.adjudicate_claim(_claim(), rows=[])
    assert v["decidable"] is False and v["about"] in ("corpus", "environment")
    assert v["reason"] in ("design_not_in_corpus", "store_unreadable")


def test_every_reason_this_stage_can_emit_is_registered():
    for r in adjudicate.ADJUDICATION_REASONS:
        assert r in errors.REASONS, r


# --- stage 4 -----------------------------------------------------------------------------------------

def _req(text, kind="plan"):
    return adjudicate.Requirement(text=text, quote=text, section="Simulation Design Matrix",
                                  section_kind=kind)


@pytest.mark.parametrize("text,cost,authority_contains", [
    ("run with the kinetic elongation model", "flag", "MODE_FLAGS"),
    ("a graded_gene_knockout at 25% expression", "run", "LAUNCHED_VARIANT_MODULES"),
    ("an amino_acid_shift timeline", "run", "VALIDATED_PERTURBATIONS"),
    ("set trna_charged_fraction_target to 0.55", "rebuild", "REFIT_FACTORS"),
    ("switch operons off", "rebuild", "REFIT_FACTORS"),
    ("enable --kinetic-ppgpp", "patch_then_run", "DRAFT_PATCHES"),
    ("use the kinetic_aa_supply module", "patch_then_run", "DRAFT_PATCHES"),
    ("apply a generation_timed_knockout at generation 2", "refused_by_gate", "VALIDATED_PERTURBATIONS"),
])
def test_each_cost_class_resolves_against_its_own_authority(text, cost, authority_contains):
    out = adjudicate.classify_cost(_req(text))
    assert out["cost"] == cost, out
    assert authority_contains in out["authority"], out["authority"]


def test_a_wet_lab_requirement_is_not_a_simulation_and_the_section_is_the_authority():
    out = adjudicate.classify_cost(_req("monitor stalling by ribosome profiling", kind="validation_wetlab"))
    assert out["cost"] == "not_a_simulation"
    assert "section_kind" in out["authority"]


def test_a_requirement_matching_nothing_is_unresolved_not_a_rebuild():
    """The over-collapse, as a guard: the single-bucket classifier called everything a rebuild."""
    out = adjudicate.classify_cost(_req("make the model more mechanistic"))
    assert out["cost"] == "unresolved" and out["authority"] == ""


def test_a_requirement_matching_two_classes_is_ambiguous_with_both_named():
    out = adjudicate.classify_cost(_req("run the kinetic model with operons off"))
    assert out["cost"] == "ambiguous"
    assert {c["cost"] for c in out["candidates"]} == {"flag", "rebuild"}


def test_the_cost_classes_are_a_closed_set_and_each_is_reachable():
    assert set(adjudicate.COST_CLASSES) == {
        "run", "flag", "patch_then_run", "rebuild", "refused_by_gate", "not_a_simulation",
        "ambiguous", "unresolved"}


def test_the_classifier_holds_no_copy_of_any_authority():
    """Conformance family 7 in miniature: a classifier with its own list of runnable variants is a second
    view of one capability, and the two drift.

    Scoped to the classifier's own source rather than the whole module, because `ppgpp_conc` is legitimately
    both a launched variant module AND a declared channel — a name appearing in the stage-1 vocabulary is
    not a copy of the stage-4 authority. A file-wide check flagged exactly that, which is the same
    proxy-versus-thing error this suite keeps catching, here in the test rather than the code."""
    import inspect
    src = inspect.getsource(adjudicate._cost_candidates)
    for literal in sorted(capability.LAUNCHED_VARIANT_MODULES) + sorted(doe.REFIT_FACTORS):
        assert f'"{literal}"' not in src, f"{literal} is copied into the cost classifier"
    assert "VALIDATED_PERTURBATIONS" in src and "MODE_FLAGS" in src
    assert "REFIT_FACTORS" in src and "LAUNCHED_VARIANT_MODULES" in src and "DRAFT_PATCHES" in src


def test_cost_summary_counts_every_class_including_the_empty_ones():
    """A class with zero members must appear as zero. 'only 4 of 45 need nothing but a rebuild' is only
    readable because every other class was counted too."""
    reqs = [_req("run with the kinetic elongation model"), _req("switch operons off"),
            _req("make it better")]
    s = adjudicate.cost_summary(reqs)
    assert set(s["by_cost"]) == set(adjudicate.COST_CLASSES)
    assert s["by_cost"]["flag"] == 1 and s["by_cost"]["rebuild"] == 1 and s["by_cost"]["unresolved"] == 1
    assert s["by_cost"]["not_a_simulation"] == 0
    assert s["n"] == 3


def test_bad_input_to_either_stage_is_an_argument_error():
    assert adjudicate.classify_cost(None)["cost"] == "unresolved"
    assert "error" in adjudicate.classify_cost(None)
    v = adjudicate.adjudicate_claim(None, rows=ROWS)
    assert v["decidable"] is False and v["about"] == "request"


def test_the_envelope_is_the_authority_for_what_is_refused():
    """Not a list here. If a perturbation becomes validated upstream, this classifier must follow."""
    assert "generation_timed_knockout" not in envelope.VALIDATED_PERTURBATIONS
    out = adjudicate.classify_cost(_req("a generation_timed_knockout"))
    assert out["cost"] == "refused_by_gate"


# --- substring false positives, found by running the classifier over the development set ---------------
#
# The saturation error reappearing one stage later, and caught the same way: by measuring instead of
# trusting. Two matches in the first run were nonsense.
#
#   * `"arm"` is a declared refit lever, and a bare substring test matched the word "Arm" at the start of a
#     markdown TABLE HEADER ("Arm | Carbon Transition | Amino-Acid Module | ..."), classifying a column
#     label as a demand for a ParCa rebuild.
#   * a sentence DESCRIBING the model ("Simulations are conducted within the Covert whole-cell model using
#     the 86-individual ...") matched "kinetic" and became a demand for a flag.
#
# Both are the same shape as `kcat` inside a citation: a word present is not a thing demanded.

@pytest.mark.parametrize("line", [
    "the warm-up generation is discarded",
    "a pharmacological inhibitor is added",
    "measured at 3 kbp from the origin",
])
def test_a_lever_name_inside_another_word_is_not_a_demand(line):
    out = adjudicate.classify_cost(_req(line))
    assert out["cost"] != "rebuild", out


def test_a_table_COLUMN_LABEL_is_not_a_demand_and_the_locator_is_what_prevents_it():
    """The other half of the same finding, and it lands on a different component.

    "Arm | Carbon Transition | Amino-Acid Module | ..." is a markdown table header, and `arm` is genuinely
    its own word in it — so word-boundary matching does not and should not save us. The classifier is
    behaving correctly on the text it was handed; the defect would be handing it a column LABEL as though it
    were a demand. Measured: feeding plan sections to the classifier line by line put table headers in the
    `run` and `rebuild` classes.

    So the guard belongs in the extractor, and the locator already supplies what it needs: a declared
    table's headers and its rows come back separately. This test pins that separation, because the moment
    they are flattened to lines the false positive returns."""
    doc = ("# T\n\n## Simulation Design Matrix\n\n"
           "| Arm | ppGpp Module | Target Charging |\n| --- | --- | --- |\n"
           "| KINAP | on | 0.55 |\n")
    plan = adjudicate.locate(doc)["plan_sections"][0]
    assert plan["table"]["headers"] == ["Arm", "ppGpp Module", "Target Charging"]
    assert plan["table"]["rows"] == [["KINAP", "on", "0.55"]]
    # And the classifier is honest about its own scope rather than guessing at it.
    assert "demand" in adjudicate.classify_cost.__doc__.lower()


def test_a_lever_named_as_its_own_word_still_resolves():
    """The guard must not be so tight that the real thing stops matching."""
    assert adjudicate.classify_cost(_req("rebuild in a separate arm"))["cost"] == "rebuild"
    assert adjudicate.classify_cost(_req("set operons off"))["cost"] == "rebuild"


def test_a_prose_word_ending_in_shift_is_not_a_refused_perturbation():
    """`refused_by_gate` was reached by a token heuristic that fired on any word ending in 'shift', so
    'Nutritional Downshift' in a sentence became a refused variant. A perturbation IDENTIFIER is snake_case;
    an English word is not, and the gate's authority is the envelope rather than a word shape."""
    out = adjudicate.classify_cost(_req("Nutritional Downshift A: glucose minimal medium shifted at 1800 s"))
    assert out["cost"] != "refused_by_gate", out
    still = adjudicate.classify_cost(_req("apply a generation_timed_knockout"))
    assert still["cost"] == "refused_by_gate"
