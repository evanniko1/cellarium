"""Extraction from an outside document, by TWO independent calculations that are then compared.

WHY TWO. This project has one reliable way of catching an extraction error, and it is not care: two
independent calculations of one quantity, compared. That is how the isoleucine contamination in the option-A
analysis surfaced — a hand-written script and Cellarium's own tool disagreed, and the script was wrong. The
methodological literature says the same thing about single extraction in blunter terms: error rates up to
50-63% in reviews of the practice, and single extraction producing about 22% more errors than double.

So extraction here is two paths that share no mechanism and barely share an input:

  * STRUCTURAL reads the declared tables. Measured on the development set, the plan tables are factorial
    design matrices: 33 tables, 277 data rows, 6-8 columns whose headers name our own factors ("ppGpp
    Module" 27 times, "Target Setpoint" 16, "Amino-Acid Mode" 16). A column is a factor and a cell is its
    level, so this path needs no vocabulary over prose at all.
  * LEXICAL reads the prose, and only the prose, for authority identifiers and declared quantities.

Where they agree, a record has two independent provenances. Where they disagree, that is the finding, and
it is reported rather than resolved by preferring one path.

THE MECHANICAL GATE. Every record must carry a quote that is a VERBATIM span of the source. That is rule R1
of the hypothesis hand-off made checkable, and it is what makes a language-model extraction path safe to add
later: an agent can propose fields, and a field it invented cannot survive the check.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import adjudicate, envelope, extraction  # noqa: E402

DOC = """# A proposal

## Factorial Simulation Matrix

| Run ID | Perturbation | ppGpp Module | Amino-Acid Mode | Target Setpoint | Primary Readouts |
| --- | --- | --- | --- | --- | --- |
| R1 | gene_knockout | on | enzyme-aware | 0.55 | growth rate, ppGpp |
| R2 | gene_knockout | off | medium-clamped | 0.85 | growth rate |

We will run these with the kinetic elongation model and set operons off for the second arm.

## Expected Outcomes

Growth rate falls by at least 20% in the argS knockout relative to wild type.

## Downstream Laboratory Validation

