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

def test_the_agent_path_is_declared_with_a_contract_and_is_not_implemented():
    """An agent path is the plausible third calculation, and the contract it must satisfy exists before any
    of it is written: quote-backed fields only, temperature 0, and the mechanical verifier as its gate."""
    c = extraction.AGENT_PATH_CONTRACT
    assert c["implemented"] is False
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