Stalling is monitored by ribosome profiling.
"""


# --- the mechanical gate: every field needs a verbatim span ------------------------------------------

def test_a_record_whose_quote_is_verbatim_is_kept():
    rec = extraction.Record(kind="requirement", role="factor:ppgpp_module", value="on",
                            quote="ppGpp Module", section="Factorial Simulation Matrix",
                            section_kind="plan", path="structural", start=0, end=0)
    out = extraction.verify_quotes([rec], DOC)
    assert out["n_kept"] == 1 and out["n_rejected"] == 0


def test_a_record_whose_quote_is_NOT_in_the_source_is_rejected_and_reported():
    """R1 made mechanical. This is the check that makes a language-model path safe to add: a field an agent
    invented has no verbatim span, so it cannot survive. A silently dropped record would be worse than a
    kept one — the count would look clean."""
    good = extraction.Record(kind="requirement", role="factor:ppgpp_module", value="on", quote="ppGpp Module",
                             section="s", section_kind="plan", path="agent", start=0, end=0)
    bad = extraction.Record(kind="requirement", role="factor:ppgpp_module", value="on",
                            quote="the ppGpp module was switched on throughout", section="s",
                            section_kind="plan", path="agent", start=0, end=0)
    out = extraction.verify_quotes([good, bad], DOC)
    assert out["n_kept"] == 1 and out["n_rejected"] == 1
    assert out["rejected"][0]["reason"] == "quote_not_in_source"
    assert out["rejected"][0]["quote"].startswith("the ppGpp module")
    assert out["about"] == "request"


def test_an_empty_quote_is_rejected_rather_than_trivially_verbatim():
    """"" is a substring of every document. A field with no quote is a field with no evidence."""
    rec = extraction.Record(kind="requirement", role="factor:medium", value="basal", quote="",
                            section="s", section_kind="plan", path="agent", start=0, end=0)
    out = extraction.verify_quotes([rec], DOC)
    assert out["n_rejected"] == 1 and out["rejected"][0]["reason"] == "quote_empty"


def test_verification_is_reported_even_when_everything_passes():
    out = extraction.verify_quotes([], DOC)
    assert out["n_kept"] == 0 and out["n_rejected"] == 0 and "note" in out


# --- path A: structural, from the declared tables ----------------------------------------------------

def test_the_structural_path_reads_a_column_as_a_factor_and_a_cell_as_its_level():
    recs = extraction.extract_structural(DOC)
    reqs = [r for r in recs if r.kind == "requirement"]
    pairs = {(r.role, r.value) for r in reqs}
    assert ("factor:ppgpp_module", "on") in pairs
    assert ("factor:ppgpp_module", "off") in pairs
    assert ("factor:aa_supply", "enzyme-aware") in pairs
    assert ("factor:target_charging", "0.55") in pairs
    assert ("factor:perturbation", "gene_knockout") in pairs
    assert all(r.path == "structural" for r in recs)


def test_the_structural_path_never_emits_a_HEADER_as_a_record():
    """The defect measured last turn: feeding plan sections to the cost classifier line by line put table
    HEADERS into the run and rebuild classes, because a column label is not a demand."""
    recs = extraction.extract_structural(DOC)
    assert not any(r.value.strip().lower() in ("ppgpp module", "perturbation", "target setpoint")
                   for r in recs)


def test_a_readout_column_yields_CLAIM_candidates_not_requirements():
    recs = extraction.extract_structural(DOC)
    claims = [r for r in recs if r.kind == "claim"]
    assert {r.value for r in claims} >= {"growth rate", "ppGpp"}
    assert all(r.role.startswith("readout") for r in claims)


def test_every_structural_record_quote_is_verbatim():
    recs = extraction.extract_structural(DOC)
    assert recs
    out = extraction.verify_quotes(recs, DOC)
    assert out["n_rejected"] == 0, out["rejected"]


def test_an_unrecognised_column_is_reported_rather_than_dropped():
    """A column whose header names no declared role is the structural path's own blind spot. Counting it
    keeps 'the table did not say' apart from 'we have no role for this header'."""
    doc = DOC.replace("| Primary Readouts |", "| Astrological Sign |")
    out = extraction.extract_report(doc)
    assert "Astrological Sign" in out["structural"]["unmapped_columns"]


def test_a_document_with_no_plan_table_yields_nothing_and_says_why():
    doc = "# T\n\n## Proposed Simulation Experiments\n\nRun the knockout at three seeds.\n"
    out = extraction.extract_report(doc)
    assert out["structural"]["n_records"] == 0
    assert "no declared table" in out["structural"]["note"].lower()


# --- path B: lexical, from the prose only ------------------------------------------------------------

def test_the_lexical_path_finds_identifiers_in_prose_and_quotes_the_sentence():
    recs = extraction.extract_lexical(DOC)
    vals = {(r.role, r.value) for r in recs if r.kind == "requirement"}
    # The SHARED role vocabulary, not a path-local one. The first run of this module had the two paths
    # using `factor:*` and `mode:*`/`lever:*` for the same facts, so they agreed on nothing at all and the
    # agreement statistic was structurally pinned to zero. The comparison is what found it.
    assert ("factor:elongation_model", "kinetic") in vals
    assert ("factor:operons", "operons") in vals
    for r in recs:
        assert r.quote and r.quote in DOC
        assert r.path == "lexical"


def test_the_lexical_path_reads_no_table_row():
    """Independence is the whole point: if this path also read the table, agreement between the two would
    measure nothing."""
    recs = extraction.extract_lexical(DOC)
    assert not any("| R1 |" in r.quote or "| R2 |" in r.quote for r in recs)


def test_the_lexical_path_ignores_a_wet_lab_section():
    recs = extraction.extract_lexical(DOC)
    assert not any(r.section_kind == "validation_wetlab" for r in recs)
    assert not any("ribosome profiling" in r.value for r in recs if r.kind == "requirement")


def test_the_lexical_path_finds_a_claim_with_its_quantity_and_threshold():
    claims = [r for r in extraction.extract_lexical(DOC) if r.kind == "claim"]
    growth = next(c for c in claims if c.role == "readout:growth_rate")
    assert "20%" in growth.quote and growth.section == "Expected Outcomes"


# --- reconciliation: the comparison, not a winner ----------------------------------------------------

def test_records_the_two_paths_agree_on_carry_both_provenances():
    """Agreement has to be POSSIBLE before it can be informative. Both paths must use one role vocabulary,
    and each agreed record must carry a quote from each path -- two provenances for one fact, found two
    ways. In this document the agreed record is the growth-rate readout: the structural path reads it from
    a `Primary Readouts` cell, the lexical path from the Expected Outcomes sentence."""
    out = extraction.extract_report(DOC)
    agreed = out["reconciled"]["agreed"]
    assert agreed, "the two paths must be able to agree on something in this document"
    assert ("claim", "readout:growth_rate") in {(r["kind"], r["role"]) for r in agreed}
    for r in agreed:
        assert set(r["paths"]) == {"structural", "lexical"}
        assert len(r["quotes"]) == 2, r          # a different span from each path, not the same line twice


def test_disagreements_are_reported_per_path_and_never_resolved_by_preference():
    out = extraction.extract_report(DOC)
    rec = out["reconciled"]
    assert rec["structural_only"] and rec["lexical_only"]
    # Nothing in the output ranks the paths, because neither is the reference standard.
    assert "preferred_path" not in rec
    assert "agreement" in rec and 0.0 <= rec["agreement"]["jaccard"] <= 1.0


def test_two_paths_that_agree_on_NOTHING_report_zero_rather_than_a_clean_empty():
    """Forced. An agreement statistic that reads 'clean' when the sets are disjoint is the empty-success
    shape: the number that matters is zero and the result must say zero."""
    a = [extraction.Record(kind="requirement", role="factor:medium", value="basal", quote="basal",
                           section="s", section_kind="plan", path="structural", start=0, end=0)]
    b = [extraction.Record(kind="requirement", role="factor:medium", value="acetate", quote="acetate",
                           section="s", section_kind="plan", path="lexical", start=0, end=0)]
    rec = extraction.reconcile(a, b)
    assert rec["agreement"]["jaccard"] == 0.0
    assert rec["agreement"]["n_agreed"] == 0
    assert len(rec["structural_only"]) == 1 and len(rec["lexical_only"]) == 1
    assert "zero" in rec["note"].lower() or "no record" in rec["note"].lower()


def test_cohens_kappa_is_explicitly_not_reported_and_the_reason_is_given():
    """Kappa needs two raters labelling ONE item set. These paths each discover their own items, so there
    is no shared denominator and a kappa computed over the union would be a number with no meaning."""
    out = extraction.extract_report(DOC)
    assert "kappa" not in out["reconciled"]["agreement"]
    assert "kappa" in out["reconciled"]["agreement"]["not_reported"].lower()


def test_no_field_is_called_accuracy_and_the_note_says_why():
    """Neither path is a reference standard, so nothing here may be reported as accuracy. The word appears
    in the note ONLY to deny it -- which is why this checks the field NAMES rather than the text, as the
    first version of this test did and contradicted itself."""
    out = extraction.extract_report(DOC)
    assert "accuracy" not in out["reconciled"]["agreement"]
    assert not any("accuracy" in k for k in out["reconciled"])
    assert "agreement is not accuracy" in out["reconciled"]["note"].lower()


# --- the agent seam, declared and gated --------------------------------------------------------------

def test_the_agent_path_contract_is_declared_and_now_implemented():
    """The contract was written BEFORE the path existed -- quote-backed fields only, temperature 0, the
    mechanical verifier as the gate -- which is why it could be used to build it rather than written to
    describe what got built. `implemented` flipping is the only line of it that changed."""
    c = extraction.AGENT_PATH_CONTRACT
    assert c["implemented"] is True
    assert c["temperature"] == 0.0
    assert "verify_quotes" in c["gate"]
    for key in ("may_not", "must"):
        assert c[key]


def test_an_agent_record_is_held_to_the_same_gate_as_any_other():
    out = extraction.extract_report(DOC, agent_records=[
        extraction.Record(kind="requirement", role="factor:ppgpp_module", value="on",
                          quote="ppGpp Module", section="s", section_kind="plan", path="agent",
                          start=0, end=0),
        extraction.Record(kind="requirement", role="factor:medium", value="rich_EZ_aa",
                          quote="we will use a rich defined medium", section="s", section_kind="plan",
                          path="agent", start=0, end=0),
    ])
    assert out["agent"]["n_kept"] == 1 and out["agent"]["n_rejected"] == 1
    assert out["agent"]["rejected"][0]["reason"] == "quote_not_in_source"


def test_extract_report_refuses_bad_input():
    for bad in (None, "", 3):
        out = extraction.extract_report(bad)
        assert "error" in out and out["about"] == "request", bad


# --- feeding the later stages ------------------------------------------------------------------------

def test_a_requirement_record_classifies_through_stage_4():
    recs = extraction.extract_structural(DOC)
    req = next(r for r in recs if r.role == "factor:perturbation")
    out = adjudicate.classify_cost(extraction.as_requirement(req))
    assert out["cost"] == "run" and "LAUNCHED_VARIANT_MODULES" in out["authority"]


def test_a_target_charging_requirement_classifies_as_a_rebuild():
    recs = extraction.extract_structural(DOC)
    req = next(r for r in recs if r.role == "factor:target_charging")
    out = adjudicate.classify_cost(extraction.as_requirement(req))
    assert out["cost"] == "rebuild" and "REFIT_FACTORS" in out["authority"]


@pytest.mark.parametrize("role,channel", [("readout:growth_rate", "growth_rate")])
def test_a_claim_record_carries_a_resolved_channel(role, channel):
    recs = extraction.extract_lexical(DOC)
    c = next(r for r in recs if r.role == role)
    assert adjudicate.resolve_quantity(c.value)["channel"] == channel


# --- the role vocabulary must stay live --------------------------------------------------------------

def test_every_role_identifier_is_still_recognised_by_some_authority():
    """`ROLE_IDENTIFIERS` exists because a role name handed to the cost classifier as prose resolves to
    nothing: `factor:target_charging 0.55` matched no declared lever, so a demand for a ParCa rebuild read
    as `unresolved` and cost nothing. Measured on this module's first run.

    An identifier that stops being recognised upstream would silently restore that bug, so each one is
    checked against the authorities rather than assumed."""
    from cellarium import capability, doe
    known = (set(doe.REFIT_FACTORS) | set(capability.LAUNCHED_VARIANT_MODULES)
             | set(capability.ELONGATION_MODES))
    for role, ident in extraction.ROLE_IDENTIFIERS.items():
        if not ident:
            continue
        assert ident in known, f"{role} -> {ident!r} is recognised by no authority any more"


def test_both_paths_draw_their_roles_from_one_namespace():
    """The structural path's roles come from COLUMN_ROLES; the lexical path's from the mode list and
    REFIT_LEVER_ROLES. Those must be ONE namespace, or agreement is pinned to zero however good either
    path is."""
    structural_roles = set(extraction.COLUMN_ROLES)
    lexical_roles = set(extraction.REFIT_LEVER_ROLES.values()) | {"factor:elongation_model"}
    shared_prefixes = {r.split(":")[0] for r in structural_roles} & {r.split(":")[0] for r in lexical_roles}
    assert "factor" in shared_prefixes
    # Every lexical role either exists in COLUMN_ROLES or is declared in ROLE_IDENTIFIERS, so no path can
    # invent a role the other could never produce.
    for r in lexical_roles:
        assert r in structural_roles or r in extraction.ROLE_IDENTIFIERS, r


def test_a_readout_cell_the_registry_has_no_words_for_keeps_a_bare_role():
    """Not dropped. A readout nobody mapped is a gap in the vocabulary, not a readout the document omitted
    -- the same three-valued distinction stage 1 makes, carried into the extractor."""
    doc = DOC.replace("| growth rate, ppGpp |", "| flagellar torque |")
    claims = [r for r in extraction.extract_structural(doc) if r.kind == "claim"]
    bare = [c for c in claims if c.role == "readout"]
    assert bare and bare[0].value == "flagellar torque"


# --- redundant or merely complementary? the distinction the measurement forced ------------------------
#
# Measured over the 33 development reports: 2,018 structural records, 8,654 lexical, SEVEN agreed, mean
# per-report Jaccard 0.004, and 30 of 33 reports agreeing on nothing at all.
#
# Read naively that says the two paths disagree violently. It says nothing of the kind. The structural path
# finds FACTORS, because factors live in table cells (perturbation 71, medium 67, elongation model 47,
# target charging 41); the lexical path finds READOUTS, because readouts are named in prose
# (fraction_trna_charged 114, ppgpp_conc 78, ribosome_conc 74). Their role sets are nearly disjoint, so
# agreement was close to impossible before either path read a word.
#
# That matters because dual extraction's whole value is REDUNDANCY on one quantity -- two calculations of
# the same thing, compared. Two paths looking at different things cannot check each other, however many
# records each produces. Conflating "we looked at different things" with "we disagree" would be a confident
# wrong reading of our own instrument, so `reconcile` now has to say which situation it is in.

def test_reconcile_says_whether_agreement_was_even_possible():
    """Disjoint role sets mean a near-zero agreement carries NO information about correctness. The verdict
    must distinguish that from two paths that covered the same ground and differed."""
    factors = [extraction.Record(kind="requirement", role="factor:medium", value="basal", quote="basal",
                                 section="s", section_kind="plan", path="structural", start=0, end=0)]
    readouts = [extraction.Record(kind="claim", role="readout:growth_rate", value="growth rate",
                                  quote="growth rate", section="s", section_kind="claim",
                                  path="lexical", start=0, end=0)]
    rc = extraction.reconcile(factors, readouts)
    assert rc["agreement"]["comparison_kind"] == "complementary"
    assert rc["agreement"]["role_overlap"] == 0.0
    assert rc["agreement"]["jaccard"] == 0.0
    assert "complementary" in rc["note"].lower()
    assert "cannot check" in rc["note"].lower() or "checks nothing" in rc["note"].lower()


def test_overlapping_roles_make_the_comparison_redundant_and_so_informative():
    same = dict(role="factor:medium", kind="requirement", section="s", section_kind="plan")
    a = [extraction.Record(value="basal", quote="basal", path="structural", start=0, end=0, **same),
         extraction.Record(value="acetate", quote="acetate", path="structural", start=0, end=0, **same)]
    b = [extraction.Record(value="basal", quote="basal medium", path="lexical", start=0, end=0, **same)]
    rc = extraction.reconcile(a, b)
    assert rc["agreement"]["comparison_kind"] == "redundant"
    assert rc["agreement"]["role_overlap"] == 1.0
    assert rc["agreement"]["n_agreed"] == 1
    # Here a disagreement IS a finding: the structural path saw a level the prose never restated.
    assert len(rc["structural_only"]) == 1


def test_a_partially_overlapping_comparison_is_named_rather_than_forced_into_one_box():
    a = [extraction.Record(kind="requirement", role="factor:medium", value="basal", quote="basal",
                           section="s", section_kind="plan", path="structural", start=0, end=0),
         extraction.Record(kind="requirement", role="factor:shift", value="none", quote="none",
                           section="s", section_kind="plan", path="structural", start=0, end=0)]
    b = [extraction.Record(kind="requirement", role="factor:medium", value="basal", quote="basal",
                           section="s", section_kind="plan", path="lexical", start=0, end=0),
         extraction.Record(kind="claim", role="readout:growth_rate", value="growth rate",
                           quote="growth rate", section="s", section_kind="claim", path="lexical",
                           start=0, end=0)]
    rc = extraction.reconcile(a, b)
    assert rc["agreement"]["comparison_kind"] == "partial"
    assert 0.0 < rc["agreement"]["role_overlap"] < 1.0


def test_the_real_document_comparison_is_reported_as_what_it_is():
    """The fixture mirrors the archive: factors in a table, readouts in prose. The agreement that exists is
    on the readout both paths happen to cover, and the verdict must not present the rest as disagreement."""
    rc = extraction.extract_report(DOC)["reconciled"]
    assert rc["agreement"]["comparison_kind"] in ("partial", "complementary")
    assert rc["agreement"]["role_overlap"] < 1.0


# =====================================================================================================
# DEDUPE and VALUE NORMALISATION -- the two gaps the dev-set measurement named with numbers.
#
# DEDUPE. 342 `rebuild` records came out of ~277 table rows carrying a setpoint cell each, when the
# archive asks for FOUR distinct setpoints (0.85 x182, 0.70 x104, 0.55 x44, 0.75 x6). Counting cells
# counts rows; counting arm decisions means counting DISTINCT demands. Both numbers are real and they
# answer different questions, so dedupe must collapse the demands WITHOUT losing the row count -- a plan
# asking for 277 simulations still asks for 277 simulations.
#
# NORMALISATION. 79.8% of structural requirements were `unresolved` at stage 4 because cell values are
# prose. Measured, the real values are: perturbation "*argA* switch-off" x112; ppGpp module "ON" x248,
# "OFF (Fixed)" x32; aa supply "Endogenous Biosynthesis" x50, "OFF (Clamped)" x16; medium "Glucose
# minimal" x176, "M9 Glucose (Aerobic)" x26.
#
# The constraint that keeps normalisation honest: it may only produce a value some AUTHORITY recognises.
# Mapping "Glucose + 20 AAs" to an invented medium name would be worse than leaving it raw, because a
# media name goes to the simulator verbatim and an invented one kills the run at the shift.
# =====================================================================================================

def test_normalisation_declares_its_basis_and_keeps_the_raw_value():
    out = extraction.normalise_value("factor:ppgpp_module", "OFF (Fixed)")
    assert out["value"] == "off" and out["raw"] == "OFF (Fixed)"
    assert out["basis"] == "declared_synonym"


@pytest.mark.parametrize("role,raw,value", [
    ("factor:ppgpp_module", "ON", "on"),
    ("factor:ppgpp_module", "OFF", "off"),
    ("factor:ppgpp_module", "OFF (Fixed)", "off"),
    ("factor:aa_supply", "Endogenous Biosynthesis", "enzymes"),
    ("factor:aa_supply", "Endogenous ON", "enzymes"),
    ("factor:aa_supply", "OFF (Clamped)", "medium"),
    ("factor:aa_supply", "Medium-Clamped", "medium"),
    ("factor:aa_supply", "Clamped 20 AA", "medium"),
])
def test_the_real_archive_values_normalise(role, raw, value):
    assert extraction.normalise_value(role, raw)["value"] == value


@pytest.mark.parametrize("raw,medium", [
    ("Glucose minimal", "minimal"),
    ("M9 Glucose (Aerobic)", "minimal"),
    ("M9 Glucose", "minimal"),
    ("Acetate minimal", "minimal_acetate"),
    ("Succinate minimal", "minimal_succinate"),
    ("Glucose + 20 AAs", "minimal_plus_amino_acids"),
    ("Glucose (anaerobic)", "minimal_minus_oxygen"),
])
def test_a_medium_normalises_only_into_media_the_model_actually_has(raw, medium):
    out = extraction.normalise_value("factor:medium", raw)
    assert out["value"] == medium
    assert medium in envelope.media_with_a_doubling_time()


def test_a_medium_that_would_normalise_to_something_the_model_lacks_stays_RAW():
    """The load-bearing constraint. A media name goes to the simulator verbatim and is looked up by name,
    so an invented one is not a weaker experiment -- it is a run that dies at the shift and leaves a
    truncated directory that looks like data. Normalisation must never be the thing that invents one."""
    out = extraction.normalise_value("factor:medium", "rich EZ defined medium")
    assert out["basis"] == "unnormalised" and out["value"] == "rich EZ defined medium"


def test_a_perturbation_switch_off_normalises_to_a_knockout_and_names_the_gene():
    out = extraction.normalise_value("factor:perturbation", "*argA* switch-off")
    assert out["value"] == "gene_knockout" and out["gene"] == "argA"
    assert out["value"] in envelope.VALIDATED_PERTURBATIONS


def test_a_GENERATION_TIMED_switch_off_is_normalised_to_the_thing_we_cannot_run():
    """Measured earlier: 7 of 45 reports ask for a switch-off at a chosen generation, and no variant module
    does that. Normalising it to a plain knockout would hide the one demand we must refuse."""
    out = extraction.normalise_value("factor:perturbation", "gen-1 *alaS* switch-off")
    assert out["value"] == "generation_timed_knockout" and out["gene"] == "alaS"
    assert out["value"] not in envelope.VALIDATED_PERTURBATIONS
    cost = adjudicate.classify_cost(adjudicate.Requirement(
        text=out["value"], quote="gen-1 *alaS* switch-off", section="s", section_kind="plan"))
    assert cost["cost"] == "refused_by_gate"


def test_a_numeric_setpoint_keeps_its_number():
    for raw, val in (("0.85", "0.85"), ("0.55", "0.55"), ("0.70", "0.70")):
        out = extraction.normalise_value("factor:target_charging", raw)
        assert out["value"] == val and out["basis"] == "numeric"


def test_a_cell_naming_TWO_levels_is_flagged_rather_than_collapsed_to_one():
    """A cell reading "ON vs OFF" or "0.55 vs 0.85" appears in the archive. It is a factor crossed inside
    one row; picking the first level would silently halve the design."""
    for role, raw in (("factor:ppgpp_module", "ON vs OFF"), ("factor:target_charging", "0.55 vs 0.85")):
        out = extraction.normalise_value(role, raw)
        assert out["basis"] == "multi_level", (role, raw, out)
        assert len(out["levels"]) == 2
        assert out["value"] == raw            # kept raw, because it is not ONE level


def test_the_simulation_module_column_cells_do_not_pretend_to_be_elongation_models():
    """Measured: that column's cells are "Configuration", "Config 1", "Designation", "(Wild-Type)" -- 52
    cells of config labels. The authority constraint drops them, and the drop is the right answer: the
    column names configurations, not modes."""
    for raw in ("Configuration", "Config 1", "Designation", "(Wild-Type)"):
        out = extraction.normalise_value("factor:elongation_model", raw)
        assert out["basis"] == "unnormalised", raw
    got = extraction.normalise_value("factor:elongation_model", "kinetic (Choi & Covert)")
    assert got["value"] == "kinetic"


def test_normalisation_is_reported_per_role_so_a_blind_spot_is_countable():
    rep = extraction.normalisation_coverage([
        extraction.Record(kind="requirement", role="factor:medium", value="Glucose minimal", quote="x",
                          section="s", section_kind="plan", path="structural", start=0, end=0),
        extraction.Record(kind="requirement", role="factor:medium", value="rich EZ medium", quote="x",
                          section="s", section_kind="plan", path="structural", start=0, end=0),
    ])
    assert rep["by_role"]["factor:medium"]["normalised"] == 1
    assert rep["by_role"]["factor:medium"]["unnormalised"] == 1
    assert "rich EZ medium" in rep["by_role"]["factor:medium"]["unnormalised_values"]


# --- dedupe -------------------------------------------------------------------------------------------

def test_dedupe_collapses_repeated_demands_and_counts_the_occurrences():
    recs = [extraction.Record(kind="requirement", role="factor:target_charging", value="0.85",
                              quote=f"row {i}", section="Matrix", section_kind="plan",
                              path="structural", start=i, end=i + 4) for i in range(5)]
    recs.append(extraction.Record(kind="requirement", role="factor:target_charging", value="0.55",
                                  quote="row 6", section="Matrix", section_kind="plan",
                                  path="structural", start=9, end=13))
    out = extraction.dedupe(recs)
    assert out["n_raw"] == 6 and out["n_distinct"] == 2
    by_value = {r["value"]: r for r in out["distinct"]}
    assert by_value["0.85"]["n_occurrences"] == 5
    assert len(by_value["0.85"]["quotes"]) == 5          # every provenance kept, not just the first


def test_dedupe_does_not_lose_the_row_count():
    """Both numbers are real and answer different questions: four distinct setpoints is four arm decisions;
    277 rows is 277 simulations. A dedupe that destroyed the second would make a plan look cheap."""
    out = extraction.extract_report(DOC)
    assert out["structural"]["n_design_rows"] == 2          # the fixture table has two data rows
    assert out["structural"]["n_distinct"] <= out["structural"]["n_records"]


def test_dedupe_is_per_document_and_says_so():
    out = extraction.dedupe([])
    assert out["n_raw"] == 0 and out["n_distinct"] == 0 and "note" in out
    assert "document" in out["note"].lower()


def test_the_cost_summary_over_DISTINCT_demands_differs_from_the_raw_one():
    """The number that was wrong. 342 rebuild records were ~277 rows x one setpoint cell; the demand is
    four setpoints. Both are reported, labelled, and never swapped."""
    recs = [extraction.Record(kind="requirement", role="factor:target_charging", value="0.85",
                              quote=f"r{i}", section="M", section_kind="plan", path="structural",
                              start=i, end=i + 1) for i in range(10)]
    raw = adjudicate.cost_summary([extraction.as_requirement(r) for r in recs])
    distinct = adjudicate.cost_summary(extraction.as_requirements_distinct(recs))
    assert raw["by_cost"]["rebuild"] == 10
    assert distinct["by_cost"]["rebuild"] == 1


# --- normalisation reaches stage 4 --------------------------------------------------------------------

def test_a_normalised_perturbation_cell_now_costs_as_a_run():
    """The 79.8%-unresolved finding, closed for this role: the cell says "*argA* switch-off", the authority
    knows `gene_knockout`, and the translation is declared rather than guessed at the call site."""
    rec = extraction.Record(kind="requirement", role="factor:perturbation", value="*argA* switch-off",
                            quote="*argA* switch-off", section="M", section_kind="plan",
                            path="structural", start=0, end=0)
    out = adjudicate.classify_cost(extraction.as_requirement(rec))
    assert out["cost"] == "run" and "LAUNCHED_VARIANT_MODULES" in out["authority"]


def test_an_unnormalised_value_still_reaches_stage_4_as_unresolved_not_as_free():
    rec = extraction.Record(kind="requirement", role="factor:medium", value="rich EZ medium",
                            quote="rich EZ medium", section="M", section_kind="plan",
                            path="structural", start=0, end=0)
    out = adjudicate.classify_cost(extraction.as_requirement(rec))
    assert out["cost"] == "unresolved"


def test_a_row_dependent_factor_is_declared_as_such():
    """`ppGpp module = on` costs nothing under steady_state (it is the default) and a drafted patch under
    kinetic. The cost depends on another cell in the SAME ROW, so a per-cell verdict cannot be given -- and
    declaring that is different from a silent `unresolved`."""
    assert "factor:ppgpp_module" in extraction.ROW_DEPENDENT_ROLES
    assert "factor:aa_supply" in extraction.ROW_DEPENDENT_ROLES
    why = extraction.ROW_DEPENDENT_ROLES["factor:ppgpp_module"]
    assert "elongation" in why.lower() and "row" in why.lower()
    rec = extraction.Record(kind="requirement", role="factor:ppgpp_module", value="ON",
                            quote="ON", section="M", section_kind="plan", path="structural",
                            start=0, end=0)
    out = adjudicate.classify_cost(extraction.as_requirement(rec))
    assert out["cost"] == "unresolved"
    assert extraction.as_requirement(rec).text.startswith("factor:ppgpp_module")


# --- why an `unresolved` is unresolved ----------------------------------------------------------------
#
# Decomposed over the development set, 210 distinct demands read `unresolved`, which as one number looks
# like a 69% blind spot. It is not: 68 are row-dependent (the classifier being RIGHT), 67 are media that
# cost nothing as a cell, 47 are configuration labels the authority constraint rightly refused, and only 28
# are a gap in the declared tables. `classify_cost` is correct to say `unresolved` for all four; what was
# missing was any way to tell them apart without knowing to consult ROW_DEPENDENT_ROLES by hand.

def _rec(role, value):
    return extraction.Record(kind="requirement", role=role, value=value, quote=value, section="M",
                             section_kind="plan", path="structural", start=0, end=0)


def test_a_row_dependent_unresolved_says_so_and_names_the_deciding_factor():
    out = extraction.cost_of(_rec("factor:ppgpp_module", "ON"))
    assert out["cost"] == "unresolved" and out["row_dependent"] is True
    assert out["unresolved_because"] == "row_dependent"
    assert "elongation model" in out["note"] and "not a gap" in out["note"].lower()


def test_an_unnormalised_value_is_reported_as_a_CLOSEABLE_gap():
    out = extraction.cost_of(_rec("factor:elongation_model", "Config 3"))
    assert out["unresolved_because"] == "value_not_normalised"
    assert "closeable" in out["note"].lower()
    assert out["row_dependent"] is False


def test_a_normalised_but_non_cost_bearing_cell_is_distinguished_from_a_gap():
    """A medium normalises perfectly and still costs nothing on its own, because it is part of a design
    rather than a demand on the model. Filing that beside a genuine table gap would overstate the gap."""
    out = extraction.cost_of(_rec("factor:medium", "Glucose minimal"))
    assert out["unresolved_because"] == "cell_is_not_cost_bearing"
    assert "design" in out["note"].lower()


def test_a_resolved_cost_is_untouched_by_the_wrapper():
    out = extraction.cost_of(_rec("factor:perturbation", "*argA* switch-off"))
    assert out["cost"] == "run" and "unresolved_because" not in out


def test_the_breakdown_splits_unresolved_and_keeps_every_class():
    recs = [_rec("factor:ppgpp_module", "ON"), _rec("factor:medium", "Glucose minimal"),
            _rec("factor:elongation_model", "Config 1"), _rec("factor:perturbation", "*argA* switch-off"),
            _rec("factor:target_charging", "0.55")]
    out = extraction.cost_breakdown(recs)
    assert set(out["by_cost"]) == set(adjudicate.COST_CLASSES)
    assert out["by_cost"]["run"] == 1 and out["by_cost"]["rebuild"] == 1
    assert out["by_cost"]["unresolved"] == 3
    assert out["unresolved_because"] == {"row_dependent": 1, "value_not_normalised": 1,
                                         "cell_is_not_cost_bearing": 1}
    assert out["n_distinct"] == 5


# =====================================================================================================
# COSTING A DESIGN ROW -- the combination, which is what prices the cells a cell cannot price.
#
# Decomposed last turn, 68 of 210 unresolved distinct demands were ROW-DEPENDENT: `ppGpp module = on`
# costs nothing under the steady-state model, where it is the default, and is the drafted patch EXT-PORT-P
# under kinetic. The deciding fact is another cell in the same row, so no per-cell verdict exists.
#
# A row is one simulation, and its cost is NOT a single class. It is a set of PREREQUISITES plus one
# blocking verdict, because the prerequisites co-occur: a row can need a parameter rebuild AND a code patch
# AND still be refused by the feasibility gate. Collapsing that to a maximum would answer a question nobody
# asked. What an operator needs is "can I queue this today, and if not, what has to happen first".
#
# And the mode is frequently UNSTATED, because the column that looked like it named elongation models turned
# out to hold configuration labels. An unstated mode makes the module costs undecidable -- which is the
# cell-level row-dependence reappearing at row level, and the honest answer is to say so rather than to
# default to steady_state.
# =====================================================================================================

def test_the_default_steady_state_row_is_runnable_today():
    """`run` IS a prerequisite, and an empty list would be the wrong answer: queuing a simulation is the
    work. `runnable_today` is what says the work needs nothing to happen first -- true exactly when the
    only prerequisite is `run`."""
    out = extraction.cost_row({"factor:elongation_model": "steady_state",
                               "factor:ppgpp_module": "ON",
                               "factor:aa_supply": "Endogenous Biosynthesis",
                               "factor:perturbation": "*argA* switch-off",
                               "factor:medium": "Glucose minimal"})
    assert out["runnable_today"] is True
    assert out["prerequisites"] == ["run"] and out["blocked"] is False
    assert out["patches"] == [] and out["flags"] == []


def test_a_kinetic_row_with_ppgpp_on_needs_the_drafted_ppgpp_patch():
    out = extraction.cost_row({"factor:elongation_model": "kinetic", "factor:ppgpp_module": "ON",
                               "factor:aa_supply": "OFF (Clamped)"})
    assert "patch_then_run" in out["prerequisites"]
    assert out["patches"] == ["EXT-PORT-P"]
    assert out["runnable_today"] is False


def test_a_kinetic_row_with_enzyme_supply_needs_the_drafted_supply_patch():
    out = extraction.cost_row({"factor:elongation_model": "kinetic", "factor:ppgpp_module": "OFF",
                               "factor:aa_supply": "Endogenous ON"})
    assert out["patches"] == ["EXT-PORT-A"]


def test_a_kinetic_row_needing_BOTH_patches_is_named_as_the_combined_arm():
    """Both patches at once is the hybrid, and it already has a name. Reporting two patch ids without the
    arm would leave a reader to rediscover that KINAP is what this row is."""
    out = extraction.cost_row({"factor:elongation_model": "kinetic", "factor:ppgpp_module": "ON",
                               "factor:aa_supply": "Endogenous Biosynthesis"})
    assert out["patches"] == ["EXT-PORT-A", "EXT-PORT-P"]
    assert out["combined_arm"]["arm"] == "KINAP"
    assert out["combined_arm"]["applied"] is False


def test_the_published_kinetic_row_needs_only_flags_not_patches():
    """Kinetic with both modules off is the model as published: a flag, nothing to patch."""
    out = extraction.cost_row({"factor:elongation_model": "kinetic", "factor:ppgpp_module": "OFF (Fixed)",
                               "factor:aa_supply": "Medium-Clamped"})
    assert out["patches"] == []
    assert out["prerequisites"] == ["flag"]
    assert any("--kinetic-trna-charging" in f for f in out["flags"])


def test_a_steady_state_row_with_a_module_off_is_a_flag_and_the_flag_is_named():
    out = extraction.cost_row({"factor:elongation_model": "steady_state",
                               "factor:ppgpp_module": "OFF (Fixed)"})
    assert out["prerequisites"] == ["flag"]
    assert "--no-ppgpp-regulation" in out["flags"]


def test_an_UNSTATED_mode_makes_the_module_costs_undecidable_rather_than_defaulted():
    """The honest core of row costing. The column that looked like it named elongation models holds
    configuration labels, so most archive rows never state the mode -- and defaulting to steady_state would
    silently price a kinetic row as free."""
    out = extraction.cost_row({"factor:ppgpp_module": "ON", "factor:aa_supply": "Endogenous ON"})
    assert out["mode_unstated"] is True
    assert out["runnable_today"] is False
    assert "undecidable" in out["prerequisites"]
    assert out["patches"] == []
    assert "elongation model" in out["note"] and "not assumed" in out["note"].lower()


def test_a_setpoint_puts_the_row_in_its_own_arm_and_that_is_a_rebuild():
    out = extraction.cost_row({"factor:elongation_model": "steady_state",
                               "factor:target_charging": "0.70"})
    assert "rebuild" in out["prerequisites"]
    assert out["arm"]["charged_fraction_target"] == "0.70"
    assert out["arm"]["elongation_model"] == "steady_state"


def test_a_generation_timed_switch_off_BLOCKS_the_row():
    """A blocker is not a prerequisite. No ordering of work makes this row runnable, because no variant
    module performs a switch-off at a chosen generation."""
    out = extraction.cost_row({"factor:elongation_model": "steady_state",
                               "factor:perturbation": "gen-1 *alaS* switch-off"})
    assert out["blocked"] is True and out["runnable_today"] is False
    assert out["blockers"][0]["role"] == "factor:perturbation"
    assert "generation_timed_knockout" in out["blockers"][0]["value"]


def test_prerequisites_CO_OCCUR_and_are_not_collapsed_to_a_worst_case():
    """A row can need a new knowledge base AND a code patch. Reporting the maximum of a declared ordering
    would answer a question nobody asked: the operator needs the whole list of what must happen first."""
    out = extraction.cost_row({"factor:elongation_model": "kinetic", "factor:ppgpp_module": "ON",
                               "factor:aa_supply": "Endogenous ON",
                               "factor:target_charging": "0.55",
                               "factor:perturbation": "*argS* switch-off"})
    assert set(out["prerequisites"]) == {"rebuild", "patch_then_run", "flag", "run"}
    assert out["patches"] == ["EXT-PORT-A", "EXT-PORT-P"]
    assert out["blocked"] is False and out["runnable_today"] is False


def test_every_cell_verdict_is_kept_beside_the_row_verdict():
    out = extraction.cost_row({"factor:elongation_model": "kinetic", "factor:ppgpp_module": "ON"})
    assert out["per_cell"]["factor:ppgpp_module"]["prerequisite"] == "patch_then_run"
    assert out["per_cell"]["factor:elongation_model"]["prerequisite"] == "flag"
    assert out["cells_normalised"]["factor:ppgpp_module"] == "on"


def test_an_empty_row_is_an_argument_error_not_a_free_row():
    for bad in ({}, None, "rows"):
        out = extraction.cost_row(bad)
        assert "error" in out and out["about"] == "request", bad


def test_a_multi_level_cell_refuses_to_cost_the_row():
    """"ON vs OFF" in one cell is two rows, not one. Costing it as a single row would price half the design
    the author asked for."""
    out = extraction.cost_row({"factor:elongation_model": "kinetic", "factor:ppgpp_module": "ON vs OFF"})
    assert "undecidable" in out["prerequisites"]
    assert out["multi_level_cells"] == ["factor:ppgpp_module"]


# --- rows out of a real document ----------------------------------------------------------------------

def test_design_rows_come_out_of_the_declared_table_with_their_cells_grouped():
    rows = extraction.extract_design_rows(DOC)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["cells"]["factor:ppgpp_module"] == "on"
    assert r0["cells_raw"]["factor:ppgpp_module"] == "on"
    assert r0["section"] == "Factorial Simulation Matrix" and r0["row_index"] == 0
    assert r0["quote"].startswith("|") and r0["quote"] in DOC


def test_a_row_costing_runs_end_to_end_from_a_document():
    out = extraction.row_cost_summary(DOC)
    assert out["n_rows"] == 2
    assert set(out["by_prerequisite"]) >= {"rebuild", "patch_then_run", "flag", "run", "undecidable"}
    assert out["n_blocked"] == 0
    assert out["n_runnable_today"] + out["n_not_runnable_today"] == 2


def test_the_row_summary_reports_how_often_the_MODE_was_stated():
    """The number that decides whether row costing can work at all on this archive."""
    out = extraction.row_cost_summary(DOC)
    assert "n_mode_unstated" in out
    assert out["n_mode_unstated"] + out["n_mode_stated"] == out["n_rows"]


# --- the false block, found by costing rows over the development set ----------------------------------
#
# 96 of 394 development rows came back BLOCKED, and 28 of those were cells naming gene symbols with no
# verb -- "`argS`, `hisS`", "`alaS`", "`alaS`, `argS`, `hisS`, `gltX`". They did not match any synonym, so
# they stayed raw, and a raw value is not a validated perturbation, so the row was reported as refused by
# the feasibility gate.
#
# That is the WORST direction to be wrong in. An undecidable row says "I cannot price this"; a blocked row
# says "no ordering of work makes this runnable", and these are ordinary knockouts -- `gene_knockout` for
# one gene and `multi_gene_knockout` for several, both validated. A false block would tell a collaborator
# to drop 28 rows of their own plan.
#
# A bare gene symbol in a column whose ROLE is the perturbation target is a knockout of that gene; that is
# the column's own meaning, and reading it so is declared here rather than inferred at a call site.

def test_a_single_bare_gene_in_a_perturbation_cell_is_a_knockout():
    out = extraction.normalise_value("factor:perturbation", "`alaS`")
    assert out["value"] == "gene_knockout" and out["gene"] == "alaS"
    assert out["basis"] == "declared_synonym"


def test_several_bare_genes_are_a_MULTI_gene_knockout_and_all_are_kept():
    out = extraction.normalise_value("factor:perturbation", "`alaS`, `argS`, `hisS`, `gltX`")
    assert out["value"] == "multi_gene_knockout"
    assert out["genes"] == ["alaS", "argS", "hisS", "gltX"]
    assert out["value"] in envelope.VALIDATED_PERTURBATIONS


def test_such_a_row_is_runnable_rather_than_blocked():
    """The whole point. A false block tells a collaborator to drop a row that runs."""
    out = extraction.cost_row({"factor:perturbation": "`argS`, `hisS`"})
    assert out["blocked"] is False
    assert "run" in out["prerequisites"]


def test_the_generation_timed_case_is_still_blocked():
    """The fix must not swallow the real refusal: a switch-off at a chosen generation has no variant."""
    out = extraction.cost_row({"factor:perturbation": "gen-1 *alaS* switch-off"})
    assert out["blocked"] is True


def test_a_cell_naming_no_gene_and_no_variant_is_undecidable_not_blocked():
    """Between a knockout and a refusal there is a third state: a cell this module cannot read. It must
    not be reported as either."""
    out = extraction.cost_row({"factor:perturbation": "a more aggressive depletion regime"})
    assert out["blocked"] is False
    assert "undecidable" in out["prerequisites"]


# =====================================================================================================
# THE AGENT PATH, built to the contract that was written before it.
#
# Its job is STRUCTURE, not a second opinion. Measured: the lexical path found 8,654 readout mentions over
# the development set and bound NONE of them to a target/reference pair -- recall without structure, which
# is what a language model does well and a pattern cannot. It is not a second opinion because the two
# mechanical paths already showed what a complementary second path buys (role overlap ~0, Jaccard 0.004):
# nothing.
#
# Every test here injects a fake client. The suite must never need an API key, and a path whose tests only
# run with one is a path nobody runs.
# =====================================================================================================

class _FakeMessage:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 100, "output_tokens": 50})()


class _FakeClient:
    """Records what it was asked, returns what it was told to."""

    def __init__(self, reply):
        self._reply = reply
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return _FakeMessage(self._reply)


def _reply(records):
    return json.dumps({"records": records})


# --- the contract, enforced on the call itself -------------------------------------------------------

def test_the_call_takes_its_temperature_from_the_SEAM_not_a_literal():
    """Justification-side work: the Council samples warm to generate rivals, an extractor must not. But
    the first live call failed on exactly this -- `claude-sonnet-5` answers 400 "temperature is deprecated
    for this model", and `llm.temperature_for` already returned None for that family. The literal 0.0 in
    this module had bypassed the seam, which is the coupling LLM-7a exists to prevent.

    So the assertion is on the POLICY: whatever the seam says is what is sent, and a model that refuses an
    explicit temperature gets none."""
    from cellarium import llm
    for model in ("claude-haiku-4-5-20251001", "claude-sonnet-5"):
        c = _FakeClient(_reply([]))
        out = extraction.extract_agent(DOC, client=c, model=model)
        want = llm.temperature_for(model)
        if want is None:
            assert "temperature" not in c.calls[0], model
            assert out["temperature_pinned"] is False
            assert "NOT PINNED" in out["note"]
        else:
            assert c.calls[0]["temperature"] == want
            assert out["temperature_pinned"] is True


def test_an_unpinnable_model_says_the_extraction_is_not_reproducible():
    """The consequence, stated rather than left for a reader to work out: two runs disagreeing is then a
    property of the sampler and not a finding about the document."""
    c = _FakeClient(_reply([]))
    out = extraction.extract_agent(DOC, client=c, model="claude-sonnet-5")
    assert out["temperature_pinned"] is False and out["temperature_sent"] is None
    assert "not reproducible" in out["note"].lower()
    assert "temperature_caveat" in extraction.AGENT_PATH_CONTRACT


def test_the_prompt_carries_only_plan_and_claim_spans():
    """It must not be shown the wet-lab section. A model given a bench leg will faithfully extract a bench
    readout, and the quote gate would pass it -- the span is real. The exclusion has to happen before the
    model sees the text, not after."""
    c = _FakeClient(_reply([]))
    extraction.extract_agent(DOC, client=c)
    everything = json.dumps(c.calls)
    # Across all the per-section calls, both readable kinds appear and the bench leg never does.
    assert "Factorial Simulation Matrix" in everything and "Expected Outcomes" in everything
    assert "ribosome profiling" not in everything
    assert "Downstream Laboratory Validation" not in everything


def test_the_prompt_states_the_prohibitions_verbatim_from_the_contract():
    """The contract is the single source. A prompt that paraphrased it could drift from the checked rules."""
    c = _FakeClient(_reply([]))
    extraction.extract_agent(DOC, client=c)
    sent = json.dumps(c.calls[0])
    for rule in extraction.AGENT_PATH_CONTRACT["may_not"]:
        assert rule[:40] in sent, rule


def test_the_declared_role_vocabulary_is_in_the_prompt_rather_than_left_to_the_model():
    c = _FakeClient(_reply([]))
    extraction.extract_agent(DOC, client=c)
    sent = json.dumps(c.calls[0])
    assert "factor:perturbation" in sent and "readout:" in sent


# --- the gate does the work ---------------------------------------------------------------------------

def test_a_record_the_model_cannot_point_at_is_rejected_even_though_it_returned_one():
    """This test used to submit a FABRICATED QUOTE and watch the gate reject it. Through this path it can
    no longer do that: a quote is not the model's to supply, so the way a record now fails is by pointing
    nowhere. The gate itself is unchanged and still tested directly, on hand-built records, in
    `test_an_agent_record_is_held_to_the_same_gate_as_any_other`.

    The model is allowed to be wrong; the platform is not."""
    c = _PerSpanClient([_reply([
        _cited(5, kind="requirement", role="factor:perturbation", value="gene_knockout",
               section="Factorial Simulation Matrix"),
        {"kind": "requirement", "role": "factor:medium", "value": "rich_EZ_aa",
         "quote": "we will use a rich defined medium throughout", "section": "Factorial Simulation Matrix"},
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1 and out["n_rejected"] == 1
    assert out["rejected"][0]["reason"] == "no_line_citation"
    assert all(r.path == "agent" for r in out["kept"])


def test_a_record_naming_an_undeclared_role_is_rejected_before_the_quote_gate():
    """A role the vocabulary does not contain cannot be reconciled with either mechanical path, so it would
    sit in `agent_only` for ever and look like a finding."""
    c = _PerSpanClient([_reply([
        {"kind": "requirement", "role": "factor:astrology", "value": "x", "quote": "Run ID",
         "section": "Factorial Simulation Matrix"},
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_rejected"] == 1 and out["rejected"][0]["reason"] == "undeclared_role"


def test_malformed_model_output_is_an_environment_fault_not_an_empty_extraction():
    """An unparseable reply means we could not look. Returning zero records would be the silent-absence
    shape with a language model as the silent party. Per span, so one bad section is named as such."""
    out = extraction.extract_agent(DOC, client=_FakeClient("not json at all"))
    assert "error" in out and out["about"] == "environment"
    assert out["n_kept"] == 0
    assert all("parsed as JSON" in f["error"] for f in out["span_failures"])
    assert len(out["span_failures"]) == out["n_spans"]


def test_an_api_failure_is_reported_as_environment_and_never_as_corpus():
    class _Boom(_FakeClient):
        def create(self, **kw):
            raise RuntimeError("503 overloaded")
    out = extraction.extract_agent(DOC, client=_Boom(_reply([])))
    assert "error" in out and out["about"] == "environment"
    assert any("503" in f["error"] for f in out["span_failures"])


def test_no_client_and_no_key_refuses_rather_than_pretending_to_run(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(extraction, "_llm_client", lambda **kw: (_ for _ in ()).throw(RuntimeError("no key")))
    out = extraction.extract_agent(DOC)
    assert "error" in out and out["about"] == "environment"


# --- redundancy, which is the point of pointing it at the same roles ---------------------------------

def test_the_agent_path_is_reconciled_against_the_STRUCTURAL_path_on_shared_roles():
    """The mechanical paths were complementary, so their agreement checked nothing. The agent is aimed at
    the roles the structural path already covers, which is what makes agreement informative at all."""
    c = _PerSpanClient([_reply([
        _cited(5, kind="requirement", role="factor:ppgpp_module", value="on",
               section="Factorial Simulation Matrix"),
        _cited(5, kind="requirement", role="factor:perturbation", value="gene_knockout",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_report(DOC, agent_client=c)
    rec = out["agent_vs_structural"]
    assert rec["agreement"]["comparison_kind"] in ("redundant", "partial")
    assert rec["agreement"]["n_agreed"] >= 1
    assert rec["agreement"]["role_overlap"] > 0.0


def test_the_agent_claim_binding_is_what_it_is_for():
    """A claim with a target AND a reference is the thing no pattern produced. 8,654 lexical readout
    mentions bound none."""
    c = _PerSpanClient([_reply([]), _reply([
        _cited(3, kind="claim", role="readout:growth_rate", value="growth rate",
               section="Expected Outcomes", target="argS knockout", reference="wild type",
               direction="down", threshold_pct=20.0),
    ])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1
    claim = out["claims"][0]
    assert claim.target == "argS knockout" and claim.reference == "wild type"
    assert claim.direction == "down" and claim.threshold_pct == 20.0


def test_a_claim_missing_a_reference_is_kept_but_flagged_not_filled():
    """R2: nothing is inferred. "growth falls in the knockout" names no reference, and supplying
    `wildtype/basal` would add a growth medium the hypothesis never chose."""
    c = _PerSpanClient([_reply([]), _reply([
        _cited(3, kind="claim", role="readout:growth_rate", value="growth rate",
               section="Expected Outcomes", target="argS knockout", reference="",
               unfilled={"reference": "the prose names no comparator"}),
    ])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1
    assert out["unfilled"][0]["field"] == "reference"
    assert "no comparator" in out["unfilled"][0]["why"]


def test_a_field_left_unfilled_with_NO_reason_is_rejected():
    """R6: every unfilled field records why, in the transcriber's words. A blank with no reason is
    indistinguishable from a field nobody looked at."""
    c = _PerSpanClient([_reply([]), _reply([
        {"kind": "claim", "role": "readout:growth_rate", "value": "growth rate", "quote": "growth rate",
         "section": "Expected Outcomes", "target": "argS knockout", "reference": ""},
    ])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_rejected"] == 1
    assert out["rejected"][0]["reason"] == "unfilled_without_reason"


def test_the_contract_now_reports_itself_as_implemented():
    assert extraction.AGENT_PATH_CONTRACT["implemented"] is True
    assert extraction.AGENT_PATH_CONTRACT["temperature"] == 0.0
    assert "verify_quotes" in extraction.AGENT_PATH_CONTRACT["gate"]
    # The firm no stands and is still written down.
    assert any("adjudicate its own output" in m for m in extraction.AGENT_PATH_CONTRACT["may_not"])
    assert extraction.AGENT_PATH_CONTRACT["third_path_must_be_mechanical"]


def test_the_module_still_imports_no_provider_sdk():
    """LLM-7a's invariant: `anthropic` is constructed in exactly one module. An extractor that imported it
    directly would reintroduce the coupling the seam exists to remove."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "cellarium", "extraction.py"),
               encoding="utf-8").read()
    assert "import anthropic" not in src
    assert "llm.client" in src or "_llm_client" in src


# --- an EMPTY reply is not an unparseable one ---------------------------------------------------------
#
# Found on the first live call that got past the temperature bug. The 60,073-character report came back
# with NO text block at all, and this module reported "the reply could not be parsed as JSON" -- a
# misattributed cause, which sends anyone diagnosing it at the output format when the problem is the
# budget. A minimal call to the same model returns a text block fine.
#
# It is also Appendix E item 4 reappearing in a new call site: "a reply spent its 4,096-token cap on
# internal reasoning and wrote no text", fixed in the agent loop with one retry at a higher cap and not
# fixed here, because this path was written without consulting that fix.

class _EmptyReplyClient(_FakeClient):
    """No text block, as a reply that spent its budget before writing one."""

    def __init__(self, stop_reason="max_tokens", then=None):
        super().__init__("")
        self._stop = stop_reason
        self._then = then

    def create(self, **kw):
        self.calls.append(kw)
        if self._then is not None and len(self.calls) > 1:
            return _FakeMessage(self._then)
        m = _FakeMessage("")
        m.content = []
        m.stop_reason = self._stop
        return m


def test_an_empty_reply_is_reported_as_empty_and_not_as_unparseable():
    """Per SPAN now, which is the better contract: the cause is attached to the section it belongs to."""
    out = extraction.extract_agent(DOC, client=_EmptyReplyClient(then=None))
    assert "error" in out and out["about"] == "environment"
    f = out["span_failures"][0]
    assert "no text" in f["error"].lower() and f["about"] == "environment"
    assert f["stop_reason"] == "max_tokens"
    assert "parsed" not in f["error"].lower()


def test_an_empty_reply_is_RETRIED_once_with_a_bigger_budget():
    """The precedent from the agent loop: one retry with room, and no third attempt."""
    c = _EmptyReplyClient(then=_reply([
        _cited(5, kind="requirement", role="factor:ppgpp_module", value="on",
               section="Factorial Simulation Matrix")]))
    out = extraction.extract_agent(DOC, client=c, max_tokens=1000)
    assert c.calls[1]["max_tokens"] > c.calls[0]["max_tokens"]
    assert out["retried_for_room"] is True and out["n_kept"] >= 1


def test_a_reply_that_is_still_empty_after_the_retry_gives_up_cleanly():
    c = _EmptyReplyClient(then=None)
    out = extraction.extract_agent(DOC, client=c, max_tokens=1000)
    assert len(c.calls) == 2 * out["n_spans"]      # one retry per span, and no third attempt
    assert out["n_kept"] == 0 and len(out["span_failures"]) == out["n_spans"]


def test_an_unparseable_NON_empty_reply_keeps_its_own_distinct_reason():
    out = extraction.extract_agent(DOC, client=_FakeClient("here is some prose, no JSON at all"))
    f = out["span_failures"][0]
    assert "parsed as JSON" in f["error"]
    assert "no text" not in f["error"].lower()


# --- one call per SECTION, not one per document -------------------------------------------------------
#
# Forced by two live failures in a row on a 60,073-character report. A single prompt carrying every plan and
# claim span came back with no text block at moderate budgets, and the retry at a tripled budget tripped the
# SDK's own guard: "Streaming is required for operations that may take longer than 10 minutes."
#
# Both say the document is the wrong unit. A per-section call is small enough to answer and to parse, keeps
# the quote gate tight on a span the model actually saw, and makes a failure LOCAL -- one unreadable section
# no longer costs the whole document, which is the difference between a partial result and no result.

class _PerSpanClient:
    """Replies per call, from a list. Short replies, as a real per-section call gives."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        r = self._replies.pop(0) if self._replies else _reply([])
        if isinstance(r, Exception):
            raise r
        return _FakeMessage(r)


def test_one_call_is_made_per_located_span():
    spans = extraction._agent_spans(DOC)
    c = _PerSpanClient([_reply([]) for _ in spans])
    out = extraction.extract_agent(DOC, client=c)
    assert len(c.calls) == len(spans) >= 2
    assert out["n_spans"] == len(spans)


def test_each_call_carries_only_its_own_span():
    c = _PerSpanClient([_reply([]), _reply([])])
    extraction.extract_agent(DOC, client=c)
    bodies = [json.dumps(k) for k in c.calls]
    matrix = [b for b in bodies if "Factorial Simulation Matrix" in b]
    outcomes = [b for b in bodies if "Expected Outcomes" in b]
    assert len(matrix) == 1 and len(outcomes) == 1
    # A section's text must not leak into another section's call.
    assert "Expected Outcomes" not in matrix[0]


def test_one_failing_span_does_not_lose_the_document():
    """The point of making the unit smaller. A partial result with the gap named beats no result."""
    c = _PerSpanClient([
        _reply([_cited(5, kind="requirement", role="factor:ppgpp_module", value="on",
                       section="Factorial Simulation Matrix")]),
        RuntimeError("503 overloaded"),
    ])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1
    assert len(out["span_failures"]) == 1
    assert out["span_failures"][0]["about"] == "environment"
    assert "503" in out["span_failures"][0]["error"]
    # And the partial-ness is stated, not left to be inferred from a count.
    assert "partial" in out["note"].lower()


def test_an_empty_reply_on_ONE_span_is_retried_only_for_that_span():
    empty = _FakeMessage("")
    empty.content = []

    class _OneEmpty(_PerSpanClient):
        def create(self, **kw):
            self.calls.append(kw)
            if len(self.calls) == 1:
                m = _FakeMessage("")
                m.content = []
                m.stop_reason = "max_tokens"
                return m
            return _FakeMessage(_reply([]))

    c = _OneEmpty([])
    out = extraction.extract_agent(DOC, client=c, max_tokens=1000)
    assert c.calls[1]["max_tokens"] > c.calls[0]["max_tokens"]
    assert out["retried_for_room"] is True


def test_the_per_span_budget_stays_under_the_streaming_threshold():
    """The second live failure. A budget big enough to need streaming is a budget this path must not ask
    for, so the cap is declared and a retry multiplies within it rather than past it."""
    assert extraction.AGENT_MAX_TOKENS_CAP <= 16000
    c = _PerSpanClient([_reply([]), _reply([])])
    extraction.extract_agent(DOC, client=c, max_tokens=99999)
    assert all(k["max_tokens"] <= extraction.AGENT_MAX_TOKENS_CAP for k in c.calls)


def test_a_document_whose_every_span_fails_says_so_rather_than_returning_zero_records():
    c = _PerSpanClient([RuntimeError("503"), RuntimeError("503")])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 0 and "error" in out and out["about"] == "environment"
    assert len(out["span_failures"]) == 2


# --- W4: a cell-level refusal reached by a TOKEN SHAPE is a verdict by proxy ---------------------------
#
# Probed rather than assumed. The snake_case heuristic was both over- and under-reaching:
#
#   "a nutrient_downshift to acetate"   -> refused_by_gate   (RIGHT, but by accident: it ends in "shift")
#   "a carbon_source_switch mid-run"    -> unresolved        (WRONG: the envelope does refuse a carbon switch)
#
# A verdict that is correct because a word ended in the right four letters is the proxy error this project
# has withdrawn findings for. `refused_by_gate` at CELL level is now reached only for identifiers we
# DECLARE as demanded-and-unavailable; everything else is undecidable at cell level and decided at ROW
# level, where a timeline and a medium exist for the envelope to actually check.

def test_a_declared_unavailable_identifier_is_still_refused_at_cell_level():
    out = adjudicate.classify_cost(adjudicate.Requirement(
        text="generation_timed_knockout", quote="x", section="M", section_kind="plan"))
    assert out["cost"] == "refused_by_gate"
    assert "KNOWN_UNAVAILABLE" in out["authority"] or "VALIDATED_PERTURBATIONS" in out["authority"]


@pytest.mark.parametrize("text", [
    "a nutrient_downshift to acetate",
    "a carbon_source_switch mid-run",
    "an aggressive_depletion_regime",
])
def test_an_UNDECLARED_snake_case_token_is_no_longer_blocked_by_its_shape(text):
    """Not refused and not run: unresolved. We do not know what the identifier is, and a refusal we cannot
    attribute to an authority is worse than an honest unknown -- a false refusal tells a collaborator to
    drop a row."""
    out = adjudicate.classify_cost(adjudicate.Requirement(
        text=text, quote=text, section="M", section_kind="plan"))
    assert out["cost"] == "unresolved", out


def test_the_known_unavailable_set_is_declared_and_disjoint_from_the_validated_one():
    assert adjudicate.KNOWN_UNAVAILABLE_PERTURBATIONS
    assert not (set(adjudicate.KNOWN_UNAVAILABLE_PERTURBATIONS) & set(envelope.VALIDATED_PERTURBATIONS))


def test_a_validated_variant_is_never_refused_however_it_is_spelled():
    for t in ("a graded_gene_knockout at 25%", "a multi_gene_knockout of argS and hisS",
              "an amino_acid_shift at 1800 s", "the ppgpp_conc clamp"):
        out = adjudicate.classify_cost(adjudicate.Requirement(
            text=t, quote=t, section="M", section_kind="plan"))
        assert out["cost"] != "refused_by_gate", t


# --- W5: mapping CORRECTNESS is not mechanically checkable; membership is -----------------------------
#
# Probed. Round-tripping a normalised medium through the envelope does not validate the MAPPING: it
# validates the DESIGN. `Acetate minimal -> minimal_acetate` is a correct mapping whose timeline the
# envelope rightly refuses as a carbon switch, so a round-trip check would have reported a correct mapping
# as broken.
#
# What a machine can check is MEMBERSHIP -- that the produced value is in the authority's set -- and that is
# already enforced at call time. Which member is right is a judgement no check makes. So the mitigation is
# to make the mappings AUDITABLE: list the ones actually applied, not only the ones that failed.

def test_the_coverage_report_lists_the_mappings_it_APPLIED_not_only_the_failures():
    recs = [extraction.Record(kind="requirement", role="factor:medium", value=v, quote="x", section="s",
                              section_kind="plan", path="structural", start=0, end=0)
            for v in ("Glucose minimal", "Acetate minimal", "Glucose minimal", "rich EZ medium")]
    rep = extraction.normalisation_coverage(recs)
    applied = rep["by_role"]["factor:medium"]["applied_mappings"]
    assert applied["Glucose minimal"] == {"value": "minimal", "n": 2}
    assert applied["Acetate minimal"] == {"value": "minimal_acetate", "n": 1}
    assert "rich EZ medium" not in applied          # it did not map; it is in the unnormalised list
    assert "rich EZ medium" in rep["by_role"]["factor:medium"]["unnormalised_values"]


def test_the_report_states_that_membership_is_checked_and_correctness_is_not():
    rep = extraction.normalisation_coverage([])
    assert "membership" in rep["note"].lower()
    assert "correct" in rep["note"].lower()


# --- ADJ-W8: a summary over a PARTIAL extraction is a lower bound, not a count ------------------------
#
# Created by this turn's own per-section change. A document can now come back with some sections unread --
# `span_failures` says so -- but a cost table built from it would report a total with nothing marking it
# incomplete. That is the silent-absence shape one layer down, in the layer added to fix the layer above.
#
# The honest semantics is not "refuse": a partial result is useful. It is that the counts become a LOWER
# BOUND and must say so, because "4 rebuilds" and "at least 4 rebuilds, 3 sections unread" license
# different decisions.

def test_a_cost_summary_told_it_is_partial_reports_a_lower_bound():
    reqs = [adjudicate.Requirement(text="operons", quote="operons", section="M", section_kind="plan")]
    out = adjudicate.cost_summary(reqs, partial=True, n_unread=3)
    assert out["partial"] is True and out["n_unread_sections"] == 3
    assert out["by_cost"]["rebuild"] == 1
    assert "lower bound" in out["note"].lower()


def test_a_complete_cost_summary_says_it_is_complete():
    out = adjudicate.cost_summary([], partial=False)
    assert out["partial"] is False
    assert "lower bound" not in out["note"].lower()


def test_the_cost_breakdown_carries_partiality_too():
    recs = [extraction.Record(kind="requirement", role="factor:operons", value="operons", quote="operons",
                              section="M", section_kind="plan", path="agent", start=0, end=0)]
    out = extraction.cost_breakdown(recs, partial=True, n_unread=2)
    assert out["partial"] is True and out["n_unread_sections"] == 2
    assert "lower bound" in out["note"].lower()


def test_a_row_summary_inherits_partiality_from_the_extraction_it_was_built_from():
    out = extraction.row_cost_summary(DOC, partial=True, n_unread=1)
    assert out["partial"] is True and out["n_unread_sections"] == 1
    assert "lower bound" in out["note"].lower()


def test_extract_report_hands_the_partial_flag_on_rather_than_leaving_it_to_be_noticed():
    """The flag has to travel. A caller who must remember to look at `span_failures` and then set a
    parameter by hand is a caller who will forget once."""
    c = _PerSpanClient([_reply([]), RuntimeError("503")])
    out = extraction.extract_report(DOC, agent_client=c)
    assert out["agent"]["partial"] is True
    assert out["agent"]["n_unread_sections"] == 1


# --- the extractor pins its OWN zero, not the global temperature --------------------------------------
#
# Caught before shipping, by asking what the seam actually returns rather than trusting the field name.
# `llm.temperature_for` returns `CELLARIUM_TEMPERATURE`, which is the Cellwright/global knob -- the Council
# already pins its own separately, by purpose. So an operator raising the global for a sweep would have made
# this extractor sample WARM while it reported `temperature_pinned: True`.
#
# "Pinned" is not "deterministic": a fixed 0.7 still samples. A transcription step that samples is a
# transcription step whose two runs may differ for reasons that are not about the document -- which is the
# exact claim `temperature_pinned` is read as denying.

def test_the_extractor_pins_zero_even_when_the_global_temperature_is_warm(monkeypatch):
    """Patched with setattr, NOT by reloading the module.

    The first version of this test set the environment variable and reloaded `llm` to pick it up. A reload
    REBINDS `llm.temperature_for` to a new function object, and `agent` imported that name earlier, so
    `agent.temperature_for is llm.temperature_for` stopped holding and `test_llm_seam.py` failed -- in the
    full suite only, because a two-file run imports `agent` fresh afterwards and the identity happens to
    match again. Order-dependent breakage in another file, from a test of mine: the defect
    `tests/conftest.py` was written to end. `setattr` patches the value monkeypatch can restore and rebinds
    nothing."""
    from cellarium import llm
    monkeypatch.setattr(llm, "TEMPERATURE", 0.7)
    assert llm.temperature_for("claude-haiku-4-5-20251001") == 0.7      # the global really is warm
    c = _FakeClient(_reply([]))
    out = extraction.extract_agent(DOC, client=c, model="claude-haiku-4-5-20251001")
    assert c.calls[0]["temperature"] == 0.0, "the extractor must pin its own zero"
    assert out["temperature_sent"] == 0.0 and out["temperature_pinned"] is True


def test_a_model_that_refuses_a_temperature_still_gets_none(monkeypatch):
    """The seam's other job is unchanged: a family that answers 400 to an explicit temperature gets none,
    and the result says sampling is not pinned."""
    c = _FakeClient(_reply([]))
    out = extraction.extract_agent(DOC, client=c, model="claude-sonnet-5")
    assert "temperature" not in c.calls[0]
    assert out["temperature_pinned"] is False


def test_pinned_means_ZERO_and_nothing_else(monkeypatch):
    """The field is read as a reproducibility claim, so it must not be true for a fixed non-zero value.
    Checked on the BEHAVIOUR rather than on the source text -- the first version of this test looked for the
    literal "0.0" inside the function, which lives in a named constant outside it, so it was testing where
    the number is written rather than what is sent."""
    assert extraction.EXTRACTOR_TEMPERATURE == 0.0
    from cellarium import llm
    monkeypatch.setattr(llm, "TEMPERATURE", 0.9)
    assert extraction._temperature_for("claude-haiku-4-5-20251001") == 0.0
    c = _FakeClient(_reply([]))
    out = extraction.extract_agent(DOC, client=c, model="claude-haiku-4-5-20251001")
    # The flag is true only because the value IS zero, never because a value was sent.
    assert out["temperature_sent"] == 0.0 and out["temperature_pinned"] is True


# --- W9: the quote is CUT BY THE PLATFORM, never copied by the model ----------------------------------
#
# The measured failure, on the first live section this path ever read: 10 records proposed, 10 rejected for
# `quote_not_in_source`, and the cause was not markup. Checked all three ways it could have been innocent --
# exact matches 0, matches after the declared table-stripping 0, genuinely absent 10. The model rewrote the
# content and offered the rewrite as quotation. Asking harder is not a fix; the prompt already said
# "character for character" in capitals.
#
# So the opportunity is removed instead. The model is shown NUMBERED units and asked which units a record is
# stated on; the platform cuts the quote from those units. A quote is then verbatim BY CONSTRUCTION, and the
# gate stays in place as a check on the construction rather than on the model's compliance.
#
# The residual risk moves rather than vanishing: a real span can be cited for a record it does not support.
# Verbatim is not the same as relevant, and that is measured (`n_value_outside_quote`), not assumed away.

LONG_PROSE = ("We will hold the medium fixed across every arm. "
              "The target setpoint is 0.85 in the high arm and 0.55 in the low arm. " * 8)


def test_citable_units_tile_the_span_exactly():
    """The whole construction rests on this. If the units do not tile the span, a cut across two of them is
    not a substring of anything and "verbatim by construction" is a slogan."""
    units = extraction.citable_units(DOC)
    assert units
    assert units[0]["start"] == 0 and units[-1]["end"] == len(DOC)
    for u, nxt in zip(units, units[1:]):
        assert u["end"] == nxt["start"], (u, nxt)
    for u in units:
        assert DOC[u["start"]:u["end"]] == u["text"]
    assert [u["n"] for u in units] == list(range(1, len(units) + 1))


def test_a_long_unwrapped_paragraph_is_split_into_sentence_sized_units():
    """Measured need, not a guess: over the development set 11.7% of the lines in a plan or claim span run
    past 300 characters and the widest is 1,596. A citation that resolves to a 1,596-character paragraph is
    verbatim and useless, and it would make a quote's size a property of how the OUTSIDE producer wraps its
    text."""
    units = extraction.citable_units(LONG_PROSE)
    assert len(units) > 1
    assert max(len(u["text"]) for u in units) <= extraction.CITABLE_UNIT_MAX
    assert "".join(u["text"] for u in units) == LONG_PROSE


def test_a_long_line_with_no_sentence_boundary_stays_ONE_unit_and_is_not_truncated():
    """A long row with no sentence to break on stays one unit at full length: the document's shape is
    reported, and cutting a row in half to meet a target width would invent a boundary the text does not
    have. The fixture is the pathological case rather than the common one -- measured, real table rows in
    the archive top out at 352 characters and only 3 of the 479 over-300 units are rows; most are a single
    long sentence, which is the right unit anyway."""
    row = "| " + " | ".join("cell%d" % i for i in range(120)) + " |"
    assert len(row) > extraction.CITABLE_UNIT_MAX
    units = extraction.citable_units(row)
    assert len(units) == 1 and units[0]["text"] == row


def test_the_numbered_body_carries_one_number_per_unit():
    units = extraction.citable_units(DOC)
    body = extraction.numbered_body(units)
    assert body.count("\n") >= len(units) - 1
    for u in units[:5]:
        assert "L%04d" % u["n"] in body


def test_a_cut_is_a_contiguous_substring_of_the_span():
    units = extraction.citable_units(DOC)
    got = extraction.cut_cited(DOC, units, [5, 6])
    assert not got["reason"]
    assert got["quote"] in DOC
    assert "Run ID" in got["quote"]


def test_a_citation_of_NON_CONTIGUOUS_units_cuts_the_RANGE_rather_than_a_splice():
    """Joining unit 3 to unit 5 would produce text that appears nowhere in the document -- a fabricated
    quote manufactured by the platform rather than by the model. The cut is the RANGE, so what comes back is
    always something a reader can find."""
    units = extraction.citable_units(DOC)
    got = extraction.cut_cited(DOC, units, [3, 5])
    # Stripped at the ends, which keeps it a substring: whitespace trimmed off a substring leaves one.
    assert got["quote"] == DOC[units[2]["start"]:units[4]["end"]].strip()
    assert got["quote"] in DOC
    assert got["units"] == [3, 4, 5]
    assert "WIDENED" in got["note"]


def test_a_record_with_no_citation_is_rejected_with_its_own_reason():
    units = extraction.citable_units(DOC)
    for empty in ([], None, "", {}):
        got = extraction.cut_cited(DOC, units, empty)
        assert got["reason"] == "no_line_citation", empty
        assert got["quote"] == ""


def test_a_citation_outside_the_span_is_rejected_rather_than_clamped():
    """Clamping would turn a wrong citation into a confident quote of whatever happens to sit at the
    boundary -- the expensive direction, because the result then looks evidenced."""
    units = extraction.citable_units(DOC)
    assert extraction.cut_cited(DOC, units, [len(units) + 5])["reason"] == "line_out_of_range"
    assert extraction.cut_cited(DOC, units, [0])["reason"] == "line_out_of_range"


def test_a_citation_wider_than_the_cap_is_rejected():
    """A whole section is not a quote. The cap is declared, so the refusal is a rule and not a feeling."""
    units = extraction.citable_units(LONG_PROSE)
    assert len(units) > extraction.MAX_CITED_UNITS
    wide = [1, extraction.MAX_CITED_UNITS + 1]
    assert extraction.cut_cited(LONG_PROSE, units, wide)["reason"] == "line_citation_too_wide"


def test_the_citation_field_accepts_the_SHAPES_A_MODEL_ACTUALLY_WRITES():
    """Generous about the reference, strict about the cut. A citation is a pointer, so a model writing
    "L0003" or "3-4" instead of 3 is a formatting difference; rejecting it would discard a record whose
    evidence is fine."""
    units = extraction.citable_units(DOC)
    want = extraction.cut_cited(DOC, units, [3, 4])["quote"]
    for shape in (["L0003", "L0004"], ["3-4"], "3-4", [3, "4"], {"lines": [3, 4]}):
        got = extraction.cut_cited(DOC, units, shape)
        assert got["quote"] == want, shape


def test_a_unit_table_FROM_THE_WRONG_SPAN_is_caught_rather_than_trusted():
    """Forcing the construction claim to fail. "Verbatim by construction" holds only while the units belong
    to the text being cut; hand it a mismatched source and the membership check must catch it, or the claim
    is decoration."""
    units = extraction.citable_units(LONG_PROSE)
    got = extraction.cut_cited(LONG_PROSE, units, [1, 2])
    assert not got["reason"]
    bad = extraction.cut_cited(LONG_PROSE, units, [1, 2], source=DOC)
    assert bad["reason"] == "cut_not_in_source"


# --- and what it does to the live path ---------------------------------------------------------------

def _cited(n, **kw):
    """A model reply record that cites units instead of copying text."""
    return dict(lines=(n if isinstance(n, list) else [n]), **kw)


def test_a_model_that_REWRITES_the_text_can_no_longer_fabricate_a_quote():
    """The W9 finding, made harmless. The reply paraphrases -- exactly what the live run did ten times out
    of ten -- and the record is still kept, with a quote the document actually contains, because the quote
    is not the model's to supply."""
    c = _PerSpanClient([_reply([
        _cited(5, kind="requirement", role="factor:perturbation", value="gene_knockout",
               quote="the first arm knocks out a gene", section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1 and out["n_rejected"] == 0
    kept = out["kept"][0]
    assert kept.quote in DOC
    assert "gene_knockout" in kept.quote
    # The behaviour that forced this design is still there. It just cannot reach the output any more, and it
    # is COUNTED rather than silently discarded.
    assert out["n_rewrote"] == 1
    assert "own wording" in out["note"]


def test_a_reply_that_offers_no_quote_at_all_is_fine_because_none_was_asked_for():
    c = _PerSpanClient([_reply([
        _cited([3, 5], kind="requirement", role="factor:target_charging", value="0.55",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1
    assert out["kept"][0].quote in DOC
    assert out["n_rewrote"] == 0


def test_every_kept_record_passes_the_quote_gate_BY_CONSTRUCTION():
    c = _PerSpanClient([_reply([
        _cited(5, kind="requirement", role="factor:ppgpp_module", value="on",
               section="Factorial Simulation Matrix"),
        _cited(6, kind="requirement", role="factor:ppgpp_module", value="off",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 2
    assert not [r for r in out["rejected"] if str(r.get("reason", "")).startswith("quote_")]
    assert all(r.quote in DOC for r in out["kept"])
    assert out["quotes_cut_by_platform"] is True


def test_a_citation_the_platform_cannot_use_is_rejected_and_named():
    c = _PerSpanClient([_reply([
        {"kind": "requirement", "role": "factor:ppgpp_module", "value": "on",
         "section": "Factorial Simulation Matrix"},
        _cited(999, kind="requirement", role="factor:medium", value="minimal",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 0 and out["n_rejected"] == 2
    assert set(r["reason"] for r in out["rejected"]) == {"no_line_citation", "line_out_of_range"}


def test_a_real_span_cited_for_a_record_it_does_not_support_is_kept_but_COUNTED():
    """Where the risk went. The quote can no longer be invented, so the remaining way to be wrong is to
    cite a true span for the wrong record -- verbatim and irrelevant. Not a refusal: a claim may legitimately
    be stated in words that never repeat its level. But counted, so nobody reads a construction guarantee as
    a guarantee of relevance."""
    c = _PerSpanClient([_reply([
        _cited(1, kind="requirement", role="factor:target_charging", value="0.85",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1
    assert out["n_value_outside_quote"] == 1
    assert "0.85" not in out["kept"][0].quote
    assert "does not contain" in out["note"]


def test_the_prompt_shows_NUMBERED_units_and_asks_for_numbers():
    c = _PerSpanClient([_reply([]), _reply([])])
    extraction.extract_agent(DOC, client=c)
    sent = json.dumps(c.calls[0])
    assert "L0001" in sent and "L0003" in sent
    assert "lines" in sent


def test_the_contract_asks_for_LINE_NUMBERS_rather_than_a_copied_quote():
    """The contract is what the prompt is built from, so the change has to land there or the prompt and the
    checked rules drift apart."""
    c = extraction.AGENT_PATH_CONTRACT
    assert any("cite" in m.lower() and "number" in m.lower() for m in c["must"])
    assert not any("quote a verbatim span" in m for m in c["must"])
    assert any("retype" in m.lower() or "ignored" in m.lower() for m in c["may_not"])
    assert "quote_provenance" in c
    assert "10" in c["quote_provenance"]


# --- where the rewriting went, and the instrument that nearly missed it -------------------------------
#
# The first live run of the fixed path, on two development reports: 333 records kept, 0 quotes that were not
# verbatim spans -- the construction holds -- and 298 of the 333 reporting "the cited span does not contain
# this value". A 90% rate, and almost all of it was the INSTRUMENT'S fault: those are `note` records, whose
# value is the transcriber's own sentence about the span. Asking a free-text field to appear verbatim inside
# its own evidence asks the format to be something it is not.
#
# The paraphrase is still the finding, and it has to be counted somewhere else: the model no longer offers a
# reworded QUOTE, it offers a reworded NOTE sitting beside a real quote, and a reader skimming the pair can
# take the note for the document's words.

def test_a_NOTE_that_states_its_span_in_other_words_is_not_an_unsupported_VALUE():
    c = _PerSpanClient([_reply([
        _cited(8, kind="requirement", role="note",
               value="the second arm turns operons off and uses the kinetic model",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1
    assert out["n_value_outside_quote"] == 0          # not a level, so not an unsupported level
    assert out["n_free_text_records"] == 1
    assert out["n_free_text_paraphrased"] == 1        # but counted, because this is where rewriting went
    assert "own words" in out["note"]


def test_a_LEVEL_role_is_still_held_to_its_cited_span():
    """The split must not become an excuse. A factor level is a token the document either carries or does
    not, and that one is still measured."""
    c = _PerSpanClient([_reply([
        _cited(1, kind="requirement", role="factor:target_charging", value="0.85",
               section="Factorial Simulation Matrix"),
        _cited(6, kind="requirement", role="factor:ppgpp_module", value="off",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_level_records"] == 2 and out["n_free_text_records"] == 0
    assert out["n_value_outside_quote"] == 1


def test_the_kept_count_says_how_much_of_it_is_FREE_TEXT():
    """Measured need: the first live report kept 148 records and most were notes. "148 kept" read as 148
    design facts would be an overstatement of nearly ten times."""
    c = _PerSpanClient([_reply([
        _cited(8, kind="requirement", role="note", value="we will run these with the kinetic elongation "
                                                         "model", section="Factorial Simulation Matrix"),
        _cited(5, kind="requirement", role="factor:ppgpp_module", value="on",
               section="Factorial Simulation Matrix"),
    ]), _reply([])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 2
    assert out["n_level_records"] == 1 and out["n_free_text_records"] == 1
    assert "not a count of design facts" in out["note"]


def test_a_READOUT_record_describing_what_it_predicts_is_prose_not_an_unsupported_level():
    """The second correction to this instrument. Excluding only note/id still left 97 of 104 records
    reporting an unsupported value, because a `readout:` record has its channel pinned by the ROLE and uses
    the value to say what is predicted -- "uncharged tRNA <2% during hardware dilution" is a sentence, not a
    level. The line is drawn where the platform will later resolve the value against a declared vocabulary,
    which is the `factor:` roles and nothing else."""
    c = _PerSpanClient([_reply([]), _reply([
        _cited(3, kind="claim", role="readout:growth_rate",
               value="growth slows markedly in the knockout", section="Expected Outcomes",
               target="argS knockout", reference="wild type", direction="down", threshold_pct=20.0),
    ])])
    out = extraction.extract_agent(DOC, client=c)
    assert out["n_kept"] == 1
    assert out["n_level_records"] == 0 and out["n_free_text_records"] == 1
    assert out["n_value_outside_quote"] == 0
    assert extraction._is_level_role("factor:medium") is True
    assert extraction._is_level_role("readout:growth_rate") is False
